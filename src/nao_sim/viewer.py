"""The simulated world: nao-viewer's sim mode, driven through its public API (specs/host/viewer.md).

`nao_viewer` comes with the `nao-sim[viewer]` extra and is imported only when a config needs
it. Closing the window stops the viewer only: the robot keeps running, and this module logs it.
"""

import logging
import threading
from typing import Any

from nao_sim.config import ConfigError, NaoSimConfig, ViewerSettings
from nao_sim.errors import MissingExtraError

log = logging.getLogger(__name__)


class WorldClosed(Exception):
    """The viewer is gone (its window closed by the user): it renders no more frames."""


def needs_viewer(config: NaoSimConfig) -> bool:
    """A window, or a headless viewer for the render camera (viewer.md, "Which viewer runs")."""
    return not config.viewer.headless or config.video_input.source == "render"


def viewer_config(settings: ViewerSettings, url: str) -> Any:
    """The `NaoViewerConfig` of nao-viewer's sim mode for nao-sim's NAOqi at `url`, checked by
    nao-viewer itself (an unknown bundled scene is a `ConfigError` on `viewer.scene`)."""
    try:
        import nao_viewer
    except ImportError:
        raise MissingExtraError(
            "this config needs the viewer (a window, or the render camera): "
            "depend on `nao-sim[viewer]` instead of `nao-sim`, or set viewer.headless to true"
        ) from None
    try:
        return nao_viewer.NaoViewerConfig(
            mode="sim",
            headless=settings.headless,
            naoqi=nao_viewer.NaoqiSettings(url=url),
            world=nao_viewer.WorldSettings(
                scene=settings.scene,
                variant=settings.variant,  # type: ignore[arg-type]  # the same three variants
            ),
        )
    except nao_viewer.ConfigError as e:
        key = getattr(e, "key", None)
        raise ConfigError(
            str(getattr(e, "message", e)), f"viewer.{key or 'scene'}"
        ) from None


class SimWorld:
    """One `NaoViewer` in sim mode, owned by a running `NaoSim`."""

    def __init__(self, config: Any):
        from nao_viewer import NaoViewer

        self._viewer = NaoViewer(config)
        self._closing = False
        self._watcher: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._viewer.running

    def launch(self) -> None:
        """Start the viewer process; returns once it can render (`LaunchError` otherwise)."""
        self._viewer.launch()
        self._watcher = threading.Thread(
            target=self._watch, name="nao-sim-viewer-watch", daemon=True
        )
        self._watcher.start()

    def _watch(self) -> None:
        self._viewer.wait()
        if not self._closing:
            log.warning(
                "the sim window was closed: the robot is still running (Ctrl-C to stop it)"
            )

    def camera_frame(self, camera: str, width: int, height: int) -> Any:
        """What a head camera (`top`, `bottom`) sees: a (height, width, 3) uint8 RGB array.
        Raises `WorldClosed` once the viewer is gone."""
        from nao_viewer import ViewerClosed

        try:
            return self._viewer.camera_frame(camera, width, height).image  # type: ignore[arg-type]
        except ViewerClosed:
            raise WorldClosed("the viewer is closed") from None

    def close(self) -> None:
        self._closing = True
        self._viewer.close()
        if self._watcher is not None:
            self._watcher.join(timeout=5)
