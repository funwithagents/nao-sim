# Live tier shared fixtures.
#
# This tier is NOT collected by the default `uv run pytest` (testpaths = ["tests"]);
# run it explicitly with `uv run pytest tests-e2e`. Mirror any isolation fixture the
# fast tier uses here — tests-e2e/ isn't a package that can import from tests/, so the
# few lines are duplicated rather than shared.
#
# The tests run the simulated NAO the way any caller does, with a `NaoqiSim`: each test runs
# once per NAOqi version, and pytest stops one version's NaoqiSim before it starts the next
# (both publish 9559). Its audio goes to a MemorySink, so a test asserts on what was played.
import asyncio
import json
import time
import uuid
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

from naoqi_sim import FakeAudioSource, MemorySink, NaoqiSim
from naoqi_sim.config import (
    AudioInputSettings,
    AudioOutputSettings,
    CameraSettings,
    NaoqiSettings,
    NaoqiSimConfig,
    VideoInputSettings,
    ViewerSettings,
)

SCENE = Path(__file__).resolve().parent / "scenes" / "camera-target.xml"

# Runs a test's Python 2.7 inside NAOqi's embedded interpreter, where Choregraphe's boxes run, on a
# thread, and leaves `run()`'s result (or the traceback) as JSON in an ALMemory key.
# (Python 2 refuses `exec` in a nested function, hence _naoqisim_exec at the top.)
_IN_NAOQI = """
def _naoqisim_exec(_body, _ns):
    exec(_body, _ns)
def _naoqisim_test(_body, _key):
    import json, threading, traceback
    from naoqi import ALProxy
    def go():
        ns = {}
        try:
            _naoqisim_exec(_body, ns)
            out = {"ok": ns["run"]()}
        except Exception:
            out = {"error": traceback.format_exc()}
        ALProxy("ALMemory").insertData(_key, json.dumps(out))
    threading.Thread(target=go).start()
_naoqisim_test(%r, %r)
"""


def pytest_configure(config):
    check_audio_setting()


def live_config(version: str, **blocks) -> NaoqiSimConfig:
    """Headless and silent, with the render camera looking at the camera-target scene (a
    red pillar straight ahead) and the fake audio source: what the live tier runs, unless a test
    asks for something else."""
    settings = {
        "naoqi": NaoqiSettings(version=version),  # type: ignore[arg-type]
        "audio_output": AudioOutputSettings(mode="silent"),
        "viewer": ViewerSettings(
            headless=True, scene=str(SCENE), variant="placeholder"
        ),
        "video_input": VideoInputSettings(
            top=CameraSettings(source="render"), bottom=CameraSettings(source="render")
        ),
        "audio_input": AudioInputSettings(source="fake"),
        **blocks,
    }
    return NaoqiSimConfig(**settings)


class Nao:
    """A running simulated NAO of one version, and a qi session to it."""

    def __init__(self, version: Version, runner: asyncio.Runner):
        self.version = version
        self.runner = runner
        self.sink = MemorySink()
        self.sim = NaoqiSim(live_config(version.name), sink=self.sink)
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
        assert self._session is not None, "the NaoqiSim is stopped"
        return self._session

    def service(self, name: str):
        return self.session.service(name)

    @property
    def audio(self) -> FakeAudioSource:
        """The fake audio source: what the robot's microphones hear."""
        return self.sim.fake_audio

    def run_in_naoqi(self, body: str, timeout: float = 60.0):
        """Runs `body` (Python 2.7 defining `run()`) inside NAOqi, as a box would, and returns
        what `run()` returned (JSON-able)."""
        memory = self.service("ALMemory")
        key = "NaoqiSimTest/" + uuid.uuid4().hex
        memory.insertData(key, "")
        error = self.service("ALPythonBridge").eval(_IN_NAOQI % (body, key))
        if error:  # eval answers with the exception it raised
            pytest.fail("in NAOqi:\n" + error)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            raw = memory.getData(key)
            if raw:
                out = json.loads(raw)
                if "error" in out:
                    pytest.fail("in NAOqi:\n" + out["error"])
                return out["ok"]
            time.sleep(0.1)
        pytest.fail(f"no result from NAOqi after {timeout} s")

    def played(self, after: float, timeout: float = 10.0) -> float:
        """Seconds of audio in the first stream that started after `after` (time.monotonic())."""
        return self.sink.wait_for(lambda p: p.started_at >= after, timeout).duration_s

    def played_if_any(self, after: float, settle: float = 1.0) -> float:
        """Like `played`, for a play that was stopped: 0 when no stream started after `after`
        (the stop came before any audio), once `settle` has given a started one time to end."""
        try:
            return self.played(after, settle)
        except TimeoutError:
            return 0.0


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config: pytest.Config) -> None:
    """Run this tier serially, overriding the fast tier's parallel `addopts`: every test shares
    the one naoqi-sim on 9559, which workers would start and stop under one another. This
    conftest loads only when tests-e2e/ is collected, so the fast tier keeps its workers."""
    config.option.numprocesses = 0


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
