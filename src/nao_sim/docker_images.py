"""The Docker images a simulated NAO runs on: fetched, built and verified once, checked at every start.

`fetch_and_build_images` does everything slow or downloaded, per NAOqi version: it fetches the
vendor files (`suite.fetch`), builds the version's NAOqi image and the `tts` image with the
installed nao-sim version as build argument and label, then boots them until the NAOqi container
is healthy and the `tts` engine answers, and takes them down. Only the image IDs that booted are
recorded, in `images.json` next to the vendor files.

`check_images` is what a start runs instead: the images exist, carry this nao-sim's version and
were verified. It never downloads or builds.
"""

import asyncio
import importlib.metadata
import json
import logging
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from nao_sim import suite
from nao_sim.errors import (
    BootError,
    DockerUnavailableError,
    FetchError,
    ImageBuildError,
    ImagesMissingError,
    ImagesOutdatedError,
    PortInUseError,
)

log = logging.getLogger(__name__)

DOCKER = Path(__file__).resolve().parents[2] / "docker"
COMPOSE = DOCKER / "compose.yaml"
VENDOR = suite.VENDOR
RECORD = "images.json"  # in the vendor folder, gitignored with it
LABEL = "io.nao-sim.version"
TTS_IMAGE = "nao-sim/tts:dev"
TTS_CONTAINER = "nao-sim-tts"
NAOQI_PORT = 9559
READY_TIMEOUT = 240.0  # seconds for the NAOqi container to turn healthy
TTS_TIMEOUT = 15.0  # seconds for the tts engine to answer once NAOqi is healthy
POLL = 1.0


@dataclass(frozen=True)
class Images:
    version: str
    image: str  # the NAOqi image tag
    service: str  # its compose service
    container: str
    profile: (
        str  # its compose profile: every NAOqi service has one, so one runs at a time
    )

    def compose(self) -> list[str]:
        return ["docker", "compose", "-f", str(COMPOSE), "--profile", self.profile]


IMAGES = {
    "2.1": Images("2.1", "nao-sim/naoqi:2.1.4.13", "naoqi21", "nao-sim-naoqi21", "2.1"),
    "2.8": Images("2.8", "nao-sim/naoqi:2.8.7.4", "naoqi28", "nao-sim-naoqi28", "2.8"),
}


def nao_sim_version() -> str:
    """The installed nao-sim version, built into the images and checked at start."""
    return importlib.metadata.version("nao-sim")


def _command(version: str) -> str:
    return f"run `nao-sim fetch-and-build-images {version}`"


def _run(
    *args: str, timeout: float = 120, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False, env=env
    )


def _inspect(tag: str) -> tuple[str, str | None] | None:
    """The image's ID and nao-sim version label, or None if there is no such image."""
    res = _run("docker", "image", "inspect", tag)
    if res.returncode != 0:
        return None
    info = json.loads(res.stdout)[0]
    labels = (info.get("Config") or {}).get("Labels") or {}
    return info["Id"], labels.get(LABEL)


def _verified(vendor: Path) -> dict[str, str]:
    """Image tag to the ID that last passed verification."""
    path = vendor / RECORD
    if not path.exists():
        return {}
    return json.loads(path.read_text())["verified"]


def _record(vendor: Path, verified: dict[str, str]) -> None:
    vendor.mkdir(parents=True, exist_ok=True)
    (vendor / RECORD).write_text(json.dumps({"verified": verified}, indent=2) + "\n")


def check_images(version: str, vendor: Path = VENDOR) -> None:
    """Raise unless the version's NAOqi image and the tts image are built by this nao-sim
    version and verified. Needs Docker; downloads and builds nothing."""
    images = IMAGES[version]
    want = nao_sim_version()
    verified = _verified(vendor)
    for tag in (images.image, TTS_IMAGE):
        found = _inspect(tag)
        if found is None:
            raise ImagesMissingError(f"{tag} is not built: {_command(version)}")
        image_id, built_by = found
        if built_by != want:
            raise ImagesOutdatedError(
                f"{tag} was built by nao-sim {built_by or '(unknown)'}, this is nao-sim "
                f"{want}: {_command(version)}"
            )
        if verified.get(tag) != image_id:
            raise ImagesMissingError(f"{tag} was not verified: {_command(version)}")


def _require_docker() -> None:
    if shutil.which("docker") is None or _run("docker", "info").returncode != 0:
        raise DockerUnavailableError(
            "Docker is not available: install it or start it (Docker Desktop, OrbStack)"
        )


def _require_free(port: int) -> None:
    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise PortInUseError(
                f"127.0.0.1:{port} is taken: stop the running nao-sim (or the stack "
                "started by hand) first"
            )


def _logs(container: str) -> str:
    res = _run("docker", "logs", "--tail", "60", container)
    return (res.stdout + res.stderr).strip()


def _wait_healthy(images: Images) -> None:
    end = time.monotonic() + READY_TIMEOUT
    while True:
        res = _run(
            "docker",
            "inspect",
            "-f",
            "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}",
            images.container,
        )
        state = res.stdout.split() if res.returncode == 0 else ["missing"]
        if state == ["running", "healthy"]:
            return
        if state[0] != "running" or state[1:] == ["unhealthy"]:
            raise BootError(
                f"NAOqi {images.version} did not boot ({' '.join(state)}):\n"
                + _logs(images.container)
            )
        if time.monotonic() > end:
            raise BootError(
                f"NAOqi {images.version} not healthy after {READY_TIMEOUT:.0f} s:\n"
                + _logs(images.container)
            )
        time.sleep(POLL)


_TTS_HEALTH = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5)"


def _wait_tts() -> None:
    end = time.monotonic() + TTS_TIMEOUT
    while _run("docker", "exec", TTS_CONTAINER, "python", "-c", _TTS_HEALTH).returncode:
        if time.monotonic() > end:
            raise BootError(f"the tts engine does not answer:\n{_logs(TTS_CONTAINER)}")
        time.sleep(POLL)


def _build(images: Images, env: dict[str, str]) -> None:
    log.info("NAOqi %s: building %s and %s", images.version, images.image, TTS_IMAGE)
    res = _run(*images.compose(), "build", "tts", images.service, timeout=3600, env=env)
    if res.returncode != 0:
        raise ImageBuildError(
            f"docker compose build failed for NAOqi {images.version}:\n"
            + (res.stdout + res.stderr)[-3000:]
        )


def _verify(images: Images, env: dict[str, str]) -> None:
    log.info("NAOqi %s: verifying the images boot", images.version)
    _require_free(NAOQI_PORT)
    try:
        res = _run(*images.compose(), "up", "-d", "tts", images.service, env=env)
        if res.returncode != 0:
            raise BootError(
                f"docker compose up failed for NAOqi {images.version}:\n{res.stderr[-3000:]}"
            )
        _wait_healthy(images)
        _wait_tts()
    finally:
        _run(*images.compose(), "down", timeout=300, env=env)


def _fetch_build_verify(images: Images, vendor: Path) -> None:
    try:
        suite.fetch(suite.VERSIONS[images.version], vendor)
    except OSError as e:  # network or disk; hash failures are FetchError already
        raise FetchError(
            f"fetching the NAOqi {images.version} vendor files: {e}"
        ) from e
    env = {**os.environ, "NAO_SIM_VERSION": nao_sim_version()}
    _build(images, env)
    _verify(images, env)
    verified = _verified(vendor)
    for tag in (images.image, TTS_IMAGE):
        found = _inspect(tag)
        if found is None:  # removed while verifying
            raise ImagesMissingError(f"{tag} disappeared: {_command(images.version)}")
        verified[tag] = found[0]
    _record(vendor, verified)
    log.info("NAOqi %s: images built and verified", images.version)


async def fetch_and_build_images(
    versions: Iterable[str] | None = None, *, vendor: Path = VENDOR
) -> None:
    """Fetch, build and verify the images of each version (default: all), in order."""
    names = list(versions or IMAGES)
    if unknown := [v for v in names if v not in IMAGES]:
        raise ValueError(
            f"unknown NAOqi version(s) {', '.join(unknown)}; choose from {', '.join(IMAGES)}"
        )
    await asyncio.to_thread(_require_docker)
    for name in names:
        await asyncio.to_thread(_fetch_build_verify, IMAGES[name], vendor)
