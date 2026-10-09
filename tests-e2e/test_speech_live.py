"""Speech through a running nao-sim stack, on each NAOqi version: the ALTextToSpeech
replacement, the tts container and the host audio output together, driven over qi like any client."""

import re
import time

import pytest

SENTENCE = "Hello, I am a simulated NAO speaking through the engine container."
LONG = (
    "This is a long sentence that will be interrupted by stop all before it finishes, "
    "and it goes on and on so that there is plenty of audio left to cut."
)
MARK = re.compile(r"\\mrk(?:pause)?=(\d+)\\")


def last(entries, method):
    return [e for e in entries if e.get("method") == method][-1]


def test_the_replacement_serves_alt_text_to_speech(nao):
    assert nao.version.implementation in nao.service("ALTextToSpeech").whoami()


def test_say_blocks_for_the_audio(nao):
    tts = nao.service("ALTextToSpeech")
    tts.setLanguage("English")
    mark = time.monotonic()
    tts.say(SENTENCE)
    returned = time.monotonic()
    playback = nao.sink.wait_for(lambda p: p.started_at >= mark)
    audio = playback.duration_s

    assert audio > 2.0  # real speech was played, not the fallback clock
    assert not playback.interrupted
    assert 0.8 * audio <= returned - mark <= audio + 1.5
    # Played in real time, and say() returns as the voice ends.
    assert playback.ended_at is not None
    assert playback.ended_at - playback.started_at == pytest.approx(audio, abs=0.3)
    assert abs(returned - playback.ended_at) < 1.0


def test_animated_speech_gets_every_bookmark(nao):
    memory = nao.service("ALMemory")
    raised: list[int] = []
    subscriber = memory.subscriber("ALTextToSpeech/CurrentBookMark")
    link = subscriber.signal.connect(raised.append)
    try:
        # The gesture comes from the robot's `animations` package, installed in the image.
        nao.service("ALAnimatedSpeech").say(
            "^start(animations/Stand/Gestures/Hey_1) Hello with gestures "
            "^wait(animations/Stand/Gestures/Hey_1) and a second part after the gesture."
        )
        time.sleep(0.5)  # events reach the host asynchronously
    finally:
        subscriber.signal.disconnect(link)

    received = last(nao.container.tts_log(), "say")["text"]
    expected = {int(m) for m in MARK.findall(received)}
    assert len(expected) >= 2, received
    assert expected <= set(raised)
    assert raised[-1] == 0


def test_stop_all_cuts_the_sentence(nao):
    tts = nao.service("ALTextToSpeech")
    mark = time.monotonic()
    future = tts.say(LONG, _async=True)
    time.sleep(1.5)  # well into the audio
    t_stop = time.time()
    tts.stopAll()
    future.wait(10000)
    returned = time.time() - t_stop
    played = nao.played(mark)

    done = last(nao.container.tts_log(), "say-done")
    assert done["interrupted"] is True
    assert returned < 0.5
    assert played < done["duration"] - 2.0


def test_stop_all_during_synthesis(nao):
    tts = nao.service("ALTextToSpeech")
    mark = time.monotonic()
    t0 = time.time()
    future = tts.say(LONG + " " + LONG, _async=True)
    time.sleep(0.15)  # the engine is still synthesizing the long text
    tts.stopAll()
    future.wait(10000)
    returned = time.time() - t0

    done = last(nao.container.tts_log(), "say-done")
    assert done["interrupted"] is True
    assert returned < 1.5  # synthesis plus the stop, not the ~15 s of audio
    assert nao.played(mark) < 0.3
