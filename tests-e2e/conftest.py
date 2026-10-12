# Live tier shared fixtures.
#
# This tier is NOT collected by the default `uv run pytest` (testpaths = ["tests"]);
# run it explicitly with `uv run pytest tests-e2e`. Mirror any isolation fixture the
# fast tier uses here — tests-e2e/ isn't a package that can import from tests/, so the
# few lines are duplicated rather than shared.
#
# The tests run the simulated NAO the way any caller does, with a `NaoSim`: each test runs
# once per NAOqi version, and pytest stops one version's NaoSim before it starts the next
# (both publish 9559). Its audio goes to a MemorySink, so a test asserts on what was played.
import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
import qi
from support import (
    VERSIONS,
    Container,
    Version,
    check_audio_setting,
    connect,
    e2e_versions,
    ensure_images,
    require_docker,
    require_free_ports,
)

from nao_sim import FakeAudioSource, MemorySink, NaoSim
from nao_sim.config import (
    AudioInputSettings,
    AudioOutputSettings,
    NaoqiSettings,
    NaoSimConfig,
    VideoInputSettings,
    ViewerSettings,
)

SCENE = Path(__file__).resolve().parent / "scenes" / "camera-target.xml"


def pytest_configure(config):
    check_audio_setting()


def live_config(version: str, **blocks) -> NaoSimConfig:
    """Headless and silent, with the render camera looking at the camera-target scene (a
    red pillar straight ahead) and the fake audio source: what the live tier runs, unless a test
    asks for something else."""
    settings = {
        "naoqi": NaoqiSettings(version=version),  # type: ignore[arg-type]
        "audio_output": AudioOutputSettings(mode="silent"),
        "viewer": ViewerSettings(
            headless=True, scene=str(SCENE), variant="placeholder"
        ),
        "video_input": VideoInputSettings(source="render"),
        "audio_input": AudioInputSettings(source="fake"),
        **blocks,
    }
    return NaoSimConfig(**settings)


class Nao:
    """A running simulated NAO of one version, and a qi session to it."""

    def __init__(self, version: Version, runner: asyncio.Runner):
        self.version = version
        self.runner = runner
        self.sink = MemorySink()
        self.sim = NaoSim(live_config(version.name), sink=self.sink)
        self.container = Container(version)
        self._session: qi.Session | None = None

    def start(self) -> None:
        self.runner.run(self.sim.start())
        self._session = connect(self.sim.url)

    def stop(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        self.runner.run(self.sim.stop())

    def restart(self) -> None:
        self.stop()
        self.start()

    @property
    def session(self) -> qi.Session:
        assert self._session is not None, "the NaoSim is stopped"
        return self._session

    def service(self, name: str):
        return self.session.service(name)

    @property
    def audio(self) -> FakeAudioSource:
        """The fake audio source: what the robot's microphones hear."""
        return self.sim.fake_audio

    def played(self, after: float, timeout: float = 10.0) -> float:
        """Seconds of audio in the first stream that started after `after` (time.monotonic())."""
        return self.sink.wait_for(lambda p: p.started_at >= after, timeout).duration_s


@pytest.fixture(scope="session", params=e2e_versions())
def nao(request) -> Iterator[Nao]:
    require_docker()
    version = VERSIONS[request.param]
    ensure_images(version)
    require_free_ports()
    with asyncio.Runner() as runner:
        nao = Nao(version, runner)
        try:
            nao.start()
            yield nao
        finally:
            nao.stop()
