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
            samplerate=rate,
            channels=1,
            dtype="int16",
            latency="low",
            callback=self._captured,
        )

    def _captured(self, indata, frames, time_info, status) -> None:
        self.blocks.append((time.monotonic(), bytes(indata)))

    def __enter__(self):
        self._stream.start()
        return self

    def __exit__(self, *exc):
        self._stream.stop()
        self._stream.close()

    def first_loud(self, threshold: float) -> float | None:
        """When the first block louder than `threshold` was captured (time.monotonic())."""
        for t, block in self.blocks:
            if block and np.abs(np.frombuffer(block, "<i2")).max() > threshold:
                return t
        return None

    def loud_seconds(self, threshold: float) -> float:
        """How long the recording is louder than `threshold`, in 10 ms windows."""
        pcm = np.frombuffer(b"".join(b for _, b in self.blocks), "<i2").astype(float)
        window = self.rate // 100
        n = len(pcm) // window
        levels = np.abs(pcm[: n * window]).reshape(n, window).max(axis=1)
        return float(np.sum(levels > threshold)) / 100


class Room:
    """Plays int16 mono into the default output device in the background, with a raw stream
    as the `DevicePlayer` does."""

    def __init__(self, samples: np.ndarray, rate: int):
        import sounddevice as sd

        self._data = samples.astype("<i2").tobytes()
        self._stream = sd.RawOutputStream(
            samplerate=rate, channels=1, dtype="int16", latency="low"
        )
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._play, daemon=True)

    def _play(self) -> None:
        step = 2 * 1024
        for i in range(0, len(self._data), step):
            if self._stopped.is_set():
                return
            self._stream.write(self._data[i : i + step])

    def __enter__(self):
        self._stream.start()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stopped.set()
        self._thread.join(5)
        self._stream.abort()
        self._stream.close()


def _longest_quiet_run(
    times: np.ndarray, values: np.ndarray, after: float, before: float, floor: int = 50
) -> tuple[float, float]:
    """(start, end) of the longest run of samples quieter than `floor` between the times."""
    inside = (times > after) & (times < before)
    t, quiet = times[inside], np.abs(values[inside]) < floor
    best, run_start = (0.0, 0.0), None
    for i, q in enumerate(quiet):
        if q and run_start is None:
            run_start = i
        if run_start is not None and (not q or i == len(quiet) - 1):
            last = i if q else i - 1
            if t[last] - t[run_start] > best[1] - best[0]:
                best = (float(t[run_start]), float(t[last]))
            run_start = None
    return best


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


def test_the_device_player_plays_a_stream_whole_and_soon(device_output):
    with Recorder() as rec:
        time.sleep(0.3)
        sent = time.monotonic()
        _send(
            device_output,
            {"cmd": "play", "rate": RATE, "channels": 1, "format": "s16le"},
            tone(1000, 1.0, RATE).tobytes(),
        )
        time.sleep(0.5)
    assert rec.loud_seconds(2000) == pytest.approx(1.0, abs=0.15)
    # Heard soon after it is played: the microphone gate's tail must cover this.
    first = rec.first_loud(2000)
    assert first is not None
    assert first - sent < 0.3, f"heard {first - sent:.2f} s after it was sent"


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
    sim, session = mic_robot
    assert session.service("ALMemory").getData("NaoSim/Audio/Source") == "mic"
    listener = Listener(session).subscribe(16000, 3, 0)
    mic = sim._audio_input.source  # type: ignore[union-attr]
    try:
        with Room(tone(440, 8.0, 48000), 48000):  # the room: a steady tone
            with Recorder() as heard:  # what reaches the loopback, robot aside
                time.sleep(1.5)
            assert heard.loud_seconds(2000) > 0.5, (
                "the tone does not reach the loopback"
            )
            assert mic.captured > 50, f"the microphone captured {mic.captured} blocks"
            assert mic.peak > 2000, f"the microphone captured silence (peak {mic.peak})"
            said = time.monotonic()
            session.service("ALTextToSpeech").say("I hear the room, not my own voice.")
            done = time.monotonic()
            time.sleep(1.5)
        tail = sim.config.audio_input.gate_tail_s
        times, values = listener.timeline(16000, since=said - 1.2)
        before = (times > said - 1.0) & (times < said - 0.1)
        assert peak_hz(values[before], 16000) == pytest.approx(440, abs=10)
        assert np.abs(values[before]).max() > 1000
        # The gate starts when the robot's audio starts, after its synthesis (which varies), so
        # the gated stretch is read from the data: the longest unbroken run of zeros after
        # say() was called. Neither the room nor the robot's own voice, which the loopback
        # brings back, gets in until it ends.
        start, end = _longest_quiet_run(times, values, said - 0.05, done + tail + 1.0)
        assert end - start > 0.8, f"gated for {end - start:.2f} s only"
        assert end >= done - 0.1, "the gate let the end of the robot's speech through"
        after = (times > end + 0.05) & (times < end + 0.6)
        assert np.abs(values[after]).max() > 1000  # the room again
        assert peak_hz(values[after], 16000) == pytest.approx(
            440, abs=10
        )  # not the voice
    finally:
        listener.close()
