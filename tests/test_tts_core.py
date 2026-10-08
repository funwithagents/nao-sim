import threading
import time

import nao_sim_tts_core as core
import pytest

END = [
    ("ALTextToSpeech/CurrentSentence", ""),
    ("ALTextToSpeech/TextDone", 1),
    ("ALTextToSpeech/CurrentBookMark", 0),
    ("ALTextToSpeech/TextStarted", 0),
]


class FakeEngine(core.Speaker):
    """A Speaker whose engine replies with chosen timings after `synth_s`, or fails."""

    def __init__(self, duration=0.2, marks=None, synth_s=0.0, fail=False):
        self.events: list[tuple[float, str, object]] = []
        self.signals: list[tuple] = []
        self.engine_calls: list[dict] = []
        self.engine_stops = 0
        super().__init__(self._record, signal=lambda *a: self.signals.append(a))
        self.reply = {"duration": duration, "marks": marks or {}, "engine": "fake"}
        self.synth_s = synth_s
        self.fail = fail

    def _record(self, key, value):
        self.events.append((time.monotonic(), key, value))

    def _engine_say(self, items, rate, pitch):
        self.engine_calls.append(
            {"items": items, "rate": rate, "pitch": pitch, "language": self.language}
        )
        time.sleep(self.synth_s)
        if self.fail:
            raise OSError("engine unreachable")
        return self.reply

    def _engine_stop(self):
        self.engine_stops += 1

    def sequence(self):
        return [(k, v) for _, k, v in self.events]

    def times(self, key):
        return [t for t, k, _ in self.events if k == key]


def say_in_thread(sp, text):
    done: list[float] = []
    t0 = time.monotonic()
    th = threading.Thread(
        target=lambda: (sp.say(text), done.append(time.monotonic() - t0))
    )
    th.start()
    return th, done


# -- parse -------------------------------------------------------------------


def test_parse_turns_tags_into_items():
    items, rate, pitch = core.parse(
        "\\pau=500\\ \\mrk=1\\  Hello there \\mrkpause=2\\ bye ", {}
    )

    assert items == [
        {"type": "pause", "ms": 500},
        {"type": "mark", "id": 1},
        {"type": "text", "text": "Hello there"},
        {"type": "mark", "id": 2},
        {"type": "text", "text": "bye"},
    ]
    assert (rate, pitch) == (100, 100)


def test_parse_drops_ignored_tags():
    items, _, _ = core.parse(
        "\\vol=50\\Loud \\emph=2\\word\\bound=W\\ \\readmode=char\\ \\tn=spell\\x", {}
    )

    assert items == [
        {"type": "text", "text": "Loud"},
        {"type": "text", "text": "word"},
        {"type": "text", "text": "x"},
    ]


def test_rate_and_pitch_apply_to_the_call_and_carry_over():
    state: dict = {}
    _, rate, pitch = core.parse("\\rspd=80\\slow \\vct=120\\high", state)
    assert (rate, pitch) == (80, 120)

    _, rate, pitch = core.parse("next call", state)
    assert (rate, pitch) == (80, 120)

    _, rate, pitch = core.parse("\\rspd=150\\ fast \\rst\\ back to normal", state)
    assert (rate, pitch) == (100, 100)


# -- say ---------------------------------------------------------------------


def test_say_raises_the_event_sequence_on_the_engine_clock():
    sp = FakeEngine(duration=0.3, marks={"2": 0.2, "1": 0.1})
    t0 = time.monotonic()
    sp.say("\\mrk=1\\ Hello \\mrk=2\\ world")
    took = time.monotonic() - t0

    assert sp.sequence() == [
        ("ALTextToSpeech/Status", [1, "enqueued"]),
        ("ALTextToSpeech/TextStarted", 1),
        ("ALTextToSpeech/TextDone", 0),
        ("ALTextToSpeech/Status", [1, "started"]),
        ("ALTextToSpeech/CurrentSentence", "\\mrk=1\\ Hello \\mrk=2\\ world"),
        ("ALTextToSpeech/CurrentBookMark", 1),
        ("ALTextToSpeech/CurrentBookMark", 2),
        ("ALTextToSpeech/Status", [1, "done"]),
        *END,
    ]
    assert sp.signals == [("_started", "\\mrk=1\\ Hello \\mrk=2\\ world")]
    started = sp.times("ALTextToSpeech/CurrentSentence")[0]
    b1, b2, _ = sp.times("ALTextToSpeech/CurrentBookMark")
    assert b1 - started == pytest.approx(0.1, abs=0.03)
    assert b2 - started == pytest.approx(0.2, abs=0.03)
    assert took == pytest.approx(0.3, abs=0.05)
    assert sp.engine_stops == 0


def test_say_sends_the_parsed_items_rate_and_language():
    sp = FakeEngine(duration=0.0)
    sp.set_language("French")
    sp.say("\\rspd=90\\Bonjour \\pau=200\\ toi")

    assert sp.engine_calls == [
        {
            "items": [
                {"type": "text", "text": "Bonjour"},
                {"type": "pause", "ms": 200},
                {"type": "text", "text": "toi"},
            ],
            "rate": 90,
            "pitch": 100,
            "language": "French",
        }
    ]
    assert ("languageTTS", "French") in sp.signals


def test_stop_all_mid_sentence():
    sp = FakeEngine(duration=1.0, marks={"1": 0.05, "2": 0.6})
    th, done = say_in_thread(sp, "\\mrk=1\\ one \\mrk=2\\ two")
    time.sleep(0.2)
    sp.stop_all()
    th.join(2)

    assert done[0] < 0.35
    marks = [v for _, k, v in sp.events if k == "ALTextToSpeech/CurrentBookMark"]
    assert marks == [1, 0]  # 2 was never reached; 0 is the end-of-sentence reset
    assert ("ALTextToSpeech/TextInterrupted", 1) in sp.sequence()
    assert sp.sequence()[-5:] == [("ALTextToSpeech/Status", [1, "done"]), *END]
    assert sp.engine_stops == 1


def test_stop_all_during_synthesis_is_not_lost():
    sp = FakeEngine(duration=1.0, marks={"1": 0.3}, synth_s=0.2)
    th, done = say_in_thread(sp, "\\mrk=1\\ a sentence still being synthesized")
    time.sleep(0.1)
    sp.stop_all()
    th.join(2)

    assert done[0] < 0.3  # right after the engine's reply, not after its 1 s of audio
    assert ("ALTextToSpeech/TextInterrupted", 1) in sp.sequence()
    assert ("ALTextToSpeech/CurrentBookMark", 1) not in sp.sequence()
    assert sp.engine_stops == 1


def test_a_stop_before_say_does_not_cut_the_next_sentence():
    sp = FakeEngine(duration=0.2)
    sp.stop_all()
    t0 = time.monotonic()
    sp.say("hello")

    assert time.monotonic() - t0 == pytest.approx(0.2, abs=0.05)
    assert ("ALTextToSpeech/TextInterrupted", 1) not in sp.sequence()


def test_fallback_clock_when_the_engine_is_unreachable(monkeypatch):
    monkeypatch.setattr(core, "FALLBACK_SECONDS_PER_TOKEN", 0.05)
    sp = FakeEngine(fail=True)
    t0 = time.monotonic()
    sp.say("one \\mrk=1\\ two three \\mrkpause=2\\")
    took = time.monotonic() - t0

    # 5 whitespace tokens, tags included.
    assert took == pytest.approx(5 * 0.05, abs=0.04)
    started = sp.times("ALTextToSpeech/CurrentSentence")[0]
    b1, b2, _ = sp.times("ALTextToSpeech/CurrentBookMark")
    assert b1 - started == pytest.approx(0.05, abs=0.03)  # token 1
    assert b2 - started == pytest.approx(0.20, abs=0.03)  # token 4
    assert sp.last["engine"] == "fallback-clock"
    assert sp.sequence()[-5:] == [("ALTextToSpeech/Status", [1, "done"]), *END]


def test_parameters_round_trip_and_reach_the_engine():
    sp = FakeEngine(duration=0.0)
    sp.set_parameter("speed", 70)
    sp.set_parameter("pitchShift", 1.2)

    assert sp.get_parameter("speed") == 70.0
    assert sp.get_parameter("pitchShift") == pytest.approx(1.2)
    sp.say("hi")
    assert (sp.engine_calls[0]["rate"], sp.engine_calls[0]["pitch"]) == (
        70.0,
        pytest.approx(120.0),
    )
