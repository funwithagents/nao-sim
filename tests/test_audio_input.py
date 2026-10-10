"""The audio input: the fake source, the formats it produces, pacing, the gate, the microphone.

The device runs as on a running `NaoSim`, served a `need` by a fake host link connection that
records what it sends, with a fake qi session for its ALMemory keys and a fake audio output whose
`playing_until` a test sets."""

import sys
import threading
import time
import types
import wave

import numpy as np
import pytest

from nao_sim import audio_input
from nao_sim.audio_input import (
    BASE_RATE,
    CHUNK,
    AudioInput,
    Decimator,
    FakeAudioSource,
    MicSource,
    _Stream,
    check_mic,
    load_sound,
    upsample,
)
from nao_sim.errors import DeviceUnavailableError

FRONT = {"rate": 16000, "channel": "front", "deinterleaved": False}
ALL = {"rate": 48000, "channel": "all", "deinterleaved": False}
ALL_SPLIT = {"rate": 48000, "channel": "all", "deinterleaved": True}


def tone(freq: float, seconds: float, rate: int, amplitude: float = 8000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.int16)


def peak_hz(samples: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.fft.rfftfreq(len(samples), 1 / rate)[np.argmax(spectrum)])


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


# --- Resampling ------------------------------------------------------------------------------


def test_a_48k_tone_brought_to_16k_keeps_its_pitch_and_level_without_seams():
    x = tone(1000, 1.0, BASE_RATE).astype(np.float64)[:, None].repeat(4, axis=1)
    whole = Decimator()(x)
    blocks = Decimator()
    pieces = np.vstack([blocks(x[i : i + 480]) for i in range(0, len(x), 480)])
    assert np.allclose(whole, pieces)  # block by block is the same signal: no seams
    assert len(pieces) == 16000
    steady = pieces[200:-200, 0]
    assert peak_hz(steady, 16000) == pytest.approx(1000, abs=3)
    assert rms(steady) == pytest.approx(8000 / np.sqrt(2), rel=0.02)


def test_up_then_down_gives_back_a_16k_signal():
    x = tone(440, 0.5, 16000).astype(np.float64)[:, None]
    back = Decimator(1)(upsample(x))
    delay = (len(audio_input.LOWPASS) - 1) // 2 // 3  # the decimator's, at 16 kHz
    error = back[delay + 50 : -50, 0] - x[50 : -50 - delay, 0]
    assert np.max(np.abs(error)) < 0.02 * 8000


def test_a_tone_above_8k_does_not_fold_into_16k():
    x = tone(12000, 0.5, BASE_RATE).astype(np.float64)[:, None]
    assert rms(Decimator(1)(x)[100:]) < 0.01 * rms(x)


# --- The fake source -------------------------------------------------------------------------


def test_load_sound_reads_wav_files_and_arrays(tmp_path):
    path = tmp_path / "four.wav"
    data = np.arange(40, dtype=np.int16).reshape(10, 4)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(4)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(data.tobytes())
    samples, rate = load_sound(path)
    assert rate == 48000 and np.array_equal(samples, data)
    samples, rate = load_sound(np.zeros(5, dtype=np.int16), 16000)
    assert samples.shape == (5, 1) and rate == 16000


def write_wav(path, rate=16000, channels=1, width=2, frames=10):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\0" * frames * channels * width)
    return path


@pytest.mark.parametrize(
    ("make", "problem"),
    [
        (lambda p: write_wav(p / "a.wav", width=1), "8-bit"),
        (lambda p: write_wav(p / "a.wav", channels=2), "2 channels"),
        (lambda p: write_wav(p / "a.wav", rate=44100), "44100 Hz"),
        (lambda p: p / "missing.wav", "cannot read"),
        (lambda p: np.zeros(10, dtype=np.float32), "float32"),
        (lambda p: np.zeros((10, 2), dtype=np.int16), "2 channels"),
    ],
)
def test_the_fake_source_refuses_other_sounds(tmp_path, make, problem):
    with pytest.raises(ValueError, match=problem):
        FakeAudioSource().play(make(tmp_path), 16000)


def test_a_mono_sound_is_spread_by_the_mono_policy():
    sound = np.full(4800, 1000, dtype=np.int16)
    dup = FakeAudioSource("duplicate")
    dup.play(sound, 48000)
    assert np.all(dup.read(time.monotonic(), 480)[:, :] > 900)
    front_only = FakeAudioSource("silence")
    take = front_only.play(sound, 48000)
    block = front_only.read(take.started_at, 480)
    assert np.all(block[:, 2] == 1000) and not block[:, [0, 1, 3]].any()


def test_a_four_channel_sound_keeps_nao_order():
    sound = np.tile(np.array([[1, 2, 3, 4]], dtype=np.int16), (480, 1))
    source = FakeAudioSource("silence")  # the policy does not touch a 4-channel sound
    take = source.play(sound, 48000)
    assert np.array_equal(source.read(take.started_at, 480), sound)


def test_overlapping_sounds_mix_and_clip():
    source = FakeAudioSource()
    a = source.play(np.full(4800, 20000, dtype=np.int16), 48000)
    source.play(np.full(4800, 20000, dtype=np.int16), 48000)
    block = audio_input._clip16(source.read(a.started_at + 0.01, 480))
    assert np.all(block == 32767)


def test_a_sound_plays_on_the_wall_clock():
    source = FakeAudioSource()
    sound = np.arange(4800, dtype=np.int16)  # 0.1 s at 48 kHz
    take = source.play(sound, 48000)
    before = source.read(take.started_at - 480 / BASE_RATE, 960)  # straddles its start
    assert not before[:480].any() and np.array_equal(before[480:, 0], sound[:480])
    later = source.read(take.started_at + 0.05, 4800)  # the second half, then silence
    assert np.array_equal(later[:2400, 0], sound[2400:]) and not later[2400:].any()
    assert take.ended_at == pytest.approx(take.started_at + 0.1)


def test_wait_returns_when_a_take_ends_and_stop_cuts_every_take():
    source = FakeAudioSource()
    short = source.play(np.zeros(4800, dtype=np.int16), 48000)  # 0.1 s
    assert short.wait(2) and short.done
    assert time.monotonic() >= short.ended_at

    long = source.play(np.ones(48000 * 10, dtype=np.int16), 48000)
    assert not long.wait(0.05)
    threading.Timer(0.1, source.stop).start()
    assert long.wait(2)
    assert long.ended_at - long.started_at < 1
    assert not source.read(time.monotonic(), 480).any()


def test_deinterleaved_chunks_lay_each_channel_after_the_other():
    stream = _Stream((48000, "all", True))
    chunk = np.tile(np.array([[1, 2, 3, 4]]), (3, 1))
    header, data = stream.message(chunk)
    assert header["channels"] == 4 and header["samples"] == 3
    assert np.frombuffer(data, "<i2").tolist() == [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]


# --- The device ------------------------------------------------------------------------------


class Conn:
    """The host link connection: records every message sent, with its time."""

    def __init__(self):
        self.sent: list[tuple[float, dict, bytes]] = []
        self.lock = threading.Lock()

    def send(self, header, payload=b""):
        with self.lock:
            self.sent.append((time.monotonic(), header, payload))
        return True

    def pcm(self, fmt: dict) -> list[tuple[float, dict, np.ndarray]]:
        with self.lock:
            return [
                (t, h, np.frombuffer(p, "<i2").reshape(h["samples"], h["channels"]))
                for t, h, p in self.sent
                if h["type"] == "pcm" and h["format"] == fmt
            ]

    def energies(self) -> list[dict]:
        with self.lock:
            return [h for _, h, _ in self.sent if h["type"] == "energy"]


class Memory:
    def __init__(self):
        self.writes: list[tuple[str, str]] = []

    def insertData(self, key, value):
        self.writes.append((key, value))


class Session:
    def __init__(self):
        self.memory = Memory()
        self.closed = False

    def service(self, name):
        assert name == "ALMemory"
        return self.memory

    def close(self):
        self.closed = True


class Output:
    playing_until = 0.0


@pytest.fixture
def device():
    made = []

    def make(source=None, tail=0.3):
        session, conn, output = Session(), Conn(), Output()
        dev = AudioInput(
            source or FakeAudioSource(),
            output,
            tail,
            "duplicate",
            connect=lambda: session,
        )
        dev.connected(conn)
        made.append(dev)
        return dev, conn, output, session

    yield make
    for dev in made:
        dev.stop()


def need(*formats, energy=False):
    return {"type": "need", "formats": list(formats), "energy": energy}


def test_silence_comes_in_chunks_at_the_nao_cadence(device):
    dev, conn, _, session = device()
    dev.start()
    dev.message(conn, need(FRONT), b"")
    time.sleep(1.0)
    chunks = conn.pcm(FRONT)
    assert 10 <= len(chunks) <= 13  # 1365 samples at 16 kHz: one every 85 ms
    assert all(c.shape == (CHUNK[16000], 1) and not c.any() for _, _, c in chunks)
    gaps = np.diff([t for t, _, _ in chunks])
    assert np.all(gaps > 0.05)  # paced, never a burst
    assert session.memory.writes == [
        ("NaoSim/Audio/Source", "fake"),
        ("NaoSim/Audio/Channels", "duplicate"),
    ]


def test_a_played_tone_reaches_each_format_with_its_pitch(device):
    dev, conn, _, _ = device()
    dev.start()
    dev.message(conn, need(FRONT, ALL), b"")
    take = dev.source.play(tone(440, 0.6, 16000), 16000)  # type: ignore[attr-defined]
    take.wait(2)
    time.sleep(0.3)
    low = np.concatenate([c[:, 0] for _, _, c in conn.pcm(FRONT)])
    high = np.concatenate([c for _, _, c in conn.pcm(ALL)])
    loud = low[np.abs(low) > 1000]
    assert peak_hz(low[: len(low) // 1365 * 1365], 16000) == pytest.approx(440, abs=12)
    assert len(loud) > 0.4 * 16000
    assert np.max(np.abs(low)) == pytest.approx(8000, rel=0.05)
    assert high.shape[1] == 4 and np.array_equal(high[:, 0], high[:, 3])  # duplicated
    assert peak_hz(high[:, 0], 48000) == pytest.approx(440, abs=12)


def test_a_need_before_start_is_served_after_it_and_stop_resets_the_keys(device):
    dev, conn, _, session = device()
    dev.message(conn, need(FRONT), b"")
    time.sleep(0.2)
    assert conn.pcm(FRONT) == []  # NaoSim step 6 has not started the device yet
    dev.start()
    time.sleep(0.3)
    assert conn.pcm(FRONT)
    dev.stop()
    sent = len(conn.sent)
    time.sleep(0.2)
    assert len(conn.sent) == sent
    assert session.memory.writes[-2:] == [
        ("NaoSim/Audio/Source", "none"),
        ("NaoSim/Audio/Channels", "none"),
    ]
    assert session.closed


def test_an_empty_need_stops_production_and_a_new_one_resumes(device):
    dev, conn, _, _ = device()
    dev.start()
    dev.message(conn, need(ALL_SPLIT), b"")
    time.sleep(0.3)
    dev.message(conn, need(), b"")
    time.sleep(0.05)
    count = len(conn.sent)
    time.sleep(0.3)
    assert len(conn.sent) == count
    dev.message(conn, need(FRONT), b"")
    time.sleep(0.3)
    assert conn.pcm(FRONT)
    header = conn.pcm(ALL_SPLIT)[0][1]
    assert (header["channels"], header["samples"]) == (4, CHUNK[48000])


def test_energy_follows_the_sound(device):
    dev, conn, _, _ = device()
    dev.start()
    dev.message(conn, need(energy=True), b"")
    dev.source.play(tone(1000, 0.5, 48000, 10000), 48000)  # type: ignore[attr-defined]
    time.sleep(1.0)
    values = [e["front"] for e in conn.energies()]
    assert len(values) >= 9  # one per 4096 samples
    assert max(values) == pytest.approx(10000 / np.sqrt(2), rel=0.05)
    assert values[-1] < 1
    assert conn.pcm(FRONT) == []  # energy alone sends no audio


def test_the_gate_turns_what_plays_while_the_robot_speaks_into_zeros(device):
    dev, conn, output, _ = device(tail=0.2)
    dev.start()
    dev.message(conn, need(FRONT), b"")
    dev.source.play(np.full(16000 * 2, 5000, dtype=np.int16), 16000)  # type: ignore[attr-defined]
    time.sleep(0.4)
    speech_start = time.monotonic()
    output.playing_until = speech_start + 0.5  # the robot speaks for 0.5 s
    time.sleep(1.2)
    received = [(t, c[:, 0]) for t, _, c in conn.pcm(FRONT)]
    # Each chunk's samples are due at (arrival - its duration .. arrival); classify by sample time.
    loud_times, quiet_times = [], []
    for t, chunk in received:
        times = t - (len(chunk) - np.arange(len(chunk))) / 16000
        loud_times += list(times[np.abs(chunk) > 2500])
        quiet_times += list(times[np.abs(chunk) < 100])
    gated_end = speech_start + 0.5 + 0.2
    loud = np.array(loud_times)
    assert not np.any((loud > speech_start + 0.03) & (loud < gated_end - 0.03))
    assert np.any(loud < speech_start) and np.any(loud > gated_end)
    quiet = np.array(quiet_times)
    assert np.any((quiet > speech_start + 0.05) & (quiet < gated_end - 0.05))


# --- The microphone --------------------------------------------------------------------------


class FakeInputStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[str] = []

    def start(self):
        self.calls.append("start")
        block = np.full(self.kwargs["blocksize"], 3000, dtype="<i2").tobytes()

        def feed():
            while "stop" not in self.calls:
                self.kwargs["callback"](block, self.kwargs["blocksize"], None, None)
                time.sleep(0.01)

        threading.Thread(target=feed, daemon=True).start()

    def stop(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")


@pytest.fixture
def fake_sounddevice(monkeypatch):
    streams: list[FakeInputStream] = []
    module = types.ModuleType("sounddevice")

    def raw_input_stream(**kwargs):
        streams.append(FakeInputStream(**kwargs))
        return streams[-1]

    module.RawInputStream = raw_input_stream  # type: ignore[attr-defined]
    module.query_devices = lambda kind=None: {"name": "fake mic"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return streams, module


def test_the_microphone_opens_with_the_first_need_and_closes_with_the_last(
    device, fake_sounddevice
):
    streams, _ = fake_sounddevice
    dev, conn, output, session = device(source=MicSource(), tail=0.0)
    dev.start()
    assert streams == []  # nothing needed yet: the microphone stays off
    dev.message(conn, need(FRONT), b"")
    time.sleep(0.5)
    assert len(streams) == 1
    kwargs = streams[0].kwargs
    assert (kwargs["samplerate"], kwargs["channels"], kwargs["dtype"]) == (
        48000,
        1,
        "int16",
    )
    assert kwargs["latency"] == "low"  # the gate expects little capture delay
    chunks = [c for _, _, c in conn.pcm(FRONT)]
    assert chunks and np.abs(chunks[-1]).max() > 2500  # what it captured
    output.playing_until = time.monotonic() + 10  # the robot speaks: the mic is gated
    time.sleep(0.4)
    assert not conn.pcm(FRONT)[-1][2].any()
    dev.message(conn, need(), b"")
    assert streams[0].calls == ["start", "stop", "close"]
    assert ("NaoSim/Audio/Source", "mic") in session.memory.writes


def test_check_mic_needs_an_input_device(fake_sounddevice):
    _, module = fake_sounddevice
    check_mic()

    def none(kind=None):
        raise ValueError("No input device matching")

    module.query_devices = none
    with pytest.raises(DeviceUnavailableError, match="no default input device"):
        check_mic()
