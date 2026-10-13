"""The `NaoqiSim` object's lifecycle, against the fake `docker` (tests/fake_docker.py): what it
checks before starting anything, the order it starts things in, and that a failed start, a
cancelled one and `stop()` leave nothing running. The audio output is real, on a free port; the
image check and naoqi-viewer are replaced, each by a recorder."""

import asyncio
import json
import socket
import time
import wave

import numpy as np
import pytest

from naoqi_sim import docker_images, sim, stack
from naoqi_sim.audio_input import FakeAudioSource
from naoqi_sim.audio_output import MemorySink
from naoqi_sim.config import (
    AudioInputSettings,
    AudioOutputSettings,
    NaoqiSettings,
    NaoqiSimConfig,
    SpeechSettings,
    VideoInputSettings,
    ViewerSettings,
)
from naoqi_sim.errors import (
    BootError,
    DeviceNotBuiltError,
    DeviceUnavailableError,
    ImagesMissingError,
    MissingExtraError,
    NaoqiSimError,
    NotRunningError,
    PortInUseError,
)
from naoqi_sim.host_link import encode, read_message

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
    """Stands in for naoqi-viewer: records the config it was given and its lifecycle."""

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
    monkeypatch.setattr(sim, "HOST_LINK_PORT", free_port())
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
    config = NaoqiSimConfig(speech=SpeechSettings(engine="espeak"), viewer=HEADLESS)
    naoqisim = sim.NaoqiSim(config, sink=sink)
    assert not naoqisim.running

    asyncio.run(naoqisim.start())
    try:
        assert naoqisim.running and naoqisim.url == "tcp://127.0.0.1:9559"
        assert env.checked == ["2.1"]
        [up] = [c for c in compose_calls(env) if " up " in c]
        assert "--profile 2.1" in up and up.endswith("up -d --no-build tts naoqi21")
        assert env.read()["up_tts_engine"] == "espeak"
        assert env.read()["containers"] == {
            "naoqi-sim-naoqi21": "healthy",
            "naoqi-sim-tts": "running",
        }
        # The audio output is up: what the containers stream reaches the sink.
        play(sim.AUDIO_OUTPUT_PORT)
        assert sink.wait_for(lambda p: True).duration_s == pytest.approx(0.2)
        assert env.viewer.events == []  # headless, no render camera: no viewer
    finally:
        asyncio.run(naoqisim.stop())

    assert not naoqisim.running
    assert env.read()["containers"] == {}
    assert not listening(sim.AUDIO_OUTPUT_PORT)
    with pytest.raises(NotRunningError):
        naoqisim.url  # noqa: B018
    asyncio.run(naoqisim.stop())  # a no-op once stopped


def test_a_version_string_is_the_one_liner():
    assert sim.NaoqiSim("2.8").config == NaoqiSimConfig(
        naoqi=NaoqiSettings(version="2.8")
    )


def test_async_with_runs_the_version_and_stops_it(env):
    naoqisim = sim.NaoqiSim(
        NaoqiSimConfig(naoqi=NaoqiSettings(version="2.8"), viewer=HEADLESS),
        sink=MemorySink(),
    )

    async def run():
        async with naoqisim:
            assert naoqisim.running
        assert not naoqisim.running

    asyncio.run(run())
    assert any(c.endswith("up -d --no-build tts naoqi28") for c in compose_calls(env))


def test_the_window_runs_the_viewer_and_stop_closes_it(env):
    naoqisim = sim.NaoqiSim(NaoqiSimConfig(), sink=MemorySink())
    asyncio.run(naoqisim.start())
    asyncio.run(naoqisim.stop())

    settings, url = env.viewer.config
    assert settings == ViewerSettings() and url == "tcp://127.0.0.1:9559"
    assert env.viewer.events == ["launch viewer-config", "close"]


def test_the_render_camera_runs_after_the_viewer_and_stops_before_it(env):
    config = NaoqiSimConfig(
        video_input=VideoInputSettings(source="render"), viewer=HEADLESS
    )
    naoqisim = sim.NaoqiSim(config, sink=MemorySink())
    asyncio.run(naoqisim.start())
    deadline = time.monotonic() + 2
    while "frame 0 640x480" not in env.viewer.events:
        assert time.monotonic() < deadline, env.viewer.events
        time.sleep(0.01)
    asyncio.run(naoqisim.stop())

    assert env.viewer.events == [
        "launch viewer-config",  # headless, but the render camera needs the viewer
        "NaoqiSim/Camera/Source = render",
        "frame 0 640x480",
        "NaoqiSim/Camera/Source = none",
        "close",
    ]


def test_a_viewer_that_cannot_launch_never_starts_the_camera(env):
    env.viewer.launch_fails = True
    config = NaoqiSimConfig(
        video_input=VideoInputSettings(source="render"), viewer=HEADLESS
    )
    with pytest.raises(RuntimeError, match="no display"):
        asyncio.run(sim.NaoqiSim(config, sink=MemorySink()).start())
    assert env.viewer.events == ["launch viewer-config", "close"]


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (
            NaoqiSimConfig(
                video_input=VideoInputSettings(source="webcam"), viewer=HEADLESS
            ),
            "video_input.source 'webcam'",
        ),
    ],
)
def test_an_unbuilt_device_fails_before_anything_starts(env, config, message):
    with pytest.raises(DeviceNotBuiltError, match=message):
        asyncio.run(sim.NaoqiSim(config, sink=MemorySink()).start())
    assert compose_calls(env) == []
    assert not listening(sim.AUDIO_OUTPUT_PORT)


def test_missing_images_fail_before_anything_starts(env, monkeypatch):
    def missing(version):
        raise ImagesMissingError("naoqi-sim/naoqi:2.1.4.13 is not built: run ...")

    monkeypatch.setattr(docker_images, "check_images", missing)
    with pytest.raises(ImagesMissingError):
        asyncio.run(sim.NaoqiSim(NaoqiSimConfig(viewer=HEADLESS)).start())
    assert compose_calls(env) == []


def test_a_missing_viewer_extra_fails_before_anything_starts(env, monkeypatch):
    def no_extra(settings, url):
        raise MissingExtraError("install it with `pip install naoqi-sim[viewer]`")

    monkeypatch.setattr(sim, "viewer_config", no_extra)
    with pytest.raises(MissingExtraError, match=r"naoqi-sim\[viewer\]"):
        asyncio.run(sim.NaoqiSim(NaoqiSimConfig(), sink=MemorySink()).start())
    assert compose_calls(env) == []


@pytest.mark.parametrize("which", ["NAOQI_PORT", "AUDIO_OUTPUT_PORT", "HOST_LINK_PORT"])
def test_a_taken_port_fails_before_anything_starts(env, which):
    config = NaoqiSimConfig(
        viewer=HEADLESS, audio_input=AudioInputSettings(source="fake")
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", getattr(sim, which)))
        s.listen()
        with pytest.raises(PortInUseError, match=str(getattr(sim, which))):
            asyncio.run(sim.NaoqiSim(config).start())
    assert compose_calls(env) == []


def test_the_host_link_port_is_free_to_use_without_an_audio_input(env):
    with socket.socket() as s:
        s.bind(("127.0.0.1", sim.HOST_LINK_PORT))
        s.listen()
        naoqisim = sim.NaoqiSim(NaoqiSimConfig(viewer=HEADLESS), sink=MemorySink())
        asyncio.run(naoqisim.start())
        asyncio.run(naoqisim.stop())


def test_the_fake_audio_input_serves_the_link_from_boot_to_stop(env, monkeypatch):
    up = stack.up
    link_open_at_up: list[bool] = []

    def recording_up(config):
        link_open_at_up.append(listening(sim.HOST_LINK_PORT))
        return up(config)

    monkeypatch.setattr(stack, "up", recording_up)
    config = NaoqiSimConfig(
        viewer=HEADLESS,
        video_input=VideoInputSettings(source="render"),
        audio_input=AudioInputSettings(source="fake", mono="silence"),
    )
    naoqisim = sim.NaoqiSim(config, sink=MemorySink())
    with pytest.raises(NotRunningError):
        naoqisim.fake_audio  # noqa: B018
    asyncio.run(naoqisim.start())
    try:
        assert link_open_at_up == [True]  # open before the containers boot
        assert isinstance(naoqisim.fake_audio, FakeAudioSource)
        # ALAudioDevice's side of the link gets audio once it says what it needs.
        with socket.create_connection(("127.0.0.1", sim.HOST_LINK_PORT)) as s:
            s.sendall(encode({"type": "hello", "service": "ALAudioDevice"}))
            fmt = {"rate": 16000, "channel": "front", "deinterleaved": False}
            s.sendall(encode({"type": "need", "formats": [fmt], "energy": False}))
            header, payload = read_message(s.makefile("rb")) or ({}, b"")
            assert header["format"] == fmt and len(payload) == 2 * 1365
    finally:
        asyncio.run(naoqisim.stop())
    events = env.viewer.events
    keys = [e for e in events if e.startswith("NaoqiSim/")]
    assert keys == [
        "NaoqiSim/Camera/Source = render",
        "NaoqiSim/Audio/Source = fake",
        "NaoqiSim/Audio/Channels = silence",
        "NaoqiSim/Audio/Source = none",  # the audio input stops first
        "NaoqiSim/Audio/Channels = none",
        "NaoqiSim/Camera/Source = none",
    ]
    assert events[-1] == "close"
    assert not listening(sim.HOST_LINK_PORT)


def test_fake_audio_needs_the_fake_source(env):
    naoqisim = sim.NaoqiSim(NaoqiSimConfig(viewer=HEADLESS), sink=MemorySink())
    asyncio.run(naoqisim.start())
    try:
        with pytest.raises(NaoqiSimError, match="not 'fake'"):
            naoqisim.fake_audio  # noqa: B018
    finally:
        asyncio.run(naoqisim.stop())


def test_a_microphone_that_cannot_open_fails_before_anything_starts(env, monkeypatch):
    def no_mic():
        raise DeviceUnavailableError(
            "audio_input.source 'mic': no default input device"
        )

    monkeypatch.setattr(sim, "check_mic", no_mic)
    config = NaoqiSimConfig(
        viewer=HEADLESS, audio_input=AudioInputSettings(source="mic")
    )
    with pytest.raises(DeviceUnavailableError, match="no default input device"):
        asyncio.run(sim.NaoqiSim(config).start())
    assert compose_calls(env) == []
    assert not listening(sim.AUDIO_OUTPUT_PORT)


@pytest.mark.parametrize("boot", ["exited", "unhealthy"])
def test_a_failed_boot_stops_what_was_started(env, boot):
    env.set(boot=boot)
    naoqisim = sim.NaoqiSim(NaoqiSimConfig(viewer=HEADLESS), sink=MemorySink())

    with pytest.raises(BootError, match="did not boot"):
        asyncio.run(naoqisim.start())
    assert not naoqisim.running
    assert env.read()["containers"] == {}  # compose down ran
    assert not listening(sim.AUDIO_OUTPUT_PORT)


def test_a_boot_slower_than_the_timeout_fails(env):
    env.set(boot="starting")
    config = NaoqiSimConfig(naoqi=NaoqiSettings(ready_timeout_s=0.1), viewer=HEADLESS)
    with pytest.raises(BootError, match="not healthy after"):
        asyncio.run(sim.NaoqiSim(config, sink=MemorySink()).start())
    assert env.read()["containers"] == {}


def test_a_viewer_that_cannot_launch_stops_everything(env):
    env.viewer.launch_fails = True
    with pytest.raises(RuntimeError, match="no display"):
        asyncio.run(sim.NaoqiSim(NaoqiSimConfig(), sink=MemorySink()).start())
    assert env.viewer.events == ["launch viewer-config", "close"]
    assert env.read()["containers"] == {}
    assert not listening(sim.AUDIO_OUTPUT_PORT)


def test_a_cancelled_start_stops_what_was_started(env):
    # Never healthy: the start waits. `up` takes its time, as a real one does: the cancel comes
    # while it is in flight, and the teardown must not race it.
    env.set(boot="starting", up_s=0.5)

    async def run():
        naoqisim = sim.NaoqiSim(NaoqiSimConfig(viewer=HEADLESS), sink=MemorySink())
        task = asyncio.create_task(naoqisim.start())
        while not listening(sim.AUDIO_OUTPUT_PORT) or not any(
            " up " in c for c in compose_calls(env)
        ):
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return naoqisim

    naoqisim = asyncio.run(run())
    assert not naoqisim.running
    assert env.read()["containers"] == {}
    assert not listening(sim.AUDIO_OUTPUT_PORT)


def test_start_twice_is_an_error(env):
    async def run():
        async with sim.NaoqiSim(
            NaoqiSimConfig(viewer=HEADLESS), sink=MemorySink()
        ) as naoqisim:
            with pytest.raises(NaoqiSimError, match="already running"):
                await naoqisim.start()

    asyncio.run(run())


def test_stop_carries_on_through_a_failure_and_raises_it(env, monkeypatch):
    naoqisim = sim.NaoqiSim(NaoqiSimConfig(viewer=HEADLESS), sink=MemorySink())
    asyncio.run(naoqisim.start())

    def down_fails(version):
        raise NaoqiSimError("docker compose down failed")

    monkeypatch.setattr(sim.stack, "down", down_fails)
    with pytest.raises(NaoqiSimError, match="down failed"):
        asyncio.run(naoqisim.stop())
    assert not naoqisim.running
    assert not listening(sim.AUDIO_OUTPUT_PORT)  # the audio output stopped anyway


def test_record_mode_writes_the_audio_to_a_wav_file(env, tmp_path):
    path = tmp_path / "played.wav"
    config = NaoqiSimConfig(
        audio_output=AudioOutputSettings(mode="record", record=path), viewer=HEADLESS
    )
    naoqisim = sim.NaoqiSim(config)
    asyncio.run(naoqisim.start())
    play(sim.AUDIO_OUTPUT_PORT, seconds=0.3)
    asyncio.run(naoqisim.stop())

    with wave.open(str(path)) as w:
        # The mix, as the robot's loudspeakers play it: 48 kHz stereo.
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (48000, 2, 14400)


def test_constructing_does_nothing(env):
    sim.NaoqiSim(NaoqiSimConfig(viewer=HEADLESS))
    time.sleep(0.05)
    assert env.calls == []
    assert not listening(sim.AUDIO_OUTPUT_PORT)
