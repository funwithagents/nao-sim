"""Real sound devices, over a loopback: what comes out of the default output goes into the default
input. CI provides one (a PulseAudio null sink and its monitor) and sets NAO_SIM_E2E_AUDIO=loopback;
anywhere else these tests skip, since they would play into the loudspeakers and record the room.

They cover what the fake source and the memory sink cannot: the `DevicePlayer` sink on a device,
the `mic` source, and the microphone gate with the robot's own voice coming back into the
microphone."""

import json
import socket
import threading
import time

import numpy as np
import pytest
from conftest import live_config
from support import AUDIO, Listener, connect, peak_hz, require_loopback, tone

from nao_sim import NaoSim
from nao_sim.audio_output import AudioOutput, DevicePlayer, Server
from nao_sim.config import AudioInputSettings, AudioOutputSettings

RATE = 22050  # the speech engine's rate, which the audio output plays

# Decided before any fixture, so no NAOqi stack boots for tests that skip.
pytestmark = pytest.mark.skipif(
    AUDIO != "loopback",
    reason="uses the default sound devices: set NAO_SIM_E2E_AUDIO=loopback when they are wired "
    "to each other (a virtual loopback), never your loudspeakers and microphone",
)


@pytest.fixture(autouse=True)
def loopback():
    """With the loopback declared, the default devices must be there (or the test fails)."""
    require_loopback()


class Recorder:
    """Records the default input device (the loopback's monitor) as int16 mono."""

    def __init__(self, rate: int = RATE):
        import sounddevice as sd

        self.rate = rate
        self.blocks: list[tuple[float, bytes]] = []
        self._stream = sd.RawInputStream(
            samplerate=rate, channels=1, dtype="int16", callback=self._captured
        )

    def _captured(self, indata, frames, time_info, status) -> None:
        self.blocks.append((time.monotonic(), bytes(indata)))

    def __enter__(self):
        self._stream.start()
        return self

    def __exit__(self, *exc):
        self._stream.stop()
        self._stream.close()

    def loud_seconds(self, threshold: float) -> float:
        """How long the recording is louder than `threshold`, in 10 ms windows."""
        pcm = np.frombuffer(b"".join(b for _, b in self.blocks), "<i2").astype(float)
        window = self.rate // 100
        n = len(pcm) // window
        levels = np.abs(pcm[: n * window]).reshape(n, window).max(axis=1)
        return float(np.sum(levels > threshold)) / 100


def _send(port: int, header: dict, body: bytes = b"") -> None:
    with socket.create_connection(("127.0.0.1", port)) as s:
        s.sendall(json.dumps(header).encode() + b"\n" + body)
        s.shutdown(socket.SHUT_WR)
        while s.recv(4096):
            pass


@pytest.fixture
def device_output():
    """An audio output with a `DevicePlayer`, as `NaoSim` runs it by default, on a free port."""
    server = Server(("127.0.0.1", 0), AudioOutput(DevicePlayer()))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_the_device_player_plays_a_stream_whole(device_output):
    with Recorder() as rec:
        time.sleep(0.3)
        _send(
            device_output,
            {"cmd": "play", "rate": RATE, "channels": 1, "format": "s16le"},
            tone(1000, 1.0, RATE).tobytes(),
        )
        time.sleep(0.5)
    assert rec.loud_seconds(2000) == pytest.approx(1.0, abs=0.15)


def test_a_stop_cuts_the_device_player(device_output):
    header = {"cmd": "play", "rate": RATE, "channels": 1, "format": "s16le"}
    with Recorder() as rec:
        time.sleep(0.3)
        playing = threading.Thread(
            target=_send, args=(device_output, header, tone(1000, 3.0, RATE).tobytes())
        )
        playing.start()
        time.sleep(1.2)  # opening a device stream takes a few hundred ms on PulseAudio
        _send(device_output, {"cmd": "stop"})
        playing.join(5)
        time.sleep(0.5)
    # Cut: some of the tone was heard, far from its 3 s.
    assert 0.3 < rec.loud_seconds(2000) < 1.2 + 0.25


@pytest.fixture
def mic_robot(nao):
    """A NaoSim hearing through the microphone and speaking on the loudspeaker (its devices
    wired to each other by the loopback), in place of the session's."""
    config = live_config(
        nao.version.name,
        audio_input=AudioInputSettings(source="mic"),
        audio_output=AudioOutputSettings(mode="play"),
    )
    sim = NaoSim(config)  # no sink passed: a DevicePlayer
    nao.stop()
    session = None
    try:
        nao.runner.run(sim.start())
        session = connect(sim.url)
        yield sim, session
    finally:
        if session is not None:
            session.close()
        nao.runner.run(sim.stop())
        nao.start()


def test_the_microphone_hears_the_room_but_not_the_robot(mic_robot):
    import sounddevice as sd

    sim, session = mic_robot
    assert session.service("ALMemory").getData("NaoSim/Audio/Source") == "mic"
    listener = Listener(session).subscribe(16000, 3, 0)
    mic = sim._audio_input.source  # type: ignore[union-attr]
    try:
        with (
            Recorder() as room
        ):  # what reaches the loopback, independently of the robot
            sd.play(tone(440, 8.0, 48000), 48000)  # the room: a steady tone
            time.sleep(1.5)
        assert room.loud_seconds(2000) > 0.5, "the tone does not reach the loopback"
        assert mic.captured > 50, f"the microphone captured {mic.captured} blocks"
        assert mic.peak > 2000, f"the microphone captured silence (peak {mic.peak})"
        said = time.monotonic()
        session.service("ALTextToSpeech").say("I hear the room, not my own voice.")
        done = time.monotonic()
        time.sleep(1.5)
        sd.stop()
        tail = sim.config.audio_input.gate_tail_s
        times, values = listener.timeline(16000, since=said - 1.2)
        before = (times > said - 1.0) & (times < said - 0.1)
        assert peak_hz(values[before], 16000) == pytest.approx(440, abs=10)
        assert np.abs(values[before]).max() > 1000
        speaking = (times > said + 0.4) & (times < done - 0.2)
        assert done - said > 1.0 and np.any(speaking)
        # Gated: neither the room nor the robot's own voice, which the loopback brings back.
        assert np.abs(values[speaking]).max() < 50
        after = times > done + tail + 0.4
        assert np.abs(values[after]).max() > 1000
    finally:
        listener.close()
