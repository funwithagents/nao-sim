"""The ALAudioPlayer replacement's core (docker/naoqi/services/audio-player/), against the real
host audio output with a memory sink on a free port: what it plays, how loud, where, how long."""

import json
import socket
import sys
import threading
import time
import wave
from pathlib import Path

import nao_sim_audio_player_core as core
import numpy as np
import pytest

from nao_sim.audio_output import RATE as MIX_RATE
from nao_sim.audio_output import AudioOutput, MemorySink, Server


@pytest.fixture
def output():
    sink = MemorySink()
    server = Server(("127.0.0.1", 0), AudioOutput(sink))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    yield sink, f"{host}:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def player(output, tmp_path):
    _, soundcard = output
    return core.Player(soundcard=soundcard, apps=str(tmp_path / "apps"))


def write_wav(
    path: Path, seconds: float, rate: int = 16000, level: int = 1000, channels=1
):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.full(int(seconds * rate) * channels, level, "<i2").tobytes())
    return str(path)


def params(**p) -> str:
    return json.dumps(p)


def play(player, tid, path, **p):
    player.start(tid, "file", params(path=path, **p))


def wait_done(player, tid, timeout=5.0):
    end = time.monotonic() + timeout
    while not player.wait_done(tid, 0.02):
        assert time.monotonic() < end, f"call {tid} still running"


def mix_frames(sink: MemorySink) -> np.ndarray:
    return np.frombuffer(sink.mixes[-1].pcm, "<i2").reshape(-1, 2)


# -- playing a file -----------------------------------------------------------------------


def test_a_file_plays_for_its_length_as_its_own_stream(player, output, tmp_path):
    sink, _ = output
    path = write_wav(tmp_path / "beep.wav", 0.5)
    t0 = time.monotonic()
    play(player, 7, path)
    assert player.wait_done(7, 0.1) is False  # still playing
    wait_done(player, 7)

    assert time.monotonic() - t0 == pytest.approx(0.5, abs=0.25)
    [p] = sink.playbacks
    assert (p.stream, p.rate, p.channels, p.interrupted) == (
        "player:7",
        16000,
        1,
        False,
    )
    assert p.duration_s == pytest.approx(0.5)


def test_volume_master_volume_and_pan_reach_the_mix(player, output, tmp_path):
    sink, _ = output
    player.set_master_volume(0.5)
    play(player, 1, write_wav(tmp_path / "a.wav", 0.4), volume=0.5, pan=-1.0)
    wait_done(player, 1)

    left, right = mix_frames(sink)[int(0.2 * MIX_RATE)]
    assert (left, right) == (250, 0)  # 1000 x 0.5 x 0.5, all on the left


def test_set_volume_changes_a_playing_sound(player, output, tmp_path):
    sink, _ = output
    play(player, 2, write_wav(tmp_path / "a.wav", 0.8))
    time.sleep(0.3)
    assert player.get_volume(2) == 1.0
    player.set_volume(2, 0.25)
    wait_done(player, 2)

    mix = mix_frames(sink)
    assert mix[int(0.15 * MIX_RATE)].tolist() == [1000, 1000]
    assert mix[-int(0.1 * MIX_RATE)].tolist() == [250, 250]


@pytest.fixture
def sndfile_convert(monkeypatch, tmp_path):
    """A stand-in for the suite's sndfile-convert: it 'decodes' an .ogg to a known WAV and, as
    libsndfile does, refuses an MP3."""
    decoded = write_wav(tmp_path / "decoded.wav", 0.3, rate=48000, channels=2)
    script = tmp_path / "sndfile-convert"
    script.write_text(
        f"#!{sys.executable}\n"
        "import shutil, sys\n"
        "src, dst = sys.argv[2], sys.argv[3]\n"
        "if src.endswith('.mp3'):\n"
        "    print('File contains data in an unknown format.'); sys.exit(1)\n"
        f"shutil.copy({decoded!r}, dst)\n"
    )
    script.chmod(0o755)
    monkeypatch.setattr(core, "SNDFILE_CONVERT", str(script))


def test_an_ogg_is_decoded_by_libsndfile(player, output, tmp_path, sndfile_convert):
    sink, _ = output
    ogg = tmp_path / "hey.ogg"
    ogg.write_bytes(b"OggS not really")
    play(player, 3, str(ogg))
    wait_done(player, 3)

    [p] = sink.playbacks
    assert (p.rate, p.channels) == (48000, 2)
    assert p.duration_s == pytest.approx(0.3)


def test_an_mp3_is_refused_with_libsndfile_s_message(player, tmp_path, sndfile_convert):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"ID3 not really")
    with pytest.raises(core.PlayerError, match="unknown format"):
        play(player, 4, str(mp3))


def test_a_missing_file_is_refused(player):
    with pytest.raises(core.PlayerError, match="not found"):
        play(player, 5, "/no/such/sound.wav")


# -- stopping ------------------------------------------------------------------------------


def test_a_loop_plays_until_stopped(player, output, tmp_path):
    sink, _ = output
    play(player, 8, write_wav(tmp_path / "a.wav", 0.2), loop=True)
    time.sleep(0.7)
    assert player.wait_done(8, 0.0) is False  # well past the file's length
    player.stop_call(8)
    wait_done(player, 8, timeout=1.0)

    [p] = sink.playbacks
    assert p.interrupted and p.duration_s > 0.4


def test_stop_all_stops_the_sounds_and_not_the_speech(player, output, tmp_path):
    sink, soundcard = output
    host, port = soundcard.rsplit(":", 1)
    speech_done: list[bool] = []

    def speak():
        with socket.create_connection((host, int(port))) as s:
            header = {"cmd": "play", "stream": "speech", "rate": 16000, "channels": 1}
            s.sendall(json.dumps(header).encode() + b"\n")
            s.sendall(np.full(16000, 500, "<i2").tobytes())  # 1 s
            s.shutdown(socket.SHUT_WR)
            while s.recv(4096):
                pass
        speech_done.append(True)

    threading.Thread(target=speak, daemon=True).start()
    play(player, 9, write_wav(tmp_path / "a.wav", 0.2), loop=True)
    play(player, 10, write_wav(tmp_path / "b.wav", 2.0))
    time.sleep(0.3)
    player.stop_all()
    wait_done(player, 9, timeout=1.0)
    wait_done(player, 10, timeout=1.0)
    end = time.monotonic() + 3
    while not speech_done and time.monotonic() < end:
        time.sleep(0.02)

    by_name = {p.stream: p for p in sink.playbacks}
    assert by_name["player:9"].interrupted and by_name["player:10"].interrupted
    assert not by_name["speech"].interrupted
    assert by_name["speech"].duration_s == pytest.approx(1.0)


# -- loaded files, pause, goTo, positions ---------------------------------------------------------


def test_loaded_files_have_ids_and_names(player, tmp_path):
    a = player.load_file(write_wav(tmp_path / "a.wav", 0.1))
    b = player.load_file(write_wav(tmp_path / "b.wav", 0.1))

    assert a >= core.FIRST_OWN_ID and b == a + 1
    assert player.get_loaded_files_ids() == [str(a), str(b)]
    assert player.get_loaded_files_names() == [
        str(tmp_path / "a.wav"),
        str(tmp_path / "b.wav"),
    ]
    assert player.get_file_length(a) == pytest.approx(0.1)
    player.unload_file(a)
    assert player.get_loaded_files_ids() == [str(b)]
    player.unload_all_files()
    assert player.get_loaded_files_ids() == []


def test_play_pause_and_play_again_of_a_loaded_file(player, output, tmp_path):
    sink, _ = output
    fid = player.load_file(write_wav(tmp_path / "a.wav", 0.6))
    t0 = time.monotonic()
    player.start(11, "loaded", params(id=fid))
    time.sleep(0.2)
    player.pause(fid)
    paused_at = player.get_current_position(11)
    time.sleep(0.4)
    assert player.get_current_position(11) == pytest.approx(paused_at, abs=0.01)
    player.start(12, "loaded", params(id=fid))  # play() again: goes on where it was
    wait_done(player, 12)
    wait_done(player, 11)

    assert time.monotonic() - t0 == pytest.approx(0.6 + 0.4, abs=0.3)
    [p] = sink.playbacks
    assert not p.interrupted and p.duration_s == pytest.approx(0.6)


def test_go_to_jumps_and_the_position_follows(player, output, tmp_path):
    play(player, 13, write_wav(tmp_path / "a.wav", 2.0))
    time.sleep(0.2)
    assert player.get_current_position(13) == pytest.approx(0.2, abs=0.15)
    assert player.get_file_length(13) == pytest.approx(2.0)
    t_jump = time.monotonic()
    player.go_to(13, 1.6)
    time.sleep(0.15)
    assert player.get_current_position(13) == pytest.approx(1.6 + 0.15, abs=0.15)
    wait_done(player, 13)

    assert time.monotonic() - t_jump == pytest.approx(
        0.4, abs=0.25
    )  # the rest after 1.6 s


def test_unknown_ids_are_refused_or_ignored(player):
    with pytest.raises(core.PlayerError):
        player.get_current_position(424242)
    player.stop_call(424242)  # stopping something unknown does nothing
    assert player.wait_done(424242, 0.0) is True


# -- sound sets ---------------------------------------------------------------------------------


def test_sound_sets_are_the_soundset_packages_of_the_package_store(
    player, output, tmp_path
):
    sink, _ = output
    folder = tmp_path / "apps" / "soundsetaldebaran"
    folder.mkdir(parents=True)
    write_wav(folder / "sfx_hello.wav", 0.2)
    (tmp_path / "apps" / "animations").mkdir()

    assert player.get_installed_sound_sets_list() == ["Aldebaran"]
    assert player.is_sound_set_installed("Aldebaran") and player.is_sound_set_installed(
        "aldebaran"
    )
    assert player.get_sound_set_file_names("Aldebaran") == ["sfx_hello"]
    assert player.is_sound_set_file_installed("Aldebaran", "sfx_hello")
    assert not player.is_sound_set_file_installed("Aldebaran", "nope")
    with pytest.raises(core.PlayerError, match="no sound set loaded"):
        player.start(20, "soundset", params(file="sfx_hello"))
    player.load_sound_set("Aldebaran")
    assert player.get_loaded_sound_sets_list() == ["Aldebaran"]
    player.start(21, "soundset", params(file="sfx_hello"))  # from any loaded set
    wait_done(player, 21)
    player.start(22, "soundset", params(set="Aldebaran", file="sfx_hello.wav"))
    wait_done(player, 22)
    player.unload_sound_set("aldebaran")

    assert player.get_loaded_sound_sets_list() == []
    assert [p.stream for p in sink.playbacks] == ["player:21", "player:22"]
    with pytest.raises(core.PlayerError, match="not installed"):
        player.load_sound_set("Pepper")


# -- synthesis and an absent audio output ----------------------------------------------------------


def test_play_sine_plays_its_tone_for_its_duration(player, output):
    sink, _ = output
    player.start(30, "sine", params(frequency=1000, gain=50, pan=0, duration=0.3))
    wait_done(player, 30)

    [p] = sink.playbacks
    samples = np.frombuffer(p.pcm, "<i2").astype(float)
    assert p.duration_s == pytest.approx(0.3, abs=0.01)
    assert np.abs(samples).max() == pytest.approx(0.5 * 32767, rel=0.01)
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), 1 / p.rate)
    assert freqs[np.argmax(spectrum)] == pytest.approx(1000, abs=5)


def test_without_an_audio_output_a_call_still_lasts_the_file(tmp_path):
    player = core.Player(soundcard="127.0.0.1:9", apps=str(tmp_path))  # nothing listens
    t0 = time.monotonic()
    play(player, 40, write_wav(tmp_path / "a.wav", 0.4))
    wait_done(player, 40)
    assert time.monotonic() - t0 == pytest.approx(0.4, abs=0.15)
