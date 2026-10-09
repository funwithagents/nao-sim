# Live tier shared fixtures.
#
# This tier is NOT collected by the default `uv run pytest` (testpaths = ["tests"]);
# run it explicitly with `uv run pytest tests-e2e`. Mirror any isolation fixture the
# fast tier uses here — tests-e2e/ isn't a package that can import from tests/, so the
# few lines are duplicated rather than shared.
#
# The tests start and stop the stacks themselves: each test runs once per NAOqi version,
# and pytest tears one version's stack down before it brings up the next (both publish 9559).
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import qi
from support import (
    VERSIONS,
    AudioOutputProcess,
    Stack,
    Version,
    connect,
    require_docker,
)


@dataclass
class Nao:
    version: Version
    stack: Stack
    session: qi.Session

    def service(self, name: str):
        return self.session.service(name)


@pytest.fixture(scope="session")
def audio_output() -> Iterator[AudioOutputProcess]:
    process = AudioOutputProcess()
    yield process
    process.close()


@pytest.fixture(scope="session", params=sorted(VERSIONS))
def nao(request, audio_output) -> Iterator[Nao]:
    require_docker()
    stack = Stack(VERSIONS[request.param])
    try:
        stack.up()
        session = connect()
        yield Nao(stack.version, stack, session)
        session.close()
    finally:
        stack.down()
