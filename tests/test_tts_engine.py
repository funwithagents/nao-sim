import json
import socket
import threading
import time

import numpy as np
import pytest
import server


@pytest.fixture
def synth(monkeypatch):
    """Fake engines: a text item "<seconds>@<rate>" synthesizes that many seconds at that rate."""
    calls: list[tuple[str, str]] = []

    def fake(engine):
        def synthesize(text, lang, rate, pitch=100):
            calls.append((engine, text))
            seconds, sr = text.split("@")
            return (
                np.full(round(float(seconds) * int(sr)), 1000, dtype=np.int16),
                int(sr),
                engine,
            )

        return synthesize

    monkeypatch.setattr(server, "synth_piper", fake("piper"))
    monkeypatch.setattr(server, "synth_espeak", fake("espeak"))
    return calls


def text(t):
    return {"type": "text", "text": t}


def mark(i):
    return {"type": "mark", "id": i}


def pause(ms):
    return {"type": "pause", "ms": ms}


def test_marks_sit_at_the_audio_before_them(synth):
    pcm, sr, marks, used = server.render(
        {"items": [mark(1), text("1.0@22050"), mark(2), text("0.5@22050"), mark(3)]}
    )

    assert marks == {"1": 0.0, "2": 1.0, "3": 1.5}
    assert (len(pcm), sr, used) == (int(1.5 * 22050), 22050, "piper")


def test_pauses_add_exact_silence(synth):
    pcm, _, marks, _ = server.render(
        {"items": [text("0.2@22050"), pause(300), mark(1), text("0.1@22050")]}
    )

    assert marks == {"1": 0.5}
    assert len(pcm) == int(0.6 * 22050)
    silence = pcm[int(0.2 * 22050) : int(0.5 * 22050)]
    assert not silence.any()


def test_parts_are_resampled_to_the_first_rate(synth):
    pcm, sr, marks, _ = server.render(
        {"items": [text("1.0@22050"), mark(1), text("0.5@16000"), mark(2)]}
    )

    assert sr == 22050
    assert marks == {"1": 1.0, "2": pytest.approx(1.5, abs=1e-3)}
    assert len(pcm) / sr == pytest.approx(1.5, abs=1e-3)


def test_empty_text_items_are_skipped(synth):
    pcm, _, marks, _ = server.render(
        {"items": [text("   "), mark(1), text(""), text("0.3@16000")]}
    )

    assert synth == [("piper", "0.3@16000")]
    assert marks == {"1": 0.0}
    assert len(pcm) == int(0.3 * 16000)


def test_without_text_the_rate_is_22050(synth):
    pcm, sr, marks, _ = server.render({"items": [pause(100), mark(1)]})
    assert (sr, len(pcm), marks) == (22050, 2205, {"1": 0.1})

    pcm, sr, marks, _ = server.render({"items": []})
    assert (sr, len(pcm), marks) == (22050, 0, {})


def test_the_request_selects_the_engine(synth):
    _, _, _, used = server.render({"engine": "espeak", "items": [text("0.1@22050")]})

    assert used == "espeak"
    assert synth == [("espeak", "0.1@22050")]


@pytest.fixture
def audio_output(monkeypatch):
    """A stand-in audio output on a free port: the header line of every connection it gets."""
    listener = socket.create_server(("127.0.0.1", 0))
    monkeypatch.setattr(server, "SOUNDCARD", f"127.0.0.1:{listener.getsockname()[1]}")
    headers: list[dict] = []

    def serve():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with conn, conn.makefile("rb") as f:
                headers.append(json.loads(f.readline()))
                f.read()

    threading.Thread(target=serve, daemon=True).start()
    yield headers
    listener.close()


def wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "condition not met in time"
        time.sleep(0.01)


def test_speech_plays_as_the_speech_stream(audio_output):
    server.stream_to_soundcard(np.zeros(2205, dtype=np.int16), 22050)
    wait_for(lambda: audio_output)

    assert audio_output == [
        {
            "cmd": "play",
            "stream": "speech",
            "rate": 22050,
            "channels": 1,
            "format": "s16le",
        }
    ]


def test_stop_stops_the_speech_stream_only(audio_output):
    server.soundcard_stop()
    wait_for(lambda: audio_output)

    assert audio_output == [{"cmd": "stop", "stream": "speech"}]
