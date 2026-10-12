"""`NaoqiSim`: the one object that runs a simulated NAO on the host (specs/runtime/api.md).

Built from a `NaoqiSimConfig`, its `start()` checks the machine, starts the audio output and the host
link, the containers, the simulated world, the video input and the audio input, and returns once
the robot is ready; `stop()` takes them all down. Every step that starts something registers how to undo it, so a failed start, a
cancelled one and `stop()` share one teardown, run in reverse.
"""

import asyncio
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

from naoqi_sim import docker_images, stack
from naoqi_sim.audio_input import AudioInput, FakeAudioSource, MicSource, check_mic
from naoqi_sim.audio_output import (
    AudioOutput,
    AudioSink,
    DevicePlayer,
    NullSink,
    Server,
    WavSink,
)
from naoqi_sim.config import NaoqiSettings, NaoqiSimConfig, NaoqiVersion
from naoqi_sim.errors import DeviceNotBuiltError, NaoqiSimError, NotRunningError
from naoqi_sim.host_link import HostLink
from naoqi_sim.stack import (
    AUDIO_OUTPUT_PORT,
    HOST_LINK_PORT,
    NAOQI_PORT,
    URL,
    NaoqiSimStatus,
)
from naoqi_sim.video_input import RenderSource, VideoInput
from naoqi_sim.viewer import SimWorld, needs_viewer, viewer_config

log = logging.getLogger(__name__)


def _sink_for(config: NaoqiSimConfig) -> AudioSink:
    settings = config.audio_output
    if settings.mode == "record":
        assert settings.record is not None  # checked by the config
        return WavSink(settings.record)
    if settings.mode == "silent":
        return NullSink()
    return DevicePlayer()


class NaoqiSim:
    """A simulated NAO: `await start()`, connect any qi client to `url`, `await stop()`."""

    def __init__(
        self,
        config: NaoqiSimConfig | NaoqiVersion | None = None,
        *,
        sink: AudioSink | None = None,
    ):
        if config is None:
            config = NaoqiSimConfig()
        elif isinstance(config, str):
            config = NaoqiSimConfig(naoqi=NaoqiSettings(version=config))
        self._config = config
        self._sink = sink if sink is not None else _sink_for(config)
        self._audio_output: AudioOutput | None = None
        self._link: HostLink | None = None
        self._audio_input: AudioInput | None = None
        self._undo: list[tuple[str, Callable[[], None]]] = []
        self._running = False
        self._busy = asyncio.Lock()

    @classmethod
    def from_dict(cls, data: Any, *, sink: AudioSink | None = None) -> Self:
        return cls(NaoqiSimConfig.from_dict(data), sink=sink)

    @classmethod
    def from_json(cls, text: str, *, sink: AudioSink | None = None) -> Self:
        return cls(NaoqiSimConfig.from_json(text), sink=sink)

    @classmethod
    def from_json_file(cls, path: str | Path, *, sink: AudioSink | None = None) -> Self:
        return cls(NaoqiSimConfig.from_json_file(path), sink=sink)

    @property
    def config(self) -> NaoqiSimConfig:
        return self._config

    @property
    def running(self) -> bool:
        return self._running

    @property
    def url(self) -> str:
        if not self._running:
            raise NotRunningError("this NaoqiSim is not running: await start() first")
        return URL

    @property
    def fake_audio(self) -> FakeAudioSource:
        """The fake audio source, which a test plays sounds through (specs/host/audio-input.md)."""
        self.url  # noqa: B018  (raises NotRunningError)
        source = self._audio_input.source if self._audio_input is not None else None
        if not isinstance(source, FakeAudioSource):
            raise NaoqiSimError(
                f"audio_input.source is {self._config.audio_input.source!r}, not 'fake': "
                "no fake audio source to play into"
            )
        return source

    async def status(self) -> NaoqiSimStatus:
        """What the `NaoqiSim` service reports, read over qi."""
        self.url  # noqa: B018  (raises NotRunningError)
        return await asyncio.to_thread(stack.read_naoqisim_status, URL)

    # --- Lifecycle ------------------------------------------------------------------

    async def start(self) -> None:
        """Check the machine, start everything, and return once the robot is ready."""
        async with self._busy:
            if self._running:
                raise NaoqiSimError("this NaoqiSim is already running")
            try:
                world_config = await asyncio.to_thread(self._check)
                await asyncio.to_thread(self._start_audio_output)
                await asyncio.to_thread(self._start_containers)
                await asyncio.to_thread(stack.wait_ready, self._config)
                world = None
                if world_config is not None:
                    world = await asyncio.to_thread(self._start_world, world_config)
                if world is not None and self._config.video_input.source == "render":
                    await asyncio.to_thread(self._start_video_input, world)
                if self._config.audio_input.source != "none":
                    await asyncio.to_thread(self._start_audio_input)
            except BaseException:
                await asyncio.to_thread(self._teardown, False)
                raise
            self._running = True
            log.info("naoqi-sim ready at %s", URL)

    async def stop(self) -> None:
        """Stop the audio and video inputs, the simulated world, the containers, the host link and
        the audio output; a no-op when not running. Carries on through every step and raises the
        first failure."""
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
        for device, source, built in (
            ("audio_input", config.audio_input.source, ("none", "mic", "fake")),
            ("video_input", config.video_input.source, ("none", "render")),
        ):
            if source not in built:
                raise DeviceNotBuiltError(
                    f"{device}.source {source!r}: the {device.replace('_', ' ')} is not "
                    "built yet; set it to 'none'"
                )
        if config.audio_input.source == "mic":
            check_mic()
        docker_images.require_free(NAOQI_PORT)
        docker_images.require_free(AUDIO_OUTPUT_PORT)
        if config.audio_input.source != "none":
            docker_images.require_free(HOST_LINK_PORT)
        return world_config

    def _start_audio_output(self) -> None:
        self._audio_output = AudioOutput(self._sink)
        server = Server(("0.0.0.0", AUDIO_OUTPUT_PORT), self._audio_output)
        thread = threading.Thread(
            target=server.serve_forever, name="naoqi-sim-audio-output", daemon=True
        )
        thread.start()

        def stop_audio_output() -> None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            if isinstance(self._sink, WavSink):
                self._sink.close()

        self._undo.append(("audio output", stop_audio_output))
        if self._config.audio_input.source != "none":
            # Open before the containers boot, so ALAudioDevice finds it; closed after them.
            self._link = HostLink(HOST_LINK_PORT)
            self._undo.append(("host link", self._close_link))

    def _close_link(self) -> None:
        link, self._link = self._link, None
        if link is not None:
            link.close()

    def _start_containers(self) -> None:
        version = self._config.naoqi.version
        # Registered first: a failed `up` may have started some of them.
        self._undo.append(("containers", lambda: stack.down(version)))
        stack.up(self._config)

    def _start_world(self, world_config: Any) -> SimWorld:
        world = SimWorld(world_config)
        self._undo.append(("viewer", world.close))
        world.launch()
        return world

    def _start_video_input(self, world: SimWorld) -> None:
        device = VideoInput(RenderSource(world), self._config.video_input.fps)
        # Registered after the viewer's, so the teardown stops it first.
        self._undo.append(("video input", device.stop))
        device.start()

    def _start_audio_input(self) -> None:
        settings = self._config.audio_input
        assert self._link is not None and self._audio_output is not None
        source = (
            FakeAudioSource(settings.mono)
            if settings.source == "fake"
            else MicSource(settings.mono)
        )
        device = AudioInput(source, settings.mono)
        self._audio_input = device
        if isinstance(source, FakeAudioSource):  # the fake room hears the robot speak
            self._audio_output.listeners.append(source.hear)
        # Registered last, so the teardown stops it first.
        self._undo.append(("audio input", self._stop_audio_input))
        self._link.register(AudioInput.service, device)
        device.start()

    def _stop_audio_input(self) -> None:
        device, self._audio_input = self._audio_input, None
        if device is not None:
            device.stop()

    def _teardown(self, raise_first: bool) -> None:
        """Undo every started step, newest first, through failures."""
        first: BaseException | None = None
        while self._undo:
            name, undo = self._undo.pop()
            try:
                undo()
            except Exception as e:  # noqa: BLE001 (stop carries on through every step)
                log.error("naoqi-sim stop: %s failed: %s", name, e)
                first = first or e
        if raise_first and first is not None:
            raise first
