"""The simulated world's side in nao-sim: when a config needs nao-viewer, the sim-mode config it
builds (checked by the installed nao-viewer itself), the missing extra, and the window closed by
the user. No viewer process is launched: `NaoViewer` is replaced where a test needs one."""

import logging
import sys
import threading

import nao_viewer
import numpy as np
import pytest

from nao_sim import viewer
from nao_sim.config import (
    ConfigError,
    NaoSimConfig,
    VideoInputSettings,
    ViewerSettings,
)
from nao_sim.errors import MissingExtraError


@pytest.mark.parametrize(
    ("headless", "source", "needed"),
    [
        (False, "none", True),
        (False, "webcam", True),
        (True, "render", True),
        (True, "none", False),
        (True, "webcam", False),
    ],
)
def test_which_configs_need_the_viewer(headless, source, needed):
    config = NaoSimConfig(
        viewer=ViewerSettings(headless=headless),
        video_input=VideoInputSettings(source=source),
    )
    assert viewer.needs_viewer(config) is needed


def test_the_viewer_runs_in_sim_mode_on_nao_sims_naoqi():
    config = viewer.viewer_config(
        ViewerSettings(headless=True, scene="table", variant="placeholder"),
        "tcp://127.0.0.1:9559",
    )

    assert isinstance(config, nao_viewer.NaoViewerConfig)
    assert config.mode == "sim" and config.headless
    assert config.naoqi.url == "tcp://127.0.0.1:9559"
    assert (config.world.scene, config.world.variant) == ("table", "placeholder")
    assert config.ghost is False  # nao-viewer's other fields keep its defaults


def test_an_unknown_scene_is_a_config_error_on_viewer_scene():
    with pytest.raises(ConfigError) as info:
        viewer.viewer_config(ViewerSettings(scene="moon"), "tcp://127.0.0.1:9559")
    assert info.value.key == "viewer.scene"
    assert "moon" in str(info.value)


def test_without_the_extra_the_error_names_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "nao_viewer", None)  # makes the import fail
    with pytest.raises(MissingExtraError, match=r"nao-sim\[viewer\]"):
        viewer.viewer_config(ViewerSettings(), "tcp://127.0.0.1:9559")


class FakeNaoViewer:
    """A viewer whose window the test closes, as a user would."""

    def __init__(self, config):
        self.config = config
        self.exited = threading.Event()
        self.running = False

    def launch(self):
        self.running = True

    def wait(self, timeout=None):
        return self.exited.wait(timeout)

    def camera_frame(self, camera, width, height):
        if not self.running:
            raise nao_viewer.ViewerClosed("the viewer process has exited")
        image = np.zeros((height, width, 3), np.uint8)
        image[..., 0] = 1 if camera == "top" else 2
        return nao_viewer.CameraFrame(image, camera, pose_seq=1, pose_age=0.01)

    def close(self):
        self.running = False
        self.exited.set()


@pytest.fixture
def fake_viewer(monkeypatch):
    made: list[FakeNaoViewer] = []

    def make(config):
        made.append(FakeNaoViewer(config))
        return made[-1]

    monkeypatch.setattr(nao_viewer, "NaoViewer", make)
    return made


def test_a_window_closed_by_the_user_is_logged_once(fake_viewer, caplog):
    world = viewer.SimWorld("config")
    world.launch()
    assert world.running

    with caplog.at_level(logging.WARNING, logger="nao_sim.viewer"):
        fake_viewer[0].exited.set()  # the user closes the window
        assert world._watcher is not None
        world._watcher.join(timeout=2)

    assert [r.getMessage() for r in caplog.records] == [
        "the sim window was closed: the robot is still running (Ctrl-C to stop it)"
    ]


def test_closing_it_ourselves_logs_nothing(fake_viewer, caplog):
    world = viewer.SimWorld("config")
    world.launch()
    with caplog.at_level(logging.WARNING, logger="nao_sim.viewer"):
        world.close()
    assert not world.running
    assert caplog.records == []


def test_camera_frames_come_from_the_viewer_until_it_is_closed(fake_viewer):
    world = viewer.SimWorld("config")
    world.launch()

    frame = world.camera_frame("top", 640, 480)
    assert frame.shape == (480, 640, 3) and frame[0, 0, 0] == 1

    fake_viewer[0].close()  # the user closes the window
    with pytest.raises(viewer.WorldClosed):
        world.camera_frame("top", 640, 480)
