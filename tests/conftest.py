# Fast tier shared fixtures.
#
# If the package has process-global or singleton state (a module-level registry,
# a cached client, a configured logger), add an `autouse=True` fixture here that
# resets it before and after each test so state can't leak between tests. Keep
# this tier deterministic and network-free — anything that needs a running NAOqi
# belongs in tests-e2e/ instead.
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fake_docker import docker  # noqa: F401  (the fixture, for every test file)

# The container code is not a package: the NAOqi override modules (docker/naoqi/services/<service>/,
# Python 2.7 code kept importable under Python 3) and the speech engine (docker/tts-engine) are
# imported by name, as inside NAOqi, where the modules sit in one flat folder.
_DOCKER = Path(__file__).resolve().parent.parent / "docker"
for _dir in [
    *sorted((_DOCKER / "naoqi" / "services").iterdir()),
    _DOCKER / "tts-engine",
]:
    sys.path.insert(0, str(_dir))


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # The container code (the NAOqi modules' cores, the entrypoints, the speech engine) runs in
    # Linux containers only; its tests need POSIX tools (bash, executable stand-ins) and test
    # nothing about a Windows host, so they skip there (specs/testing/testing.md, "Platforms").
    if sys.platform != "win32":
        return
    skip = pytest.mark.skip(
        reason="code that runs in the Linux containers: tested on Linux and macOS"
    )
    for item in items:
        if item.get_closest_marker("container_code"):
            item.add_marker(skip)


class _Lateness:
    """How late this machine wakes a thread from a short timed wait: the worst seen so far by a
    sampler thread doing 5 ms waits for the whole session, so it lives through the same load as
    the tests (other xdist workers included). About 1 ms on a quiet desktop, tens of ms on a busy
    CI virtual machine."""

    def __init__(self) -> None:
        self.worst = 0.0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._sample, daemon=True)
            self._thread.start()

    def _sample(self) -> None:
        event = threading.Event()
        while True:
            t0 = time.monotonic()
            event.wait(0.005)
            self.worst = max(self.worst, time.monotonic() - t0 - 0.005)


_LATENESS = _Lateness()


def pytest_configure() -> None:
    _LATENESS.start()


def pytest_report_header() -> str:
    time.sleep(1.0)  # a first figure for the header
    return f"timed waits woke up to {_LATENESS.worst * 1000:.1f} ms late in the first second"


@pytest.fixture
def lateness() -> Callable[[], float]:
    """This machine's wake-up lateness so far, read at the assertion: a test bounding a reaction
    time adds it to its bound, which stays the spec's on a quiet machine
    (specs/testing/testing.md, "Platforms")."""
    return lambda: _LATENESS.worst
