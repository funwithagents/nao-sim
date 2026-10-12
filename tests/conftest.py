# Fast tier shared fixtures.
#
# If the package has process-global or singleton state (a module-level registry,
# a cached client, a configured logger), add an `autouse=True` fixture here that
# resets it before and after each test so state can't leak between tests. Keep
# this tier deterministic and network-free — anything that needs a running NAOqi
# belongs in tests-e2e/ instead.
import sys
from pathlib import Path

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
