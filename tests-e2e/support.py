"""Helpers for the opt-in live tier: the nao-sim stacks and the host speaker.

The live tests drive their own stack: they build and verify a version's images with
`fetch_and_build_images`, start its containers with `docker compose`, wait for the entrypoint's
ready line, and take them down afterwards. A version whose suite (or image) is missing, or a
machine without Docker, skips, never fails.
"""

import asyncio
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import qi

from nao_sim import docker_images, suite
from nao_sim.errors import NaoSimError

REPO = Path(__file__).resolve().parent.parent
COMPOSE = REPO / "docker" / "compose.yaml"
VENDOR = REPO / "docker" / "vendor"
URL = "tcp://127.0.0.1:9559"
SPEAKER_PORT = 9562


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


class Stack:
    """One version's containers (`tts` + NAOqi), brought up and down with docker compose."""

    def __init__(self, version: Version):
        self.version = version
        self._compose = [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "--profile",
            version.profile,
        ]

    def up(self, timeout: float = 240) -> None:
        v = self.version
        vendored = suite.VERSIONS[v.name]
        folder = VENDOR / v.name
        if _port_taken(9559):
            pytest.fail("127.0.0.1:9559 is taken: stop the running nao-sim stack first")
        if (folder / vendored.suite.filename).exists() and (
            folder / suite.PACKAGE
        ).exists():
            # The one slow step, as a user runs it: build from the checkout and verify.
            try:
                asyncio.run(docker_images.fetch_and_build_images([v.name]))
            except NaoSimError as e:
                pytest.fail(f"fetch-and-build-images failed for {v.name}: {e}")
        else:
            try:
                docker_images.check_images(v.name)
            except NaoSimError as e:
                pytest.skip(
                    f"NAOqi {v.name}: no suite and package in docker/vendor/{v.name}/ "
                    f"and no usable images ({e})"
                )
        since = str(int(time.time()))
        res = _run(*self._compose, "up", "-d", "tts", v.service, timeout=600)
        if res.returncode != 0:
            pytest.fail(f"docker compose up failed for {v.name}:\n{res.stderr[-3000:]}")
        end = time.time() + timeout
        while "[entrypoint] nao-sim ready" not in self.logs(since):
            if time.time() > end:
                pytest.fail(
                    f"NAOqi {v.name} not ready after {timeout}s:\n{self.logs(since)[-3000:]}"
                )
            if (
                _run(
                    "docker", "inspect", "-f", "{{.State.Running}}", v.container
                ).stdout.strip()
                != "true"
            ):
                pytest.fail(
                    f"NAOqi {v.name} container exited:\n{self.logs(since)[-3000:]}"
                )
            time.sleep(1)

    def down(self) -> None:
        """`docker compose down`: removes the containers, keeps the package store volume."""
        _run(*self._compose, "down", timeout=300)

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


class SpeakerProcess:
    """`nao-sim-speaker --silent` on the port the tts container streams to.

    Its stdout events (`start`, `end` with `played_s`, ...) say what was actually played."""

    def __init__(self, port: int = SPEAKER_PORT):
        if _port_taken(port):
            pytest.fail(f"port {port} is taken: stop the running nao-sim-speaker first")
        self.events: list[dict] = []
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "nao_sim.speaker",
                "--silent",
                "--listen",
                f"0.0.0.0:{port}",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        threading.Thread(target=self._read, daemon=True).start()
        self.wait_for(lambda e: e["event"] == "listening", after=0)

    def _read(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            if line.startswith("{"):
                self.events.append(json.loads(line))

    def mark(self) -> int:
        """Position in the event stream, to look only at what happens after it."""
        return len(self.events)

    def wait_for(self, pred, after: int, timeout: float = 5.0) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            for e in self.events[after:]:
                if pred(e):
                    return e
            time.sleep(0.05)
        raise AssertionError(f"no matching speaker event; got {self.events[after:]}")

    def played(self, after: int, timeout: float = 5.0) -> float:
        """Seconds of audio played by the first stream that ends after `after`."""
        return self.wait_for(lambda e: e["event"] == "end", after, timeout)["played_s"]

    def close(self) -> None:
        self._proc.terminate()
        self._proc.wait(5)
