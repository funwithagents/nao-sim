"""The `NaoSim` object's lifecycle, against the fake `docker` (tests/fake_docker.py): what it
checks before starting anything, the order it starts things in, and that a failed start, a
cancelled one and `stop()` leave nothing running. The audio output is real, on a free port; the
image check and nao-viewer are replaced, each by a recorder."""

import asyncio
import json
import socket
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from nao_sim import docker_images, sim, stack
from nao_sim.audio_output import MemorySink
from nao_sim.config import (
    AudioInputSettings,
    AudioOutputSettings,
    NaoqiSettings,
    NaoSimConfig,
    SpeechSettings,
    VideoInputSettings,
    ViewerSettings,
)
from nao_sim.errors import (
    BootError,
    DeviceNotBuiltError,
    ImagesMissingError,
    MissingExtraError,
    NaoSimError,
    NotRunningError,
    PortInUseError,
)

HEADLESS = ViewerSettings(headless=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Viewer:
    """Stands in for nao-viewer: records the config it was given and its lifecycle."""

    def __init__(self):
        self.events: list[str] = []
        self.config = None
        self.launch_fails = False

    def viewer_config(self, settings, url):
        self.config = (settings, url)
        return "viewer-config"

    def world(self, config):
        viewer = self

        class World:
            def launch(self):
                viewer.events.append(f"launch {config}")
                if viewer.launch_fails:
                    raise RuntimeError("no display")

            def camera_frame(self, camera, width, height):
                return np.zeros((height, width, 3), np.uint8)

            def close(self):
                viewer.events.append("close")

        return World()


class Naoqi:
    """The qi session the video input opens: records frames and ALMemory writes into the
    viewer stand-in's event list, so their order against the viewer's lifecycle shows."""

    def __init__(self, events: list[str]):
        self.events = events
        self.frames = 0

    def service(self, name):
        return self

    def putImage(self, camera, width, height, data):
        self.frames += 1
        if self.frames == 1:
            self.events.append(f"frame {camera} {width}x{height}")
        return True

    def insertData(self, key, value):
        self.events.append(f"{key} = {value}")

    def close(self):
        pass


@pytest.fixture
def env(docker, monkeypatch):
    """The fake Docker with the images in place, free ports, and a stand-in viewer."""
    checked: list[str] = []
    monkeypatch.setattr(docker_images, "check_images", checked.append)
    monkeypatch.setattr(sim, "NAOQI_PORT", free_port())
    monkeypatch.setattr(sim, "AUDIO_OUTPUT_PORT", free_port())
    viewer = Viewer()
    monkeypatch.setattr(sim, "viewer_config", viewer.viewer_config)
    monkeypatch.setattr(sim, "SimWorld", viewer.world)
    naoqi = Naoqi(viewer.events)
    monkeypatch.setattr(stack, "connect", lambda: naoqi)
    docker.checked = checked  # type: ignore[attr-defined]
    docker.viewer = viewer  # type: ignore[attr-defined]
    return docker


def compose_calls(docker) -> list[str]:
    return [c for c in docker.calls if c.startswith("compose")]


def play(port: int, seconds: float = 0.2, rate: int = 8000) -> None:
    header = {"cmd": "play", "rate": rate, "channels": 1, "format": "s16le"}
    with socket.create_connection(("127.0.0.1", port)) as s:
        s.sendall(
            json.dumps(header).encode() + b"\n" + b"\x10\x00" * int(rate * seconds)
        )
        s.shutdown(socket.SHUT_WR)
        while s.recv(4096):
            pass


def test_start_runs_the_robot_and_stop_takes_it_down(env):
    sink = MemorySink()
    config = NaoSimConfig(speech=SpeechSettings(engine="espeak"), viewer=HEADLESS)
    naosim = sim.NaoSim(config, sink=sink)
    assert not naosim.running

    asyncio.run(naosim.start())
    try:
        assert naosim.running and naosim.url == "tcp://127.0.0.1:9559"
        assert env.checked == ["2.1"]
        [up] = [c for c in compose_calls(env) if " up " in c]
        assert "--profile 2.1" in up and up.endswith("up -d --no-build tts naoqi21")
        assert env.read()["up_tts_engine"] == "espeak"
        assert env.read()["containers"] == {
            "nao-sim-naoqi21": "healthy",
            "nao-sim-tts": "running",
        }
        # The audio output is up: what the containers stream reaches the sink.
        play(sim.AUDIO_OUTPUT_PORT)
        assert sink.wait_for(lambda p: True).duration_s == pytest.approx(0.2)
        assert env.viewer.events == []  # headless, no render camera: no viewer
    finally:
        asyncio.run(naosim.stop())

    assert not naosim.running
    assert env.read()["containers"] == {}
    assert not listening(sim.AUDIO_OUTPUT_PORT)
    with pytest.raises(NotRunningError):
        naosim.url  # noqa: B018
    asyncio.run(naosim.stop())  # a no-op once stopped


def test_a_version_string_is_the_one_liner():
    assert sim.NaoSim("2.8").config == NaoSimConfig(naoqi=NaoqiSettings(version="2.8"))


def test_async_with_runs_the_version_and_stops_it(env):
    naosim = sim.NaoSim(
        NaoSimConfig(naoqi=NaoqiSettings(version="2.8"), viewer=HEADLESS),
        sink=MemorySink(),
    )

    async def run():
        async with naosim:
            assert naosim.running
        assert not naosim.running

    asyncio.run(run())
    assert any(c.endswith("up -d --no-build tts naoqi28") for c in compose_calls(env))


def test_the_window_runs_the_viewer_and_stop_closes_it(env):
    naosim = sim.NaoSim(NaoSimConfig(), sink=MemorySink())
    asyncio.run(naosim.start())
    asyncio.run(naosim.stop())

    settings, url = env.viewer.config
    assert settings == ViewerSettings() and url == "tcp://127.0.0.1:9559"
    assert env.viewer.events == ["launch viewer-config", "close"]


def test_the_render_camera_runs_after_the_viewer_and_stops_before_it(env):
    config = NaoSimConfig(
        video_input=VideoInputSettings(source="render"), viewer=HEADLESS
    )
    naosim = sim.NaoSim(config, sink=MemorySink())
    asyncio.run(naosim.start())
    deadline = time.monotonic() + 2
    while "frame 0 640x480" not in env.viewer.events:
        assert time.monotonic() < deadline, env.viewer.events
        time.sleep(0.01)
    asyncio.run(naosim.stop())

    assert env.viewer.events == [
        "launch viewer-config",  # headless, but the render camera needs the viewer
        "NaoSim/Camera/Source = render",
        "frame 0 640x480",
        "NaoSim/Camera/Source = none",
        "close",
    ]


def test_a_viewer_that_cannot_launch_never_starts_the_camera(env):
    env.viewer.launch_fails = True
    config = NaoSimConfig(
        video_input=VideoInputSettings(source="render"), viewer=HEADLESS
    )
    with pytest.raises(RuntimeError, match="no display"):
        asyncio.run(sim.NaoSim(config, sink=MemorySink()).start())
    assert env.viewer.events == ["launch viewer-config", "close"]


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (
            NaoSimConfig(
                audio_input=AudioInputSettings(source="wav", wav=Path("in.wav")),
                viewer=HEADLESS,
            ),
            "audio_input.source 'wav'",
        ),
        (
            NaoSimConfig(
                video_input=VideoInputSettings(source="webcam"), viewer=HEADLESS
            ),
            "video_input.source 'webcam'",
        ),
    ],
)
def test_an_unbuilt_device_fails_before_anything_starts(env, config, message):
    with pytest.raises(DeviceNotBuiltError, match=message):
        asyncio.run(sim.NaoSim(config, sink=MemorySink()).start())
    assert compose_calls(env) == []
    assert not listening(sim.AUDIO_OUTPUT_PORT)


def test_missing_images_fail_before_anything_starts(env, monkeypatch):
    def missing(version):
        raise ImagesMissingError("nao-sim/naoqi:2.1.4.13 is not built: run ...")

    monkeypatch.setattr(docker_images, "check_images", missing)
    with pytest.raises(ImagesMissingError):
        asyncio.run(sim.NaoSim(NaoSimConfig(viewer=HEADLESS)).start())
    assert compose_calls(env) == []


def test_a_missing_viewer_extra_fails_before_anything_starts(env, monkeypatch):
    def no_extra(settings, url):
        raise MissingExtraError("install it with `pip install nao-sim[viewer]`")

    monkeypatch.setattr(sim, "viewer_config", no_extra)
    with pytest.raises(MissingExtraError, match=r"nao-sim\[viewer\]"):
        asyncio.run(sim.NaoSim(NaoSimConfig(), sink=MemorySink()).start())
    assert compose_calls(env) == []


@pytest.mark.parametrize("which", ["NAOQI_PORT", "AUDIO_OUTPUT_PORT"])
def test_a_taken_port_fails_before_anything_starts(env, which):
    with socket.socket() as s:
        s.bind(("127.0.0.1", getattr(sim, which)))
        s.listen()
        with pytest.raises(PortInUseError, match=str(getattr(sim, which))):
            asyncio.run(sim.NaoSim(NaoSimConfig(viewer=HEADLESS)).start())
    assert compose_calls(env) == []


@pytest.mark.parametrize("boot", ["exited", "unhealthy"])
def test_a_failed_boot_stops_what_was_started(env, boot):
    env.set(boot=boot)
    naosim = sim.NaoSim(NaoSimConfig(viewer=HEADLESS), sink=MemorySink())

    with pytest.raises(BootError, match="did not boot"):
        asyncio.run(naosim.start())
    assert not naosim.running
    assert env.read()["containers"] == {}  # compose down ran
    assert not listening(sim.AUDIO_OUTPUT_PORT)


def test_a_boot_slower_than_the_timeout_fails(env):
    env.set(boot="starting")
    config = NaoSimConfig(naoqi=NaoqiSettings(ready_timeout_s=0.1), viewer=HEADLESS)
    with pytest.raises(BootError, match="not healthy after"):
        asyncio.run(sim.NaoSim(config, sink=MemorySink()).start())
    assert env.read()["containers"] == {}


def test_a_viewer_that_cannot_launch_stops_everything(env):
    env.viewer.launch_fails = True
    with pytest.raises(RuntimeError, match="no display"):
        asyncio.run(sim.NaoSim(NaoSimConfig(), sink=MemorySink()).start())
    assert env.viewer.events == ["launch viewer-config", "close"]
    assert env.read()["containers"] == {}
    assert not listening(sim.AUDIO_OUTPUT_PORT)


def test_a_cancelled_start_stops_what_was_started(env):
    env.set(boot="starting")  # never healthy: the start waits

    async def run():
        naosim = sim.NaoSim(NaoSimConfig(viewer=HEADLESS), sink=MemorySink())
        task = asyncio.create_task(naosim.start())
        while not listening(sim.AUDIO_OUTPUT_PORT) or not any(
            " up " in c for c in compose_calls(env)
        ):
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return naosim

    naosim = asyncio.run(run())
    assert not naosim.running
    assert env.read()["containers"] == {}
    assert not listening(sim.AUDIO_OUTPUT_PORT)


def test_start_twice_is_an_error(env):
    async def run():
        async with sim.NaoSim(
            NaoSimConfig(viewer=HEADLESS), sink=MemorySink()
        ) as naosim:
            with pytest.raises(NaoSimError, match="already running"):
                await naosim.start()

    asyncio.run(run())


def test_stop_carries_on_through_a_failure_and_raises_it(env, monkeypatch):
    naosim = sim.NaoSim(NaoSimConfig(viewer=HEADLESS), sink=MemorySink())
    asyncio.run(naosim.start())

    def down_fails(version):
        raise NaoSimError("docker compose down failed")

    monkeypatch.setattr(sim.stack, "down", down_fails)
    with pytest.raises(NaoSimError, match="down failed"):
        asyncio.run(naosim.stop())
    assert not naosim.running
    assert not listening(sim.AUDIO_OUTPUT_PORT)  # the audio output stopped anyway


def test_record_mode_writes_the_audio_to_a_wav_file(env, tmp_path):
    path = tmp_path / "played.wav"
    config = NaoSimConfig(
        audio_output=AudioOutputSettings(mode="record", record=path), viewer=HEADLESS
    )
    naosim = sim.NaoSim(config)
    asyncio.run(naosim.start())
    play(sim.AUDIO_OUTPUT_PORT, seconds=0.3)
    asyncio.run(naosim.stop())

    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnframes()) == (8000, 2400)


def test_constructing_does_nothing(env):
    sim.NaoSim(NaoSimConfig(viewer=HEADLESS))
    time.sleep(0.05)
    assert env.calls == []
    assert not listening(sim.AUDIO_OUTPUT_PORT)
