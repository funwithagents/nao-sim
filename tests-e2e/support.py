"""Helpers for the opt-in live tier.

The live tests drive their own simulated NAO: they build and verify a version's images with
`fetch_and_build_images` when `check_images` finds them missing or outdated (an edit under
docker/ included), then run it with a `NaoSim` (tests-e2e/conftest.py). A version whose suite
(or image) is missing, or a machine without Docker, skips, never fails, unless
`NAO_SIM_E2E_VERSION` names the version to run (CI, specs/testing/ci.md): then only that version
runs, and what would skip fails. `Container` reaches into the running NAOqi container for what qi
does not show (the replacement's log, files, the image).
"""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import numpy as np
import pytest
import qi

from nao_sim import docker_images, suite
from nao_sim.errors import ImagesMissingError, ImagesOutdatedError, NaoSimError

REPO = Path(__file__).resolve().parent.parent
COMPOSE = REPO / "docker" / "compose.yaml"
IMAGE_DATA = REPO / "docker" / "image-data"
URL = "tcp://127.0.0.1:9559"
AUDIO_OUTPUT_PORT = 9562
HOST_LINK_PORT = 9563
REQUIRED = os.environ.get("NAO_SIM_E2E_VERSION") or None  # CI: this version must run
# "loopback": the default audio output and input are wired to each other (CI's PulseAudio null
# sink), so the tests that use real sound devices run; without it they skip.
AUDIO = os.environ.get("NAO_SIM_E2E_AUDIO") or None


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


def e2e_versions() -> list[str]:
    """The versions the tier runs: the required one, or every version."""
    if REQUIRED is None:
        return sorted(VERSIONS)
    if REQUIRED not in VERSIONS:
        raise pytest.UsageError(
            f"NAO_SIM_E2E_VERSION={REQUIRED!r}: choose from {', '.join(sorted(VERSIONS))}"
        )
    return [REQUIRED]


def check_audio_setting() -> None:
    if AUDIO not in (None, "loopback"):
        raise pytest.UsageError(
            f"NAO_SIM_E2E_AUDIO={AUDIO!r}: the only value is 'loopback'"
        )


def require_loopback() -> None:
    """Skip unless the default audio devices are declared a loopback; when they are, a missing
    sound system fails instead (CI)."""
    if AUDIO != "loopback":
        pytest.skip(
            "uses the default sound devices: set NAO_SIM_E2E_AUDIO=loopback when they are "
            "wired to each other (a virtual loopback), never your loudspeakers and microphone"
        )
    try:
        import sounddevice as sd

        sd.query_devices(kind="input")
        sd.query_devices(kind="output")
    except Exception as e:  # noqa: BLE001 (PortAudio's errors are not typed)
        pytest.fail(f"NAO_SIM_E2E_AUDIO=loopback but no default sound devices: {e}")


def tone(freq: float, seconds: float, rate: int, amplitude: float = 8000) -> np.ndarray:
    """A sine as int16 samples."""
    t = np.arange(int(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.int16)


def peak_hz(samples: np.ndarray, rate: int) -> float:
    """The strongest frequency in `samples`."""
    x = np.asarray(samples, dtype=np.float64)
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / rate)[np.argmax(spectrum)])


@dataclass
class Chunk:
    """One `processRemote` call, as a client gets it."""

    channels: int
    samples: int
    stamp: list
    buffer: Any  # what libqi handed over: a bytearray, as from a NAO
    arrived: float  # time.monotonic()

    def pcm(self) -> np.ndarray:
        """(samples, channels) int16, interleaved order."""
        return np.frombuffer(bytes(self.buffer), "<i2").reshape(
            self.samples, self.channels
        )


class Listener:
    """A client's audio service: registered on a session, subscribed to ALAudioDevice like
    nao-bridge's microphone, recording every buffer with its arrival time."""

    count = 0

    def __init__(self, session: qi.Session):
        Listener.count += 1
        self.name = f"NaoSimE2EListener{Listener.count}"
        self.session = session
        self.chunks: list[Chunk] = []
        self._lock = threading.Lock()
        self._sid = session.registerService(self.name, self)
        self.device = session.service("ALAudioDevice")

    def processRemote(self, nbOfChannels, nbOfSamplesByChannel, timeStamp, inputBuffer):
        chunk = Chunk(
            nbOfChannels, nbOfSamplesByChannel, timeStamp, inputBuffer, time.monotonic()
        )
        with self._lock:
            self.chunks.append(chunk)

    def subscribe(
        self, rate: int | None = None, channels: int = 0, deinterleaved: int = 0
    ):
        if rate is not None:
            self.device.setClientPreferences(self.name, rate, channels, deinterleaved)
        self.device.subscribe(self.name)
        return self

    def received(self, since: float = 0.0) -> list[Chunk]:
        with self._lock:
            return [c for c in self.chunks if c.arrived >= since]

    def wait(self, n: int, timeout: float = 5.0) -> list[Chunk]:
        end = time.monotonic() + timeout
        while len(self.received()) < n and time.monotonic() < end:
            time.sleep(0.02)
        return self.received()

    def timeline(self, rate: int, since: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        """(sample times, first channel's samples): each chunk's samples end at its arrival."""
        times, values = [], []
        for c in self.received(since):
            pcm = c.pcm()[:, 0]
            times.append(c.arrived - (len(pcm) - np.arange(len(pcm))) / rate)
            values.append(pcm)
        if not times:
            return np.zeros(0), np.zeros(0)
        return np.concatenate(times), np.concatenate(values)

    def close(self) -> None:
        try:
            self.device.unsubscribe(self.name)
        except RuntimeError:
            pass
        try:
            self.session.unregisterService(self._sid)
        except RuntimeError:
            pass


def unavailable(reason: str) -> NoReturn:
    """Skip a test whose means the machine lacks; fail it when a version is required."""
    if REQUIRED is not None:
        pytest.fail(f"{reason} (NAO_SIM_E2E_VERSION={REQUIRED} requires it)")
    pytest.skip(reason)


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
        unavailable("Docker is not available")


def ensure_images(version: Version) -> None:
    """Use the version's images if current; build and verify them from the checkout if not,
    when its image data are there; skip (or fail, see `unavailable`) otherwise."""
    pinned = suite.VERSIONS[version.name]
    folder = IMAGE_DATA / version.name
    try:
        # Current images (this nao-sim, these recipes, verified) are used as they are.
        docker_images.check_images(version.name)
    except (ImagesMissingError, ImagesOutdatedError) as stale:
        if not (
            (folder / pinned.suite.filename).exists()
            and (folder / suite.PACKAGE).exists()
        ):
            unavailable(
                f"NAOqi {version.name}: no suite and package in docker/image-data/{version.name}/ "
                f"and no usable images ({stale})"
            )
        # The one slow step, as a user runs it: build from the checkout and verify.
        try:
            asyncio.run(docker_images.fetch_and_build_images([version.name]))
        except NaoSimError as e:
            pytest.fail(f"fetch-and-build-images failed for {version.name}: {e}")


def require_free_ports() -> None:
    for port, what in (
        (9559, "NAOqi"),
        (AUDIO_OUTPUT_PORT, "audio output"),
        (HOST_LINK_PORT, "host link"),
    ):
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
