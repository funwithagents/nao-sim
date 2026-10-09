"""Helpers for the opt-in live tier.

The live tests drive their own simulated NAO: they build and verify a version's images with
`fetch_and_build_images` when `check_images` finds them missing or outdated (an edit under
docker/ included), then run it with a `NaoSim` (tests-e2e/conftest.py). A version whose suite
(or image) is missing, or a machine without Docker, skips, never fails. `Container` reaches into
the running NAOqi container for what qi does not show (the replacement's log, files, the image).
"""

import asyncio
import json
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import qi

from nao_sim import docker_images, suite
from nao_sim.errors import ImagesMissingError, ImagesOutdatedError, NaoSimError

REPO = Path(__file__).resolve().parent.parent
COMPOSE = REPO / "docker" / "compose.yaml"
VENDOR = REPO / "docker" / "vendor"
URL = "tcp://127.0.0.1:9559"
AUDIO_OUTPUT_PORT = 9562


@dataclass(frozen=True)
class Version:
    name: str
    naoqi_version: str  # what NaoSim.getNaoqiVersion() reports
    service: str  # compose service
    container: str
    image: str
    profile: str  # compose profile
    tts_log: (
        str  # JSON-lines log of the ALTextToSpeech replacement, inside the container
    )
    implementation: str  # what ALTextToSpeech.whoami() names


VERSIONS = {
    "2.1": Version(
        "2.1",
        "2.1.4.13",
        "naoqi21",
        "nao-sim-naoqi21",
        "nao-sim/naoqi:2.1.4.13",
        "2.1",
        "/home/nao/tts_almodule.jsonl",
        "nao-sim ALModule replacement",
    ),
    "2.8": Version(
        "2.8",
        "2.8.7.4",
        "naoqi28",
        "nao-sim-naoqi28",
        "nao-sim/naoqi:2.8.7.4",
        "2.8",
        "/home/nao/tts_qiservice.jsonl",
        "nao-sim qi.Session replacement",
    ),
}


def connect(url: str = URL, attempts: int = 5) -> qi.Session:
    """Connect a qi.Session, retrying: libqi 3 fails about one connect in three against 2.1."""
    error: Exception | None = None
    for _ in range(attempts):
        session = qi.Session()
        try:
            session.connect(url)
            return session
        except RuntimeError as e:
            error = e
            time.sleep(0.5)
    raise RuntimeError(f"could not connect to {url} in {attempts} attempts: {error}")


def _run(
    *args: str, timeout: float = 120, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False, env=env
    )


def _port_taken(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def require_docker() -> None:
    if shutil.which("docker") is None or _run("docker", "info").returncode != 0:
        pytest.skip("Docker is not available")


def ensure_images(version: Version) -> None:
    """Use the version's images if current; build and verify them from the checkout if not,
    when its vendor files are there; skip otherwise."""
    vendored = suite.VERSIONS[version.name]
    folder = VENDOR / version.name
    try:
        # Current images (this nao-sim, these recipes, verified) are used as they are.
        docker_images.check_images(version.name)
    except (ImagesMissingError, ImagesOutdatedError) as stale:
        if not (
            (folder / vendored.suite.filename).exists()
            and (folder / suite.PACKAGE).exists()
        ):
            pytest.skip(
                f"NAOqi {version.name}: no suite and package in docker/vendor/{version.name}/ "
                f"and no usable images ({stale})"
            )
        # The one slow step, as a user runs it: build from the checkout and verify.
        try:
            asyncio.run(docker_images.fetch_and_build_images([version.name]))
        except NaoSimError as e:
            pytest.fail(f"fetch-and-build-images failed for {version.name}: {e}")


def require_free_ports() -> None:
    for port, what in ((9559, "NAOqi"), (AUDIO_OUTPUT_PORT, "audio output")):
        if _port_taken(port):
            pytest.fail(
                f"port {port} ({what}) is taken: stop the running nao-sim (or the stack "
                "started by hand) first"
            )


class Container:
    """The running NAOqi container of a version, reached through Docker."""

    def __init__(self, version: Version):
        self.version = version

    def copy_in(self, src: Path, dest: str) -> None:
        res = _run("docker", "cp", str(src), f"{self.version.container}:{dest}")
        assert res.returncode == 0, res.stderr

    def image_env(self) -> dict[str, str]:
        """The environment baked into the version's image (`NAO_SIM_VERSION`, ...)."""
        res = _run(
            "docker",
            "image",
            "inspect",
            "-f",
            "{{range .Config.Env}}{{println .}}{{end}}",
            self.version.image,
        )
        assert res.returncode == 0, res.stderr
        return dict(
            line.split("=", 1) for line in res.stdout.splitlines() if "=" in line
        )

    def health(self) -> str:
        """Docker's health status of the NAOqi container: starting, healthy or unhealthy."""
        res = _run(
            "docker",
            "inspect",
            "-f",
            "{{.State.Health.Status}}",
            self.version.container,
        )
        return res.stdout.strip()

    def wait_healthy(self, timeout: float = 30) -> str:
        end = time.time() + timeout
        status = self.health()
        while status != "healthy" and time.time() < end:
            time.sleep(1)
            status = self.health()
        return status

    def logs(self, since: str) -> str:
        res = _run("docker", "logs", "--since", since, self.version.container)
        return res.stdout + res.stderr

    def tts_log(self) -> list[dict]:
        """Entries of the ALTextToSpeech replacement's JSON-lines log."""
        res = _run(
            "docker", "exec", self.version.container, "cat", self.version.tts_log
        )
        return [
            json.loads(line) for line in res.stdout.splitlines() if line.startswith("{")
        ]
