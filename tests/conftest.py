# Fast tier shared fixtures.
#
# If the package has process-global or singleton state (a module-level registry,
# a cached client, a configured logger), add an `autouse=True` fixture here that
# resets it before and after each test so state can't leak between tests. Keep
# this tier deterministic and network-free — anything that needs a running NAOqi
# belongs in tests-e2e/ instead.
import functools
import sys
import threading
import time
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


@functools.cache
def wake_lateness() -> float:
    """How late this machine wakes a thread from a short timed wait, at worst over 200 waits
    (seconds): about 1 ms on a desktop, more on a busy CI virtual machine."""
    event, worst = threading.Event(), 0.0
    for _ in range(200):
        t0 = time.monotonic()
        event.wait(0.005)
        worst = max(worst, time.monotonic() - t0 - 0.005)
    return worst


def pytest_report_header() -> str:
    return (
        f"timed waits wake up to {wake_lateness() * 1000:.1f} ms late on this machine"
    )


@pytest.fixture
def lateness() -> float:
    """This machine's wake-up lateness, which a test bounding a reaction time adds to its
    bound: the bound stays the spec's on a quiet machine (specs/testing/testing.md)."""
    return wake_lateness()
