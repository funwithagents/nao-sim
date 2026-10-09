"""Speech through a running nao-sim stack, on each NAOqi version: the ALTextToSpeech
replacement, the tts container and the host speaker together, driven over qi like any client."""

import re
import time

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


def test_say_blocks_for_the_audio(nao, speaker):
    tts = nao.service("ALTextToSpeech")
    tts.setLanguage("English")
    mark = speaker.mark()
    t0 = time.time()
    tts.say(SENTENCE)
    blocked = time.time() - t0
    audio = speaker.played(mark)

    assert audio > 2.0  # real speech was played, not the fallback clock
    assert 0.8 * audio <= blocked <= audio + 1.5


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

    received = last(nao.stack.tts_log(), "say")["text"]
    expected = {int(m) for m in MARK.findall(received)}
    assert len(expected) >= 2, received
    assert expected <= set(raised)
    assert raised[-1] == 0


def test_stop_all_cuts_the_sentence(nao, speaker):
    tts = nao.service("ALTextToSpeech")
    mark = speaker.mark()
    future = tts.say(LONG, _async=True)
    time.sleep(1.5)  # well into the audio
    t_stop = time.time()
    tts.stopAll()
    future.wait(10000)
    returned = time.time() - t_stop
    played = speaker.played(mark)

    done = last(nao.stack.tts_log(), "say-done")
    assert done["interrupted"] is True
    assert returned < 0.5
    assert played < done["duration"] - 2.0


def test_stop_all_during_synthesis(nao, speaker):
    tts = nao.service("ALTextToSpeech")
    mark = speaker.mark()
    t0 = time.time()
    future = tts.say(LONG + " " + LONG, _async=True)
    time.sleep(0.15)  # the engine is still synthesizing the long text
    tts.stopAll()
    future.wait(10000)
    returned = time.time() - t0

    done = last(nao.stack.tts_log(), "say-done")
    assert done["interrupted"] is True
    assert returned < 1.5  # synthesis plus the stop, not the ~15 s of audio
    assert speaker.played(mark) < 0.3
