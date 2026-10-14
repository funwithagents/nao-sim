"""The video input against a fake NAOqi (`ALVideoDevice`, `ALMemory`) and a fake frame source:
what it injects, at what rate, what it publishes, and how it lives through a closed viewer,
refused frames and a source that blocks."""

import logging
import threading
import time

import numpy as np
import pytest

from naoqi_sim import video_input
from naoqi_sim.video_input import VideoInput
from naoqi_sim.viewer import WorldClosed


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


class Ran:
    """The time a device ran, measured from outside: at least from after `start()` returned to
    when `stop()` was called, at most from before `start()` to after `stop()` returned. A slow
    machine stretches the sleeps in between; the device's schedule follows the time it ran."""

    def __init__(self, fps: int) -> None:
        self.fps = fps

    def start(self, source, naoqi) -> VideoInput:
        self.t0 = time.monotonic()
        device = running(source, naoqi, fps=self.fps)
        self.t1 = time.monotonic()
        return device

    def stop(self, device: VideoInput) -> None:
        self.t2 = time.monotonic()
        device.stop()
        self.t3 = time.monotonic()

    def slots(self, lateness: float) -> tuple[float, float]:
        """The fewest and most slots of the schedule in that time. A machine that wakes threads
        `lateness` seconds late (a CI virtual machine) loses slots at both ends: before the
        device's thread first runs, and after the last slot it handled when `stop()` finds it
        sleeping late, besides the frame in flight (specs/testing/testing.md, "Platforms")."""
        fewest = (self.t2 - self.t1 - 2 * lateness) * self.fps - 2
        return fewest, (self.t3 - self.t0) * self.fps + 1


def test_paces_at_the_configured_rate(naoqi, lateness):
    ran = Ran(fps=10)
    device = ran.start(Frames(), naoqi)
    time.sleep(1.0)
    ran.stop(device)

    # Each slot puts its frame, or is missed (a render or an injection stalled past it, as on a
    # loaded machine), never caught up with a second frame.
    fewest, most = ran.slots(lateness())
    assert len(naoqi.puts) <= most
    assert fewest <= len(naoqi.puts) + device.missed <= most
    gaps = np.diff([put[4] for put in naoqi.puts])
    # Never a burst: missed slots made up would put frames back to back (well under a
    # millisecond apart), where a frame woken late still lands before the next slot's.
    assert gaps.min() > 0.001


def test_a_slow_source_skips_slots_and_never_catches_up(naoqi, lateness):
    source = Frames(delay=0.08)  # slower than 30 fps' 33 ms
    ran = Ran(fps=30)
    device = ran.start(source, naoqi)
    time.sleep(0.6)
    source.delay = 0.0  # fast again: the missed slots are not made up
    time.sleep(0.4)
    ran.stop(device)

    times = [put[4] for put in naoqi.puts]
    late = [t for t in times if t > times[0] + 0.65]
    fewest, most = ran.slots(lateness())
    assert device.missed >= 5  # a frame every 80 ms missed slots of 33 ms
    assert fewest <= len(times) + device.missed <= most  # missed, not lost
    # Back on the 30 fps schedule: a burst would put the missed frames back to back (well under
    # a millisecond apart), where a frame woken late still lands before the next slot's.
    assert np.diff(late).min() > 0.001


def test_publishes_its_source_while_it_runs(naoqi):
    device = running(Frames(), naoqi)
    assert naoqi.memory["NaoqiSim/Camera/Source"] == "render"
    device.stop()

    assert naoqi.memory["NaoqiSim/Camera/Source"] == "none"
    assert naoqi.closed


def test_a_closed_viewer_stops_the_camera_and_says_so_once(naoqi, caplog):
    source = Frames()
    device = running(source, naoqi)
    wait_until(lambda: len(naoqi.puts) >= 1)

    with caplog.at_level(logging.WARNING, logger="naoqi_sim.video_input"):
        source.closed = True  # the user closes the window
        wait_until(lambda: naoqi.memory["NaoqiSim/Camera/Source"] == "none")
        put = len(naoqi.puts)
        time.sleep(0.3)
        device.stop()

    assert len(naoqi.puts) == put  # nothing more injected
    assert [r.getMessage() for r in caplog.records] == [
        "the viewer is closed: the robot's camera gets no more frames"
    ]


def test_refused_frames_warn_once_and_injection_resumes(naoqi, caplog):
    naoqi.refuse = True
    with caplog.at_level(logging.WARNING, logger="naoqi_sim.video_input"):
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
    assert naoqi.memory["NaoqiSim/Camera/Source"] == "none"
    device.stop()  # twice is harmless
