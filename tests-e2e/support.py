"""Helpers for the opt-in live tier: the nao-sim stacks and the host sound card.

The live tests drive their own stack: they build and start a version's containers with
`docker compose`, wait for the entrypoint's ready line, and take them down afterwards. A
version whose suite (or image) is missing, or a machine without Docker, skips, never fails.
"""

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

from nao_sim import suite

REPO = Path(__file__).resolve().parent.parent
COMPOSE = REPO / "docker" / "compose.yaml"
VENDOR = REPO / "docker" / "vendor"
URL = "tcp://127.0.0.1:9559"
SOUNDCARD_PORT = 9562


@dataclass(frozen=True)
class Version:
    name: str
    service: str  # compose service
    container: str
    image: str
    profile: str | None
    tts_log: (
        str  # JSON-lines log of the ALTextToSpeech replacement, inside the container
    )
    implementation: str  # what ALTextToSpeech.whoami() names


VERSIONS = {
    "2.1": Version(
        "2.1",
        "naoqi",
        "nao-sim-naoqi",
        "nao-sim/naoqi:2.1.4.13",
        None,
        "/home/nao/tts_almodule.jsonl",
        "nao-sim ALModule replacement",
    ),
    "2.8": Version(
        "2.8",
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


def _run(*args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
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
        profile = ["--profile", version.profile] if version.profile else []
        self._compose = ["docker", "compose", "-f", str(COMPOSE), *profile]

    def up(self, timeout: float = 240) -> None:
        v = self.version
        vendored = suite.VERSIONS[v.name]
        folder = VENDOR / v.name
        build = (folder / vendored.suite.filename).exists() and (
            folder / suite.PACKAGE
        ).exists()
        if not build and _run("docker", "image", "inspect", v.image).returncode != 0:
            pytest.skip(
                f"NAOqi {v.name}: no suite and package in docker/vendor/{v.name}/ "
                f"(uv run nao-sim-fetch-suite {v.name}) and no {v.image} image"
            )
        if _port_taken(9559):
            pytest.fail("127.0.0.1:9559 is taken: stop the running nao-sim stack first")
        since = str(int(time.time()))
        cmd = [
            *self._compose,
            "up",
            "-d",
            *(["--build"] if build else []),
            "tts",
            v.service,
        ]
        res = _run(*cmd, timeout=1800)
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


class SoundCardProcess:
    """`nao-sim-soundcard --silent` on the port the tts container streams to.

    Its stdout events (`start`, `end` with `played_s`, ...) say what was actually played."""

    def __init__(self, port: int = SOUNDCARD_PORT):
        if _port_taken(port):
            pytest.fail(
                f"port {port} is taken: stop the running nao-sim-soundcard first"
            )
        self.events: list[dict] = []
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "nao_sim.soundcard",
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
        raise AssertionError(f"no matching sound card event; got {self.events[after:]}")

    def played(self, after: int, timeout: float = 5.0) -> float:
        """Seconds of audio played by the first stream that ends after `after`."""
        return self.wait_for(lambda e: e["event"] == "end", after, timeout)["played_s"]

    def close(self) -> None:
        self._proc.terminate()
        self._proc.wait(5)
