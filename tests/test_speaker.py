import json
import socket
import threading
import time
import wave
from pathlib import Path

import pytest

from nao_sim.speaker import Server, Speaker

RATE = 8000  # small streams, same code path as 22050


class RunningSpeaker:
    """An in-process `nao-sim-speaker --silent --record FILE` on a free port."""

    def __init__(self, record: Path):
        self.record = record
        self.speaker = Speaker(record=str(record), silent=True)
        self.server = Server(("127.0.0.1", 0), self.speaker)
        host, port = self.server.server_address[:2]
        self.addr = (str(host), int(port))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def send(self, header: bytes | dict, pcm: bytes = b"") -> float:
        """One connection: header line, body, then wait for the speaker to close it. Returns its duration."""
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
            # The speaker may stop reading with data still buffered, which resets the connection.
            except ConnectionResetError:
                pass
        return time.monotonic() - t0

    def play(self, seconds: float) -> float:
        return self.send(
            {"cmd": "play", "rate": RATE, "channels": 1, "format": "s16le"},
            tone(seconds),
        )

    def play_async(self, seconds: float) -> list[float]:
        out: list[float] = []
        threading.Thread(
            target=lambda: out.append(self.play(seconds)), daemon=True
        ).start()
        return out

    def recorded(self) -> tuple[int, int]:
        """(frames, rate) of the recording so far."""
        self.speaker.close()
        with wave.open(str(self.record)) as w:
            return w.getnframes(), w.getframerate()

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.speaker.close()


def tone(seconds: float) -> bytes:
    return b"\x10\x00" * int(seconds * RATE)


def events(out: str) -> list[dict]:
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)


@pytest.fixture
def speaker(tmp_path):
    c = RunningSpeaker(tmp_path / "played.wav")
    yield c
    c.shutdown()


def test_play_records_every_sample_paced_in_real_time(speaker):
    took = speaker.play(0.5)

    assert speaker.recorded() == (int(0.5 * RATE), RATE)
    assert 0.45 <= took <= 0.8


def test_stop_ends_playback_within_one_chunk(speaker):
    done = speaker.play_async(2.0)
    time.sleep(0.5)
    t_stop = time.monotonic()
    speaker.send({"cmd": "stop"})
    wait_for(lambda: done)

    # At most one 100 ms chunk, plus slack for the scheduler.
    assert time.monotonic() - t_stop < 0.25
    frames, _ = speaker.recorded()
    assert 0.3 * RATE < frames < 0.8 * RATE


def test_newest_stream_wins(speaker, capsys):
    first = speaker.play_async(2.0)
    time.sleep(0.3)
    second_took = speaker.play(0.5)
    wait_for(lambda: first)

    evs = events(capsys.readouterr().out)
    assert [e["event"] for e in evs].count("interrupted") == 1
    ends = sorted(e["played_s"] for e in evs if e["event"] == "end")
    assert ends[0] < 0.6  # the first stream was cut shortly after the second started
    assert ends[1] == pytest.approx(0.5, abs=0.01)  # the second played in full
    assert first[0] < 1.5 and second_took >= 0.45


def test_bad_header_is_ignored(speaker, capsys):
    speaker.send(b"not json\n", tone(0.2))
    speaker.play(0.2)

    assert [e["event"] for e in events(capsys.readouterr().out)] == ["start", "end"]
    assert speaker.recorded() == (int(0.2 * RATE), RATE)
