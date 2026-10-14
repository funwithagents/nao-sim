"""Sound features the Speech and Sound boxes use beyond saying and playing (Set Speaker Vol.,
Record Sound, Dialog), from a host client: the volume is heard in what the loudspeakers played,
the recording holds what the microphones heard, the dialog answers aloud
(plans/202610132100_api-coverage-from-boxes.md)."""

import io
import time
import wave

import numpy as np
import pytest
from support import known_issue, peak_hz, tone

TOPIC = """topic: ~naoqi_sim_e2e()
language: enu

u:(hello robot) hello human
"""


def loudness(nao, after: float, timeout: float = 15.0) -> float:
    """RMS of the loudspeakers' mix over the runs that began after `after` and have ended."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        runs = [m for m in nao.sink.mixes if m.started_at >= after]
        if runs and all(m.ended_at is not None for m in runs):
            pcm = np.frombuffer(b"".join(m.pcm for m in runs), np.int16)
            if pcm.size:
                return float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
        time.sleep(0.1)
    pytest.fail("the loudspeakers played nothing")


def test_speaker_volume_is_heard(request, nao):
    """Set Speaker Vol.: ALAudioDevice.setOutputVolume makes the robot quieter."""
    known_issue(
        request,
        nao,
        "setOutputVolume keeps the value only (specs/services/audio-device.md, open question 2)",
    )
    device = nao.service("ALAudioDevice")
    tts = nao.service("ALTextToSpeech")
    tts.setLanguage("English")
    was = device.getOutputVolume()
    try:
        device.setOutputVolume(90)
        mark = time.monotonic()
        tts.say("Volume check.")
        loud = loudness(nao, mark)
        device.setOutputVolume(20)
        mark = time.monotonic()
        tts.say("Volume check.")
        quiet = loudness(nao, mark)
    finally:
        device.setOutputVolume(was)
    assert quiet < 0.5 * loud


def test_record_sound_keeps_what_the_microphones_heard(request, nao, tmp_path):
    """Record Sound: ALAudioDevice records the microphones to a WAV file on the robot."""
    known_issue(
        request,
        nao,
        "no recording yet (specs/services/audio-device.md, open question 3)",
    )
    device = nao.service("ALAudioDevice")
    path = "/tmp/naoqi_sim_e2e_record.wav"
    device.startMicrophonesRecording(path)
    try:
        time.sleep(0.3)
        nao.audio.play(tone(440, 1.0, 48000), 48000).wait(3)
        time.sleep(0.3)
    finally:
        device.stopMicrophonesRecording()
    nao.container.copy_out(path, tmp_path / "record.wav")
    with wave.open(io.BytesIO((tmp_path / "record.wav").read_bytes())) as w:
        rate, channels = w.getframerate(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    first = pcm.reshape(-1, channels)[:, 0]
    assert first.size / rate > 1.0
    assert peak_hz(first, rate) == pytest.approx(440, abs=10)


def test_a_dialog_topic_answers_aloud(nao, tmp_path):
    """Dialog: a topic loaded in ALDialog answers an input through the robot's voice."""
    nao.service("ALTextToSpeech").setLanguage("English")
    topic_file = tmp_path / "naoqi_sim_e2e.top"
    topic_file.write_text(TOPIC)
    nao.container.copy_in(topic_file, "/tmp/naoqi_sim_e2e.top")
    dialog = nao.service("ALDialog")
    dialog.setLanguage("English")
    name = dialog.loadTopic("/tmp/naoqi_sim_e2e.top")
    try:
        dialog.activateTopic(name)
        dialog.subscribe("naoqi_sim_e2e")
        try:
            mark = time.monotonic()
            dialog.forceInput("hello robot")
            assert nao.played(mark, timeout=15) > 0.3
            said = [e for e in nao.container.speech_log() if "hello human" in str(e)]
            assert said
        finally:
            dialog.unsubscribe("naoqi_sim_e2e")
            dialog.deactivateTopic(name)
    finally:
        dialog.unloadTopic(name)
