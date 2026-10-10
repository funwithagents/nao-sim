"""The render camera on each NAOqi version, as a vision client sees it: it subscribes to
`ALVideoDevice` and reads frames with `getImageRemote`, which nao-viewer rendered and the video
input injected (the live tier runs it: headless viewer, placeholder variant, 15 fps)."""

import math
import time

import numpy as np
import pytest

TOP, BOTTOM = 0, 1
QVGA, VGA = 1, 2
RGB, BGR = 11, 13
FPS = 15  # VideoInputSettings' default, which the live tier keeps


@pytest.fixture
def camera(nao):
    """Subscribes to a camera like a client, and unsubscribes after the test."""
    video = nao.service("ALVideoDevice")
    handles: list[str] = []

    def subscribe(index=TOP, resolution=QVGA, colorspace=RGB):
        handles.append(
            video.subscribeCamera("nao_sim_e2e", index, resolution, colorspace, 30)
        )
        return handles[-1]

    yield video, subscribe
    for handle in handles:
        video.unsubscribe(handle)


def read(video, handle) -> tuple[np.ndarray, float]:
    """The subscriber's current frame and its timestamp."""
    reply = video.getImageRemote(handle)
    video.releaseImage(handle)
    width, height, layers = reply[0], reply[1], reply[2]
    image = np.frombuffer(bytes(reply[6]), np.uint8).reshape(height, width, layers)
    return image, reply[4] + reply[5] / 1e6


def next_frame(video, handle, after: float, timeout: float = 2.0) -> np.ndarray:
    """The first frame stamped after `after`."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        image, stamp = read(video, handle)
        if stamp > after:
            return image
        time.sleep(0.01)
    pytest.fail("no new frame")


def test_the_robot_says_its_camera_is_the_render(nao):
    assert nao.service("ALMemory").getData("NaoSim/Camera/Source") == "render"


def test_a_client_reads_rendered_frames_at_the_configured_rate(camera):
    """Never faster than `fps`, and frames keep coming. Not exactly `fps`: a CI runner renders
    in software (Mesa, no GPU) and reaches about 9 VGA frames per second on 2.8, where a
    Mac holds 30."""
    video, subscribe = camera
    handle = subscribe(resolution=QVGA)

    image, stamp = read(video, handle)
    stamps = {stamp}
    seconds = 3.0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        image, stamp = read(video, handle)
        stamps.add(stamp)
        time.sleep(0.005)
    rate = (len(stamps) - 1) / seconds

    # NAOqi scaled the VGA frame to the subscriber's resolution.
    assert image.shape == (240, 320, 3)
    assert image.std() > 1  # a render of the scene, not a flat placeholder
    assert 4 <= rate <= FPS + 1.5, f"{rate:.1f} frames per second"


def test_each_subscriber_gets_its_own_colorspace(camera):
    video, subscribe = camera
    rgb, bgr = subscribe(colorspace=RGB), subscribe(resolution=QVGA, colorspace=BGR)

    for _ in range(
        20
    ):  # the two reads can straddle an injection: retry until they match
        rgb_image, rgb_stamp = read(video, rgb)
        bgr_image, bgr_stamp = read(video, bgr)
        if rgb_stamp == bgr_stamp:
            break
    else:
        pytest.fail("never read both subscribers on the same frame")

    diff = np.abs(rgb_image.astype(int) - bgr_image[..., ::-1].astype(int))
    assert diff.max() <= 2


TARGET = (
    1.5,
    0.0,
)  # the camera-target scene's red pillar on the floor, world frame (m)
HALF_FOV = math.radians(60.97) / 2  # a NAO head camera's horizontal field of view
WORLD = 1  # ALMotion's FRAME_WORLD


def target_columns(image: np.ndarray) -> np.ndarray:
    """The columns of the red pillar's pixels in an RGB image."""
    red = (image[..., 0] > 150) & (image[..., 1] < 80) & (image[..., 2] < 80)
    return np.nonzero(red)[1]


def bearing_to_target(motion) -> float:
    """The pillar's direction from CameraTop, relative to where it looks (positive: left)."""
    x, y, _, _, _, heading = motion.getPosition("CameraTop", WORLD, True)
    return math.atan2(TARGET[1] - y, TARGET[0] - x) - heading


def expected_column(bearing: float, width: int) -> float | None:
    """Where a pinhole camera sees the pillar's centre at `bearing`, or None when the
    pillar is out of the field of view."""
    if abs(bearing) > HALF_FOV + 0.1:  # the pillar's half-width: 0.07 rad at 1.5 m
        return None
    return width / 2 * (1 - math.tan(bearing) / math.tan(HALF_FOV))


def look(motion, yaw: float) -> None:
    motion.angleInterpolation(["HeadYaw", "HeadPitch"], [yaw, 0.0], 0.8, True)
    time.sleep(0.5)  # the viewer follows the pose at 50 Hz


def test_the_camera_sees_what_the_head_faces(nao, camera):
    """The red pillar where the camera's pose says it is, as the head turns left and right
    of it, and gone once the head turns away. The head aims relative to the pillar, not to
    the scene: NAOqi's world pose of the robot, which the viewer renders, starts about
    0.13 rad off and drifts with gestures (specs/host/viewer.md, "In the live tier and CI")."""
    video, subscribe = camera
    motion = nao.service("ALMotion")
    handle = subscribe(resolution=QVGA)
    width = 320
    motion.setStiffnesses("Head", 1.0)
    try:
        look(motion, 0.0)
        aim = bearing_to_target(
            motion
        )  # the HeadYaw that faces the pillar, near enough
        for offset in (0.0, 0.25, -0.25, 1.2, -1.2):
            look(motion, aim + offset)
            seen = target_columns(
                next_frame(video, handle, after=read(video, handle)[1])
            )
            expected = expected_column(bearing_to_target(motion), width)
            if expected is None:
                assert seen.size == 0, (
                    f"{offset:+} rad off: the pillar should be out of view"
                )
            else:
                assert seen.size > 100, f"{offset:+} rad off: the pillar is not in view"
                assert abs(seen.mean() - expected) < 15, f"{offset:+} rad off"
    finally:
        motion.angleInterpolation("HeadYaw", 0.0, 0.5, True)


def test_the_bottom_camera_gets_no_frames(camera):
    video, subscribe = camera
    handle = subscribe(index=BOTTOM, resolution=QVGA)

    image, stamp = read(video, handle)
    time.sleep(0.5)
    _, later = read(video, handle)

    # NAOqi's placeholder for a camera never fed (video-input.md, "As measured").
    assert image.shape == (240, 320, 3)
    assert len(np.unique(image.reshape(-1, 3), axis=0)) <= 2
    assert later == stamp
