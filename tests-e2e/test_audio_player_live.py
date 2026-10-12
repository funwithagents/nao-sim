"""ALAudioPlayer through a running naoqi-sim stack, on each NAOqi version: the C++ front, its Python
core and the host audio output's mixer together (specs/services/audio-player.md), driven over qi
and, for the boxes' pattern, from inside NAOqi as Choregraphe runs a box."""

import time

import numpy as np
import pytest
from support import box

from naoqi_sim.audio_output import RATE as MIX_RATE

LONG = (
    "This is a long sentence the robot says while a sound plays, and it goes on and on so "
    "that there is plenty of speech around the sound."
)

# Written inside the container by the test: NAOqi reads them where it runs.
FILES = """
import math, os, struct, wave
os.path.isdir("/tmp/naoqi-sim-test") or os.makedirs("/tmp/naoqi-sim-test")
def write(name, seconds, level, rate=16000):
    w = wave.open("/tmp/naoqi-sim-test/" + name, "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(struct.pack("<h", level) * int(seconds * rate))
    w.close()
def run():
    write("one-second.wav", 1.0, 3000)
    write("three-seconds.wav", 3.0, 3000)
    open("/tmp/naoqi-sim-test/song.mp3", "wb").write(b"ID3" + b"\\0" * 1024)
    found = None
    for root in ("/home/nao/.local/share/PackageManager/apps", "/opt/naoqi/share/naoqi/apps",
                 "/opt/aldebaran/share/naoqi/apps"):
        for d, _, names in os.walk(root):
            if "hey6.ogg" in names:
                found = os.path.join(d, "hey6.ogg")
                break
        if found:
            break
    return {"ogg": found}
"""


@pytest.fixture(scope="module")
def files(nao):
    out = nao.run_in_naoqi(FILES)
    return {
        "wav": "/tmp/naoqi-sim-test/one-second.wav",
        "long": "/tmp/naoqi-sim-test/three-seconds.wav",
        "mp3": "/tmp/naoqi-sim-test/song.mp3",
        "ogg": out["ogg"],
    }


def sound(nao, after: float, timeout: float = 10.0):
    """The first player stream that started after `after`."""
    return nao.sink.wait_for(
        lambda p: p.stream.startswith("player:") and p.started_at >= after, timeout
    )


def mix_after(nao, after: float) -> np.ndarray:
    runs = [m for m in nao.sink.mixes if m.started_at >= after - 0.05]
    return np.frombuffer(b"".join(m.pcm for m in runs), "<i2").reshape(-1, 2)


def test_the_front_serves_al_audio_player(nao):
    assert "naoqi-sim C++ front" in nao.service("ALAudioPlayer").whoami()


def test_a_wav_plays_for_its_length_as_its_own_stream(nao, files):
    player = nao.service("ALAudioPlayer")
    mark = time.monotonic()
    player.playFile(files["wav"])
    took = time.monotonic() - mark
    p = sound(nao, mark)

    assert took == pytest.approx(1.0, abs=0.4)  # blocks for the sound
    assert (p.rate, p.channels, p.interrupted) == (16000, 1, False)
    assert p.duration_s == pytest.approx(1.0, abs=0.01)


def test_the_robot_s_own_ogg_plays(nao, files):
    if files["ogg"] is None:
        pytest.fail("hey6.ogg not found in the installed animations package")
    mark = time.monotonic()
    nao.service("ALAudioPlayer").playFile(files["ogg"])
    p = sound(nao, mark)

    assert (p.rate, p.channels) == (48000, 2)  # decoded by the suite's libsndfile
    assert p.duration_s == pytest.approx(0.534, abs=0.01)


def test_an_mp3_is_refused_as_on_a_virtual_robot(nao, files):
    with pytest.raises(RuntimeError, match="(?i)format"):
        nao.service("ALAudioPlayer").playFile(files["mp3"])


def test_volume_and_pan_reach_the_mix(nao, files):
    mark = time.monotonic()
    nao.service("ALAudioPlayer").playFile(files["wav"], 0.5, -1.0)
    sound(nao, mark)

    mix = mix_after(nao, mark)
    loud = mix[np.abs(mix[:, 0]) > 0]
    assert np.median(loud[:, 0]) == pytest.approx(
        1500, abs=10
    )  # half of 3000, on the left
    assert np.abs(loud[:, 1]).max() == 0  # nothing on the right


# -- the Play Sound box's pattern ----------------------------------------------------------------


def test_the_play_sound_box_stops_its_sound(nao, files):
    mark = time.monotonic()
    out = box(
        nao,
        f"""
def run():
    player, stopper = proxies("ALAudioPlayer")
    t0 = time.time()
    tid = start(player, "playFileFromPosition", {files["long"]!r}, 0.0, 1.0, 0.0)
    time.sleep(0.4)
    player.setVolume(tid, 0.5)
    stop_later(stopper, tid, 0.6)
    wait(player, tid)
    return {{"id": tid, "waited": time.time() - t0}}
""",
    )
    p = sound(nao, mark)

    assert out["id"] >= 0 and p.stream == f"player:{out['id']}"
    assert out["waited"] < 1.5  # the stop at 1 s, not the 3 s of the sound
    assert p.interrupted and p.duration_s < 1.6
    mix = mix_after(nao, mark)[:, 0]
    playing = mix[mix != 0]
    assert playing[: int(0.2 * MIX_RATE)].mean() == pytest.approx(3000, abs=50)
    assert playing[-int(0.1 * MIX_RATE) :].mean() == pytest.approx(
        1500, abs=50
    )  # setVolume


def test_of_two_sounds_only_the_stopped_one_ends(nao, files):
    mark = time.monotonic()
    out = box(
        nao,
        f"""
def run():
    player, stopper = proxies("ALAudioPlayer")
    a = start(player, "playFileFromPosition", {files["long"]!r}, 0.0, 1.0, 0.0)
    b = start(player, "playFileFromPosition", {files["long"]!r}, 0.0, 1.0, 0.0)
    stop_later(stopper, a, 0.5)
    t0 = time.time()
    wait(player, a)
    waited_a = time.time() - t0
    wait(player, b)
    return {{"a": a, "b": b, "waited_a": waited_a, "waited_b": time.time() - t0}}
""",
    )
    time.sleep(0.2)
    by_name = {
        p.stream: p
        for p in nao.sink.playbacks
        if p.stream.startswith("player:") and p.started_at >= mark
    }

    assert out["waited_a"] < 1.0 and out["waited_b"] > 2.5
    assert by_name[f"player:{out['a']}"].interrupted
    assert not by_name[f"player:{out['b']}"].interrupted


# -- with speech ---------------------------------------------------------------------------------


def test_stop_all_stops_the_sounds_and_the_speech_goes_on(nao, files):
    tts, player = nao.service("ALTextToSpeech"), nao.service("ALAudioPlayer")
    mark = time.monotonic()
    speech = tts.say(LONG, _async=True)
    looping = player.playFileInLoop(files["wav"], _async=True)
    time.sleep(1.5)
    player.stopAll()
    looping.wait(5000)
    speech.wait(30000)

    loop = sound(nao, mark)
    said = nao.sink.wait_for(lambda p: p.stream == "speech" and p.started_at >= mark)
    assert loop.interrupted and loop.duration_s > 1.0
    assert not said.interrupted


def test_a_sound_and_a_sentence_play_together(nao, files):
    tts, player = nao.service("ALTextToSpeech"), nao.service("ALAudioPlayer")
    mark = time.monotonic()
    speech = tts.say(LONG, _async=True)
    time.sleep(1.0)
    player.playFile(files["wav"])
    speech.wait(30000)

    beep = sound(nao, mark)
    said = nao.sink.wait_for(lambda p: p.stream == "speech" and p.started_at >= mark)
    assert said.ended_at is not None and beep.ended_at is not None
    assert (
        said.started_at < beep.started_at < beep.ended_at < said.ended_at
    )  # inside the sentence
    assert not said.interrupted and not beep.interrupted


# -- loaded files, positions, synthesis, sound sets -------------------------------------------------


def test_a_loaded_file_plays_pauses_and_goes_on(nao, files):
    player = nao.service("ALAudioPlayer")
    fid = player.loadFile(files["long"])
    assert str(fid) in player.getLoadedFilesIds()
    assert player.getFileLength(fid) == pytest.approx(3.0, abs=0.01)
    mark = time.monotonic()
    playing = player.play(fid, _async=True)
    time.sleep(0.8)
    player.pause(fid)
    paused_at = player.getCurrentPosition(fid)
    time.sleep(0.5)
    assert player.getCurrentPosition(fid) == pytest.approx(paused_at, abs=0.02)
    resumed = player.play(fid, _async=True)  # play() of a paused file goes on with it
    resumed.wait(10000)
    playing.wait(10000)
    player.unloadFile(fid)

    p = sound(nao, mark)
    assert paused_at == pytest.approx(0.8, abs=0.25)
    assert not p.interrupted and p.duration_s == pytest.approx(3.0, abs=0.01)
    assert p.ended_at is not None and p.ended_at - p.started_at == pytest.approx(
        3.5, abs=0.4
    )
    assert str(fid) not in player.getLoadedFilesIds()


def test_play_sine_plays_for_its_duration(nao):
    mark = time.monotonic()
    nao.service("ALAudioPlayer").playSine(1000, 30, 0, 0.5)
    p = sound(nao, mark)

    samples = np.frombuffer(p.pcm, "<i2").astype(float)
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), 1 / p.rate)
    assert p.duration_s == pytest.approx(0.5, abs=0.01)
    assert freqs[np.argmax(spectrum)] == pytest.approx(1000, abs=5)


def test_sound_sets_when_one_is_installed(nao):
    player = nao.service("ALAudioPlayer")
    sets = player.getInstalledSoundSetsList()
    if "Aldebaran" not in sets:
        pytest.skip("no soundsetaldebaran package installed (user-supplied)")
    player.loadSoundSet("Aldebaran")
    name = player.getSoundSetFileNames("Aldebaran")[0]
    mark = time.monotonic()
    player.playSoundSetFile("Aldebaran", name)
    assert sound(nao, mark).duration_s > 0
