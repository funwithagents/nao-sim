"""The video input: the robot's head camera, fed into `ALVideoDevice` (specs/host/video-input.md).

An ordinary qi client: at `fps` frames per second it takes a 640x480 RGB frame from its source
(the viewer's render of the top camera) and injects it with the public `putImage` into
`CameraTop`, whoever subscribes. NAOqi serves every subscriber from that one frame, in the
subscriber's own resolution and colorspace. Rendering and injecting run on separate threads,
the newest frame winning, so a `putImage` never makes the next render miss the viewer's tick.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

from nao_sim import stack
from nao_sim.viewer import SimWorld, WorldClosed

log = logging.getLogger(__name__)

# VGA: the largest size both versions' putImage accepts (2.8 refuses anything above it).
WIDTH, HEIGHT = 640, 480
TOP_CAMERA = 0
SOURCE_KEY = "NaoSim/Camera/Source"
# How long stop() waits for each thread: a source blocked longer is left behind (daemon).
JOIN_TIMEOUT_S = 1.0


class FrameSource(Protocol):
    """Where the frames come from; `name` is what `NaoSim/Camera/Source` says."""

    name: str

    def frame(self) -> np.ndarray:
        """A (480, 640, 3) uint8 RGB image; `WorldClosed` when there will be no more."""
        ...


class RenderSource:
    """The top camera as nao-viewer renders it, at the robot's current pose."""

    name = "render"

    def __init__(self, world: SimWorld):
        self._world = world

    def frame(self) -> np.ndarray:
        return self._world.camera_frame("top", WIDTH, HEIGHT)


class VideoInput:
    """Injects `source`'s frames into `CameraTop` at `fps`, from `start()` to `stop()`."""

    def __init__(
        self,
        source: FrameSource,
        fps: int,
        connect: Callable[[], Any] | None = None,
    ):
        self._source = source
        self._period = 1.0 / fps
        self._connect = connect or (lambda: stack.connect())  # a qi session, retried
        self._session: Any = None
        self._video: Any = None
        self._memory: Any = None
        self._stopping = threading.Event()
        self._ready = threading.Condition()
        self._frame: np.ndarray | None = None
        self._failing: set[str] = set()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self._session = self._connect()
        self._video = self._session.service("ALVideoDevice")
        self._memory = self._session.service("ALMemory")
        self._publish(self._source.name)
        for name, target in (("render", self._render), ("inject", self._inject)):
            thread = threading.Thread(
                target=target, name=f"nao-sim-video-{name}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        """Stop both threads, write `none` back and close the session. Idempotent."""
        self._halt()
        for thread in self._threads:
            thread.join(timeout=JOIN_TIMEOUT_S)
        self._threads = []
        if self._session is not None:
            self._publish("none")
            self._session.close()
            self._session = None

    def _halt(self) -> None:
        with self._ready:
            self._stopping.set()
            self._ready.notify_all()

    def _render(self) -> None:
        """Takes a frame per slot of a fixed schedule; a missed slot is skipped, not caught up."""
        due = time.monotonic()
        while not self._stopping.wait(max(0.0, due - time.monotonic())):
            try:
                image = self._source.frame()
            except WorldClosed:
                if not self._stopping.is_set():
                    log.warning(
                        "the viewer is closed: the robot's camera gets no more frames"
                    )
                    self._halt()
                    self._publish("none")
                return
            except Exception as e:  # noqa: BLE001 (a bad frame must not end the device)
                self._failed("render", e)
            else:
                self._succeeded("render")
                with self._ready:
                    self._frame = image
                    self._ready.notify_all()
            due += self._period
            late = time.monotonic() - due
            if late >= 0:
                due += (int(late / self._period) + 1) * self._period

    def _inject(self) -> None:
        while True:
            with self._ready:
                while self._frame is None and not self._stopping.is_set():
                    self._ready.wait()
                image = self._frame
                if self._stopping.is_set() or image is None:
                    return
                self._frame = None
            try:
                accepted = self._video.putImage(
                    TOP_CAMERA, WIDTH, HEIGHT, image.tobytes()
                )
            except Exception as e:  # noqa: BLE001 (NAOqi may be busy; try the next frame)
                self._failed("putImage", e)
            else:
                if accepted:
                    self._succeeded("putImage")
                else:
                    self._failed("putImage", "NAOqi refused the frame")

    def _failed(self, stage: str, error: object) -> None:
        """Logs the first failure of a run, then stays quiet until the stage succeeds again."""
        if stage not in self._failing:
            self._failing.add(stage)
            log.warning("video input: %s failed: %s", stage, error)

    def _succeeded(self, stage: str) -> None:
        if stage in self._failing:
            self._failing.discard(stage)
            log.info("video input: %s works again", stage)

    def _publish(self, value: str) -> None:
        try:
            self._memory.insertData(SOURCE_KEY, value)
        except Exception as e:  # noqa: BLE001 (best effort: NAOqi may be stopping too)
            log.debug("video input: could not write %s = %s: %s", SOURCE_KEY, value, e)
