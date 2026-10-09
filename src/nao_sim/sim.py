"""`NaoSim`: the one object that runs a simulated NAO on the host (specs/runtime/api.md).

Built from a `NaoSimConfig`, its `start()` checks the machine, starts the audio output, the
containers and the simulated world, and returns once the robot is ready; `stop()` takes them
all down. Every step that starts something registers how to undo it, so a failed start, a
cancelled one and `stop()` share one teardown, run in reverse.
"""

import asyncio
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

from nao_sim import docker_images, stack
from nao_sim.audio_output import (
    AudioOutput,
    AudioSink,
    DevicePlayer,
    NullSink,
    Server,
    WavSink,
)
from nao_sim.config import NaoqiSettings, NaoqiVersion, NaoSimConfig
from nao_sim.errors import DeviceNotBuiltError, NaoSimError, NotRunningError
from nao_sim.stack import AUDIO_OUTPUT_PORT, NAOQI_PORT, URL, NaoSimStatus
from nao_sim.viewer import SimWorld, needs_viewer, viewer_config

log = logging.getLogger(__name__)


def _sink_for(config: NaoSimConfig) -> AudioSink:
    settings = config.audio_output
    if settings.mode == "record":
        assert settings.record is not None  # checked by the config
        return WavSink(settings.record)
    if settings.mode == "silent":
        return NullSink()
    return DevicePlayer()


class NaoSim:
    """A simulated NAO: `await start()`, connect any qi client to `url`, `await stop()`."""

    def __init__(
        self,
        config: NaoSimConfig | NaoqiVersion | None = None,
        *,
        sink: AudioSink | None = None,
    ):
        if config is None:
            config = NaoSimConfig()
        elif isinstance(config, str):
            config = NaoSimConfig(naoqi=NaoqiSettings(version=config))
        self._config = config
        self._sink = sink if sink is not None else _sink_for(config)
        self._undo: list[tuple[str, Callable[[], None]]] = []
        self._running = False
        self._busy = asyncio.Lock()

    @classmethod
    def from_dict(cls, data: Any, *, sink: AudioSink | None = None) -> Self:
        return cls(NaoSimConfig.from_dict(data), sink=sink)

    @classmethod
    def from_json(cls, text: str, *, sink: AudioSink | None = None) -> Self:
        return cls(NaoSimConfig.from_json(text), sink=sink)

    @classmethod
    def from_json_file(cls, path: str | Path, *, sink: AudioSink | None = None) -> Self:
        return cls(NaoSimConfig.from_json_file(path), sink=sink)

    @property
    def config(self) -> NaoSimConfig:
        return self._config

    @property
    def running(self) -> bool:
        return self._running

    @property
    def url(self) -> str:
        if not self._running:
            raise NotRunningError("this NaoSim is not running: await start() first")
        return URL

    async def status(self) -> NaoSimStatus:
        """What the `NaoSim` service reports, read over qi."""
        self.url  # noqa: B018  (raises NotRunningError)
        return await asyncio.to_thread(stack.read_naosim_status, URL)

    # --- Lifecycle ------------------------------------------------------------------

    async def start(self) -> None:
        """Check the machine, start everything, and return once the robot is ready."""
        async with self._busy:
            if self._running:
                raise NaoSimError("this NaoSim is already running")
            try:
                world_config = await asyncio.to_thread(self._check)
                await asyncio.to_thread(self._start_audio_output)
                await asyncio.to_thread(self._start_containers)
                await asyncio.to_thread(stack.wait_ready, self._config)
                if world_config is not None:
                    await asyncio.to_thread(self._start_world, world_config)
            except BaseException:
                await asyncio.to_thread(self._teardown, False)
                raise
            self._running = True
            log.info("nao-sim ready at %s", URL)

    async def stop(self) -> None:
        """Stop the simulated world, the containers and the audio output; a no-op when not
        running. Carries on through every step and raises the first failure."""
        async with self._busy:
            if not self._running:
                return
            self._running = False
            await asyncio.to_thread(self._teardown, True)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # --- Steps ----------------------------------------------------------------------

    def _check(self) -> Any:
        """Step 1: what the machine must offer before anything starts. Returns the viewer's
        config when the simulated world runs, else None."""
        config = self._config
        docker_images.require_docker()
        docker_images.check_images(config.naoqi.version)
        world_config = (
            viewer_config(config.viewer, URL) if needs_viewer(config) else None
        )
        for device, source in (
            ("audio_input", config.audio_input.source),
            ("video_input", config.video_input.source),
        ):
            if source != "none":
                raise DeviceNotBuiltError(
                    f"{device}.source {source!r}: the {device.replace('_', ' ')} is not "
                    "built yet; set it to 'none'"
                )
        docker_images.require_free(NAOQI_PORT)
        docker_images.require_free(AUDIO_OUTPUT_PORT)
        return world_config

    def _start_audio_output(self) -> None:
        server = Server(("0.0.0.0", AUDIO_OUTPUT_PORT), AudioOutput(self._sink))
        thread = threading.Thread(
            target=server.serve_forever, name="nao-sim-audio-output", daemon=True
        )
        thread.start()

        def stop_audio_output() -> None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            if isinstance(self._sink, WavSink):
                self._sink.close()

        self._undo.append(("audio output", stop_audio_output))

    def _start_containers(self) -> None:
        version = self._config.naoqi.version
        # Registered first: a failed `up` may have started some of them.
        self._undo.append(("containers", lambda: stack.down(version)))
        stack.up(self._config)

    def _start_world(self, world_config: Any) -> None:
        world = SimWorld(world_config)
        self._undo.append(("viewer", world.close))
        world.launch()

    def _teardown(self, raise_first: bool) -> None:
        """Undo every started step, newest first, through failures."""
        first: BaseException | None = None
        while self._undo:
            name, undo = self._undo.pop()
            try:
                undo()
            except Exception as e:  # noqa: BLE001 (stop carries on through every step)
                log.error("nao-sim stop: %s failed: %s", name, e)
                first = first or e
        if raise_first and first is not None:
            raise first
