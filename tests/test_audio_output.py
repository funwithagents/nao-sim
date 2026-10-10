import json
import socket
import sys
import threading
import time
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from nao_sim.audio_output import (
    AudioOutput,
    AudioSink,
    DevicePlayer,
    MemorySink,
    NullSink,
    Server,
    WavSink,
)

RATE = 8000  # small streams, same code path as 22050


class RunningOutput:
    """An in-process audio output on a free port, feeding `sink`."""

    def __init__(self, sink: AudioSink):
        self.sink = sink
        self.output = AudioOutput(sink)
        self.server = Server(("127.0.0.1", 0), self.output)
        host, port = self.server.server_address[:2]
        self.addr = (str(host), int(port))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def send(self, header: bytes | dict, pcm: bytes = b"") -> float:
        """One connection: header line, body, then wait for the output to close it. Returns its duration."""
        line = (
            header if isinstance(header, bytes) else json.dumps(header).encode() + b"\n"
        )
        t0 = time.monotonic()
        with socket.create_connection(self.addr) as s:
            s.sendall(line + pcm)
            s.shutdown(socket.SHUT_WR)
            try:
                while s.recv(4096):
                    pass
            # The output may stop reading with data still buffered, which resets the connection.
            except ConnectionResetError:
                pass
        return time.monotonic() - t0

    def play(self, seconds: float, rate: int = RATE, channels: int = 1) -> float:
        return self.send(
            {"cmd": "play", "rate": rate, "channels": channels, "format": "s16le"},
            tone(seconds, rate, channels),
        )

    def play_async(self, seconds: float) -> list[float]:
        out: list[float] = []
        threading.Thread(
            target=lambda: out.append(self.play(seconds)), daemon=True
        ).start()
        return out

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()


def tone(seconds: float, rate: int = RATE, channels: int = 1) -> bytes:
    return b"\x10\x00" * int(seconds * rate) * channels


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)


@pytest.fixture
def memory():
    c = RunningOutput(MemorySink())
    yield c
    c.shutdown()


def playbacks(c: RunningOutput):
    assert isinstance(c.sink, MemorySink)
    return c.sink.playbacks


# --- The protocol and its semantics -------------------------------------------------


def test_play_feeds_every_sample_paced_in_real_time(memory):
    took = memory.play(0.5)

    [p] = playbacks(memory)
    assert (p.rate, p.channels, p.interrupted) == (RATE, 1, False)
    assert p.pcm == tone(0.5)
    assert 0.45 <= took <= 0.8
    assert p.ended_at is not None and p.ended_at - p.started_at >= 0.45


def test_null_sink_is_paced_too():
    c = RunningOutput(NullSink())
    try:
        assert 0.45 <= c.play(0.5) <= 0.8
    finally:
        c.shutdown()


def test_stop_ends_playback_within_one_chunk(memory):
    done = memory.play_async(2.0)
    time.sleep(0.5)
    t_stop = time.monotonic()
    memory.send({"cmd": "stop"})
    wait_for(lambda: done)

    # At most one 100 ms chunk, plus slack for the scheduler.
    assert time.monotonic() - t_stop < 0.25
    [p] = playbacks(memory)
    assert p.interrupted
    assert 0.3 < p.duration_s < 0.8


def test_newest_stream_wins(memory):
    first = memory.play_async(2.0)
    time.sleep(0.3)
    second_took = memory.play(0.5)
    wait_for(lambda: first)

    cut, full = playbacks(memory)
    assert cut.interrupted and cut.duration_s < 0.6
    assert not full.interrupted and full.duration_s == pytest.approx(0.5)
    assert first[0] < 1.5 and second_took >= 0.45


def test_bad_header_is_ignored(memory):
    memory.send(b"not json\n", tone(0.2))
    memory.play(0.2)

    [p] = playbacks(memory)
    assert p.pcm == tone(0.2)


def test_a_stop_does_not_cut_the_next_stream(memory):
    memory.send({"cmd": "stop"})
    memory.play(0.2)

    [p] = playbacks(memory)
    assert not p.interrupted and p.pcm == tone(0.2)


class CallLog:
    """A sink that records its calls, and fails if two streams overlap."""

    def __init__(self):
        self.calls: list[str] = []
        self._open = False

    def begin(self, rate, channels):
        assert not self._open, "begin while a stream is open"
        self._open = True
        self.calls.append("begin")

    def feed(self, chunk):
        assert self._open
        if self.calls[-1] != "feed":
            self.calls.append("feed")

    def end(self, interrupted):
        assert self._open
        self._open = False
        self.calls.append(f"end({interrupted})")


def test_sink_calls_never_overlap_when_a_newer_stream_cuts_in():
    sink = CallLog()
    c = RunningOutput(sink)
    try:
        first = c.play_async(2.0)
        time.sleep(0.3)
        c.play(0.3)
        wait_for(lambda: first)
    finally:
        c.shutdown()

    assert sink.calls == ["begin", "feed", "end(True)", "begin", "feed", "end(False)"]


def test_a_failing_sink_still_gets_its_end():
    class Failing(CallLog):
        def feed(self, chunk):
            raise OSError("device gone")

    sink = Failing()
    c = RunningOutput(sink)
    try:
        c.play(0.3)
        c.play(0.3)
    finally:
        c.shutdown()

    assert sink.calls == ["begin", "end(True)", "begin", "end(True)"]


# --- Playing state ------------------------------------------------------------------


def test_playing_until_follows_the_audio(memory):
    output = memory.output
    assert output.playing_until < time.monotonic()  # idle

    t0 = time.monotonic()
    done = memory.play_async(1.0)
    time.sleep(0.4)
    assert output.playing_until > time.monotonic()
    assert output.playing_until == pytest.approx(t0 + 0.5, abs=0.15)  # one chunk ahead
    wait_for(lambda: done)
    assert output.playing_until == pytest.approx(t0 + 1.0, abs=0.15)
    assert output.playing_until <= time.monotonic()


def test_a_stop_ends_the_playing_period_at_once(memory):
    memory.play_async(2.0)
    time.sleep(0.4)
    t_stop = time.monotonic()
    memory.send({"cmd": "stop"})

    assert memory.output.playing_until <= time.monotonic()
    assert memory.output.playing_until == pytest.approx(t_stop, abs=0.1)


# --- Sinks --------------------------------------------------------------------------


def wav_contents(path: Path) -> tuple[int, int, int, bytes]:
    with wave.open(str(path)) as w:
        return w.getnchannels(), w.getframerate(), w.getnframes(), w.readframes(-1)


def test_wav_sink_appends_streams_and_restarts_on_a_new_rate(tmp_path):
    path = tmp_path / "played.wav"
    sink = WavSink(path)
    for chunk in (tone(0.1), tone(0.2)):
        sink.begin(RATE, 1)
        sink.feed(chunk)
        sink.end(False)
    assert wav_contents(path)[:3] == (
        1,
        RATE,
        int(0.3 * RATE),
    )  # readable between streams

    sink.begin(16000, 1)
    sink.feed(tone(0.1, 16000))
    sink.end(False)
    sink.close()
    assert wav_contents(path)[:3] == (1, 16000, 1600)


def test_wav_sink_downmixes_to_mono(tmp_path):
    path = tmp_path / "played.wav"
    sink = WavSink(path)
    stereo = np.array([[100, 300], [-50, -150]] * 400, dtype="<i2")
    sink.begin(RATE, 2)
    sink.feed(stereo.tobytes())
    sink.end(False)
    sink.close()

    channels, _, frames, pcm = wav_contents(path)
    assert (channels, frames) == (1, 800)
    assert np.frombuffer(pcm, dtype="<i2")[:2].tolist() == [200, -100]


def test_memory_sink_wait_for_returns_an_ended_playback():
    sink = MemorySink()
    sink.begin(RATE, 1)
    sink.feed(tone(0.1))

    def finish():
        time.sleep(0.1)
        sink.end(False)

    threading.Thread(target=finish).start()
    p = sink.wait_for(lambda p: p.rate == RATE, timeout=2)
    assert p.ended_at is not None and p.pcm == tone(0.1)
    with pytest.raises(TimeoutError):
        sink.wait_for(lambda p: p.rate == 16000, timeout=0.1)


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[str] = []
        self.written = b""

    def start(self):
        self.calls.append("start")

    def write(self, data):
        self.written += data

    def stop(self):
        self.calls.append("stop")

    def abort(self):
        self.calls.append("abort")

    def close(self):
        self.calls.append("close")


@pytest.fixture
def fake_sounddevice(monkeypatch):
    streams: list[FakeStream] = []

    def raw_output_stream(**kwargs):
        streams.append(FakeStream(**kwargs))
        return streams[-1]

    module = types.ModuleType("sounddevice")
    module.RawOutputStream = raw_output_stream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return streams


def test_device_player_plays_each_stream_and_cuts_on_interruption(fake_sounddevice):
    player = DevicePlayer(device=3)
    assert fake_sounddevice == []  # nothing opened before a stream

    player.begin(RATE, 2)
    player.feed(b"ab")
    player.feed(b"cd")
    player.end(False)
    player.begin(RATE, 1)
    player.end(True)

    finished, cut = fake_sounddevice
    assert finished.kwargs["samplerate"] == RATE and finished.kwargs["channels"] == 2
    assert finished.kwargs["device"] == 3 and finished.kwargs["dtype"] == "int16"
    assert (
        finished.kwargs["latency"] == "low"
    )  # the robot's voice is heard right away (gate)
    assert finished.written == b"abcd"
    assert finished.calls == ["start", "stop", "close"]  # drained
    assert cut.calls == ["start", "abort", "close"]  # cut at once
