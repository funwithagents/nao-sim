"""The webcam source against a fake camera: the frames it serves (cropped, scaled, RGB, the
newest), the start check's errors, and how it lives through a camera that does not open, stops
delivering or blocks. The conversion runs on the real OpenCV (the dev group takes the extra)."""

import logging
import sys
import threading
import time

import numpy as np
import pytest

from naoqi_sim import webcam
from naoqi_sim.errors import DeviceUnavailableError, MissingExtraError
from naoqi_sim.video_input import NoFrame
from naoqi_sim.webcam import Webcam, check_webcam, to_vga


class Camera:
    """A host camera: every capture opened on it reads numbered 1280x720 BGR frames (every
    pixel at n % 256) about every 10 ms while `delivering`, fails its reads when not, and
    blocks while `blocked` is clear. With `stepping`, a read waits for the test to release
    each frame, and `reads` counts the reads begun."""

    def __init__(self):
        self.opens = 0
        self.released = 0
        self.opening = True  # whether a capture opens
        self.delivering = True
        self.blocked = threading.Event()
        self.blocked.set()
        self.stepping: threading.Semaphore | None = None
        self.reads = 0
        self.count = 0

    def open(self, device):
        self.opens += 1
        camera = self

        class Capture:
            def isOpened(self):
                return camera.opening

            def read(self):
                camera.reads += 1
                if camera.stepping is not None:
                    camera.stepping.acquire()
                camera.blocked.wait()
                time.sleep(0.01)
                if not camera.delivering:
                    return False, None
                camera.count += 1
                return True, np.full((720, 1280, 3), camera.count % 256, np.uint8)

            def getBackendName(self):
                return "FAKE"

            def release(self):
                camera.released += 1

        return Capture()


def wait_until(predicate, timeout=5.0):
    """A deadline for something that happens in milliseconds, generous for a loaded runner."""
    end = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def has_frame(source) -> bool:
    try:
        source.frame()
    except NoFrame:
        return False
    return True


@pytest.fixture
def camera():
    return Camera()


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(webcam.platform, "system", lambda: "Linux")


# --- The frames ---------------------------------------------------------------------


def test_a_wide_frame_loses_its_sides_and_comes_out_vga_rgb():
    bgr = np.zeros((720, 1280, 3), np.uint8)
    bgr[:, :] = (0, 0, 255)  # red sides, in BGR
    bgr[:, 160:1120] = (255, 128, 0)  # the 4:3 centre: blue-ish
    image = to_vga(bgr)
    assert image.shape == (480, 640, 3) and image.dtype == np.uint8
    assert (image == (0, 128, 255)).all()  # the centre only, in RGB


def test_a_tall_frame_loses_its_top_and_bottom():
    bgr = np.zeros((720, 480, 3), np.uint8)
    bgr[180:540] = (10, 20, 30)  # the 4:3 centre of a 480-wide frame: 360 rows
    image = to_vga(bgr)
    assert image.shape == (480, 640, 3)
    assert (image == (30, 20, 10)).all()


def test_a_vga_frame_is_only_converted_to_rgb():
    bgr = np.random.default_rng(0).integers(0, 256, (480, 640, 3), np.uint8)
    assert (
        to_vga(bgr) == bgr[:, :, ::-1]
    ).all()  # not cropped, not scaled, not mirrored


# --- The start check -----------------------------------------------------------------


def test_the_check_opens_reads_and_releases_the_camera(camera):
    check_webcam(0, ["video_input.top"], camera.open)
    assert camera.opens == 1 and camera.released == 1 and camera.count == 1


@pytest.mark.parametrize(
    ("opening", "delivering", "message"),
    [
        (False, True, "webcam 2 does not open"),
        (True, False, "webcam 2 gives no frame"),
    ],
)
def test_a_camera_that_fails_the_check_names_its_keys_and_is_released(
    camera, linux, opening, delivering, message
):
    camera.opening, camera.delivering = opening, delivering
    with pytest.raises(DeviceUnavailableError) as raised:
        check_webcam(2, ["video_input.top", "video_input.bottom"], camera.open)
    assert str(raised.value) == (
        f"video_input.top.source and video_input.bottom.source 'webcam': {message}"
    )
    assert camera.released == 1


def test_on_macos_the_error_says_where_the_camera_permission_is(camera, monkeypatch):
    monkeypatch.setattr(webcam.platform, "system", lambda: "Darwin")
    camera.opening = False
    with pytest.raises(DeviceUnavailableError, match="Privacy & Security > Camera"):
        check_webcam(0, ["video_input.top"], camera.open)


def test_without_opencv_the_check_names_the_extra(camera, monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)  # `import cv2` raises ImportError
    with pytest.raises(MissingExtraError, match=r"naoqi-sim\[webcam\]"):
        check_webcam(0, ["video_input.top"], camera.open)
    assert camera.opens == 0


# --- A running webcam ----------------------------------------------------------------


def test_serves_the_newest_frame_converted_once(camera):
    camera.stepping = threading.Semaphore(0)
    source = Webcam(0, camera.open)
    source.start()
    try:
        camera.stepping.release(3)  # three frames, read back to back
        # The fourth read has begun, so the third frame is stored: no clock involved.
        wait_until(lambda: camera.reads == 4)
        image = source.frame()
        assert image.shape == (480, 640, 3)
        assert (image == 3).all()  # the newest, the first two superseded
        assert (
            source.frame() is image
        )  # no new frame: the same conversion, served again
    finally:
        camera.stepping.release(100)
        source.stop()


def test_no_frame_before_the_first_one_or_once_the_newest_is_stale(camera):
    camera.blocked.clear()
    source = Webcam(0, camera.open, frame_timeout_s=0.2)
    source.start()
    try:
        time.sleep(0.05)
        with pytest.raises(NoFrame):
            source.frame()
        camera.blocked.set()
        wait_until(lambda: has_frame(source))
        camera.blocked.clear()  # the camera hangs in `read`
        wait_until(lambda: not has_frame(source))
    finally:
        camera.blocked.set()
        source.stop()


def test_a_camera_that_does_not_open_is_retried_and_its_failure_said_once(
    camera, linux, caplog
):
    camera.opening = False
    source = Webcam(0, camera.open, retry_s=0.02)
    with caplog.at_level(logging.INFO, logger="naoqi_sim.webcam"):
        source.start()
        wait_until(lambda: camera.opens >= 4)
        camera.opening = True
        wait_until(lambda: has_frame(source))
        source.stop()

    assert [r.getMessage() for r in caplog.records] == [
        "webcam 0: it does not open; retrying every 0.02 s",
        "webcam 0 is live: 1280x720 (FAKE)",
        "webcam 0 is off",
    ]
    assert camera.released == camera.opens


def test_a_camera_that_stops_delivering_is_reopened(camera, linux, caplog):
    source = Webcam(0, camera.open, retry_s=0.02)
    with caplog.at_level(logging.INFO, logger="naoqi_sim.webcam"):
        source.start()
        wait_until(lambda: has_frame(source))
        camera.delivering = False  # unplugged
        wait_until(lambda: camera.opens >= 2)
        camera.delivering = True
        wait_until(lambda: len(caplog.records) >= 4)
        source.stop()

    messages = [r.getMessage() for r in caplog.records]
    assert messages[:4] == [
        "webcam 0 is live: 1280x720 (FAKE)",
        "webcam 0 is off",
        "webcam 0: it stopped delivering frames; retrying every 0.02 s",
        "webcam 0 is live: 1280x720 (FAKE)",
    ]
    # Reads failing on every reopen before it came back were said once, not per attempt.
    assert messages.count("webcam 0: it gives no frame; retrying every 0.02 s") <= 1
    assert camera.released == camera.opens


def test_stop_releases_the_camera_and_does_not_wait_on_a_blocked_read(
    camera, monkeypatch
):
    monkeypatch.setattr(webcam, "JOIN_TIMEOUT_S", 0.2)
    source = Webcam(0, camera.open)
    source.start()
    wait_until(lambda: has_frame(source))
    source.stop()
    assert camera.released == 1

    source.start()  # a stopped webcam starts again
    wait_until(lambda: camera.opens == 2)
    camera.blocked.clear()
    time.sleep(0.05)
    started = time.monotonic()
    source.stop()
    assert time.monotonic() - started < 1.0
    source.stop()  # twice is harmless
    camera.blocked.set()
    wait_until(lambda: camera.released == 2)
