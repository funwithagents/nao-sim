"""The robot's microphones on each NAOqi version, as an audio client hears them: it registers a
service with `processRemote` and subscribes to `ALAudioDevice`, as nao-bridge does, while the test
plays sounds through the fake audio source (the live tier runs it). The buffers come through the
host link, the Python 2.7 replacement and the native relay."""

import time

import numpy as np
import pytest
import qi
from support import Listener, connect, peak_hz, tone

FRONT_16K = (16000, 3, 0)
CHUNK_16K, CHUNK_48K = 1365, 4096


@pytest.fixture
def listen(nao):
    """Subscribes listeners like clients, and unsubscribes them after the test."""
    made: list[Listener] = []

    def make(*preferences, session=None):
        listener = Listener(session or nao.session)
        made.append(listener)
        return listener.subscribe(*preferences)

    yield make
    for listener in made:
        listener.close()
    nao.audio.stop()


def test_the_robot_says_its_microphones_are_the_fake_source(nao):
    memory = nao.service("ALMemory")
    assert memory.getData("NaoSim/Audio/Source") == "fake"
    assert memory.getData("NaoSim/Audio/Channels") == "duplicate"
    names = {s["name"] for s in nao.session.services()}
    assert {"ALAudioDevice", "_NaoSimAudioRelay"} <= names


def test_a_client_gets_bytearray_chunks_of_silence_at_the_nao_cadence(listen):
    listener = listen(*FRONT_16K)
    time.sleep(0.3)  # let the subscription settle
    start = time.monotonic()
    time.sleep(2.0)
    chunks = listener.received(since=start)
    assert 21 <= len(chunks) <= 26  # 1365 samples at 16 kHz: about 11.7 per second
    first = chunks[0]
    assert isinstance(first.buffer, bytearray)  # a binary, as from a NAO's C++ device
    assert (first.channels, first.samples) == (1, CHUNK_16K)
    assert len(first.buffer) == 2 * CHUNK_16K
    assert not any(c.pcm().any() for c in chunks)  # a quiet room
    stamps = [s + us / 1e6 for s, us in (c.stamp for c in chunks)]
    gaps = np.diff(stamps)
    assert np.all(gaps > 0) and np.median(gaps) == pytest.approx(
        CHUNK_16K / 16000, abs=0.02
    )


def test_split_sounds_arrive_in_order_with_their_pitch_and_timing(nao, listen):
    listener = listen(*FRONT_16K)
    time.sleep(0.3)
    first = nao.audio.play(tone(440, 1.0, 16000), 16000)
    first.wait(3)
    time.sleep(0.5)
    second = nao.audio.play(tone(1000, 0.7, 16000), 16000)
    second.wait(3)
    time.sleep(0.4)
    times, values = listener.timeline(16000, since=first.started_at - 0.2)
    for take, freq in ((first, 440), (second, 1000)):
        inside = (times > take.started_at + 0.15) & (times < take.ended_at - 0.15)
        assert peak_hz(values[inside], 16000) == pytest.approx(freq, abs=10)
        loud = times[np.abs(values) > 2000]
        heard = loud[(loud > take.started_at - 0.3) & (loud < take.ended_at + 0.3)]
        # Heard when it plays: link and relay add a few ms; the chunking is what we allow for.
        assert heard.min() == pytest.approx(take.started_at, abs=0.15)
        assert heard.max() == pytest.approx(take.ended_at, abs=0.15)
    between = (times > first.ended_at + 0.15) & (times < second.started_at - 0.15)
    assert not np.abs(values[between]).max() > 200  # silence between the takes


def test_the_default_format_is_48k_with_four_channels(nao, listen):
    listener = listen()  # no setClientPreferences: NAO's default
    time.sleep(0.3)
    take = nao.audio.play(tone(440, 0.6, 16000), 16000)
    take.wait(3)
    time.sleep(0.3)
    chunks = listener.received(since=take.started_at)
    assert {(c.channels, c.samples) for c in chunks} == {(4, CHUNK_48K)}
    pcm = np.concatenate([c.pcm() for c in chunks])
    assert np.abs(pcm).max() > 7000
    assert all(
        np.array_equal(pcm[:, 0], pcm[:, i]) for i in (1, 2, 3)
    )  # duplicated mono


def test_deinterleaved_buffers_lay_each_channel_after_the_other(nao, listen):
    listener = listen(48000, 0, 1)
    time.sleep(0.3)
    take = nao.audio.play(tone(440, 0.4, 48000), 48000)
    take.wait(3)
    time.sleep(0.3)
    loud = [c for c in listener.received() if np.abs(c.pcm()).max() > 1000]
    assert loud
    blocks = np.frombuffer(bytes(loud[0].buffer), "<i2").reshape(4, CHUNK_48K)
    assert all(np.array_equal(blocks[0], blocks[i]) for i in (1, 2, 3))
    assert peak_hz(blocks[0], 48000) == pytest.approx(440, abs=15)


def test_two_formats_at_once(nao, listen):
    low = listen(*FRONT_16K)
    high = listen(48000, 0, 0)
    time.sleep(1.0)
    assert {c.samples for c in low.received()} == {CHUNK_16K}
    assert {c.samples for c in high.received()} == {CHUNK_48K}


def test_the_robot_does_not_hear_itself(nao, listen):
    """The microphone gate on every run: a sound played across the robot's speech reaches the
    client as zeros from the speech's start until its end plus the gate's tail."""
    listener = listen(*FRONT_16K)
    time.sleep(0.3)
    take = nao.audio.play(tone(440, 8.0, 16000), 16000)
    time.sleep(1.0)
    said = time.monotonic()
    nao.service("ALTextToSpeech").say("I do not hear my own voice.")
    speech = nao.sink.wait_for(lambda p: p.started_at >= said, 10)
    time.sleep(1.0)
    nao.audio.stop()
    tail = nao.sim.config.audio_input.gate_tail_s
    times, values = listener.timeline(16000, since=take.started_at)
    loud = times[np.abs(values) > 2000]
    gate_from, gate_to = speech.started_at, speech.ended_at + tail
    assert gate_to - gate_from > 0.8  # a real sentence
    assert not np.any((loud > gate_from + 0.1) & (loud < gate_to - 0.15))
    assert np.any((loud > gate_from - 0.5) & (loud < gate_from))  # heard before
    assert np.any((loud > gate_to + 0.15) & (loud < gate_to + 0.8))  # and after


def test_energy_follows_the_room(nao):
    device = nao.service("ALAudioDevice")
    device.enableEnergyComputation()
    try:
        take = nao.audio.play(tone(440, 1.5, 16000), 16000)
        time.sleep(0.8)
        during = device.getFrontMicEnergy()
        take.wait(3)
        time.sleep(0.5)
        after = device.getFrontMicEnergy()
    finally:
        device.disableEnergyComputation()
    assert during == pytest.approx(8000 / np.sqrt(2), rel=0.1)
    assert after < 50
    assert device.getFrontMicEnergy() == 0.0  # disabled


def test_unsubscribe_stops_the_buffers(listen, nao):
    listener = listen(*FRONT_16K)
    listener.wait(3)
    nao.service("ALAudioDevice").unsubscribe(listener.name)
    stopped = time.monotonic()
    time.sleep(0.6)
    assert not listener.received(since=stopped + 0.2)


def test_formats_naoqi_does_not_offer_are_refused(nao):
    listener = Listener(nao.session)
    try:
        with pytest.raises(RuntimeError, match="unsupported format"):
            nao.service("ALAudioDevice").setClientPreferences(
                listener.name, 44100, 0, 0
            )
        with pytest.raises(RuntimeError, match="unsupported format"):
            nao.service("ALAudioDevice").setClientPreferences(
                listener.name, 48000, 3, 0
            )
    finally:
        listener.close()


def test_a_client_that_disappears_does_not_disturb_another(nao, listen):
    gone_session: qi.Session = connect(nao.sim.url)
    listen(*FRONT_16K, session=gone_session).wait(2)
    staying = listen(*FRONT_16K)
    gone_session.close()  # without unsubscribing
    time.sleep(1.0)
    since = time.monotonic()
    time.sleep(1.0)
    assert 10 <= len(staying.received(since=since)) <= 13
