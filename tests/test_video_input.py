"""The video input against a fake NAOqi (`ALVideoDevice`, `ALMemory`) and a fake frame source:
what it injects, at what rate, what it publishes, and how it lives through a closed viewer,
refused frames and a source that blocks."""

import logging
import threading
import time

import numpy as np
import pytest

from nao_sim import video_input
from nao_sim.video_input import VideoInput
from nao_sim.viewer import WorldClosed


class FakeNaoqi:
    """A qi session to a NAOqi whose ALVideoDevice records the frames put into it."""

    def __init__(self):
        self.puts: list[tuple[int, int, int, bytes, float]] = []
        self.memory: dict[str, str] = {}
        self.memory_log: list[str] = []
        self.refuse = False
        self.closed = False

    def service(self, name):
        return {"ALVideoDevice": self, "ALMemory": self}[name]

    def putImage(self, camera, width, height, data):
        if self.refuse:
            return False
        self.puts.append((camera, width, height, data, time.monotonic()))
        return True

    def insertData(self, key, value):
        self.memory[key] = value
        self.memory_log.append(value)

    def close(self):
        self.closed = True


class Frames:
    """A source of numbered frames: frame n has every pixel at n % 256."""

    name = "render"

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.count = 0
        self.closed = False
        self.block = threading.Event()

    def frame(self):
        if self.closed:
            raise WorldClosed("the viewer is closed")
        if self.block.is_set():
            time.sleep(10)
        time.sleep(self.delay)
        self.count += 1
        return np.full((480, 640, 3), self.count % 256, np.uint8)


@pytest.fixture
def naoqi():
    return FakeNaoqi()


def running(source, naoqi, fps=10) -> VideoInput:
    device = VideoInput(source, fps, connect=lambda: naoqi)
    device.start()
    return device


def wait_until(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_injects_the_sources_frames_into_the_top_camera_at_vga(naoqi):
    device = running(Frames(), naoqi)
    wait_until(lambda: len(naoqi.puts) >= 2)
    device.stop()

    camera, width, height, data, _ = naoqi.puts[0]
    assert (camera, width, height) == (0, 640, 480)
    image = np.frombuffer(data, np.uint8).reshape(480, 640, 3)
    assert (image == 1).all()  # the source's first frame, as it gave it
    assert np.frombuffer(naoqi.puts[1][3], np.uint8)[0] == 2


def test_paces_at_the_configured_rate(naoqi):
    device = running(Frames(), naoqi, fps=10)
    time.sleep(1.0)
    device.stop()

    assert 8 <= len(naoqi.puts) <= 11
    gaps = np.diff([put[4] for put in naoqi.puts])
    assert gaps.min() > 0.04  # never a burst (back to back would be ~0 s)


def test_a_slow_source_skips_slots_and_never_catches_up(naoqi):
    source = Frames(delay=0.08)  # slower than 30 fps' 33 ms
    device = running(source, naoqi, fps=30)
    time.sleep(0.6)
    source.delay = 0.0  # fast again: the missed slots are not made up
    time.sleep(0.4)
    device.stop()

    times = [put[4] for put in naoqi.puts]
    late = [t for t in times if t > times[0] + 0.65]
    assert len(times) < 30
    assert np.diff(late).min() > 0.01  # back on the 30 fps schedule, no burst


def test_publishes_its_source_while_it_runs(naoqi):
    device = running(Frames(), naoqi)
    assert naoqi.memory["NaoSim/Camera/Source"] == "render"
    device.stop()

    assert naoqi.memory["NaoSim/Camera/Source"] == "none"
    assert naoqi.closed


def test_a_closed_viewer_stops_the_camera_and_says_so_once(naoqi, caplog):
    source = Frames()
    device = running(source, naoqi)
    wait_until(lambda: len(naoqi.puts) >= 1)

    with caplog.at_level(logging.WARNING, logger="nao_sim.video_input"):
        source.closed = True  # the user closes the window
        wait_until(lambda: naoqi.memory["NaoSim/Camera/Source"] == "none")
        put = len(naoqi.puts)
        time.sleep(0.3)
        device.stop()

    assert len(naoqi.puts) == put  # nothing more injected
    assert [r.getMessage() for r in caplog.records] == [
        "the viewer is closed: the robot's camera gets no more frames"
    ]


def test_refused_frames_warn_once_and_injection_resumes(naoqi, caplog):
    naoqi.refuse = True
    with caplog.at_level(logging.WARNING, logger="nao_sim.video_input"):
        device = running(Frames(), naoqi, fps=30)
        time.sleep(0.3)
        naoqi.refuse = False
        wait_until(lambda: len(naoqi.puts) >= 2)
        device.stop()

    assert [r.getMessage() for r in caplog.records] == [
        "video input: putImage failed: NAOqi refused the frame"
    ]


def test_stop_does_not_wait_on_a_blocked_source(naoqi, monkeypatch):
    monkeypatch.setattr(video_input, "JOIN_TIMEOUT_S", 0.2)
    source = Frames()
    device = running(source, naoqi)
    wait_until(lambda: len(naoqi.puts) >= 1)
    source.block.set()  # the next frame takes 10 s
    time.sleep(0.2)

    started = time.monotonic()
    device.stop()
    assert time.monotonic() - started < 1.0
    assert naoqi.memory["NaoSim/Camera/Source"] == "none"
    device.stop()  # twice is harmless
