"""The containers of a running nao-sim, and what other terminals read from them (specs/runtime/api.md).

`up`/`down`/`wait_ready` are the container steps of `NaoSim.start()` and `stop()`.
`read_status` and `cleanup` serve `nao-sim status` and `nao-sim cleanup`, run from any
terminal: they read Docker and the `NaoSim` service, so they need no `NaoSim` object.
"""

import asyncio
import json
import logging
import subprocess
import time
from dataclasses import dataclass

from nao_sim import docker_images, files
from nao_sim.config import NaoSimConfig
from nao_sim.docker_images import COMPOSE, IMAGES, run
from nao_sim.errors import BootError, NaoSimError

log = logging.getLogger(__name__)

PROJECT = "nao-sim"
URL = "tcp://127.0.0.1:9559"
NAOQI_PORT = docker_images.NAOQI_PORT
AUDIO_OUTPUT_PORT = 9562  # the tts container streams to host.docker.internal:9562
HOST_LINK_PORT = (
    9563  # the containers' services connect out to host.docker.internal:9563
)


@dataclass(frozen=True)
class NaoSimStatus:
    """What the `NaoSim` service inside NAOqi reports (specs/container/status-service.md)."""

    version: str
    naoqi_version: str
    ready: bool
    camera_source: str
    audio_source: str


@dataclass(frozen=True)
class ContainerState:
    name: str
    service: str
    state: str  # running, exited, ...
    health: str  # healthy, starting, unhealthy, or "" without a healthcheck


@dataclass(frozen=True)
class StackStatus:
    """Whatever nao-sim runs on this machine: its containers, and its `NaoSim` service once
    the NAOqi container is healthy."""

    containers: list[ContainerState]
    naoqi: NaoSimStatus | None

    @property
    def ready(self) -> bool:
        return self.naoqi is not None and self.naoqi.ready


# --- The container steps of NaoSim.start() and stop() -------------------------------


def up(config: NaoSimConfig) -> None:
    """Start the `tts` service and the version's NAOqi service from the verified images."""
    images = IMAGES[config.naoqi.version]
    env = {**files.compose_env(), "NAO_SIM_TTS_ENGINE": config.speech.engine}
    res = run(
        *images.compose(),
        "up",
        "-d",
        "--no-build",
        "tts",
        images.service,
        timeout=300,
        env=env,
    )
    if res.returncode != 0:
        raise BootError(
            f"docker compose up failed for NAOqi {images.version}:\n{res.stderr[-3000:]}"
        )


def wait_ready(config: NaoSimConfig) -> None:
    docker_images.wait_healthy(
        IMAGES[config.naoqi.version], timeout=config.naoqi.ready_timeout_s
    )


def down(version: str) -> None:
    """`docker compose down`: removes the containers, keeps the package store volumes."""
    res = run(*IMAGES[version].compose(), "down", timeout=300, env=files.compose_env())
    if res.returncode != 0:
        raise NaoSimError(
            f"docker compose down failed for NAOqi {version}:\n{res.stderr[-3000:]}"
        )


# --- Without a NaoSim object --------------------------------------------------------


def _containers() -> list[ContainerState]:
    res = run("docker", "compose", "-p", PROJECT, "ps", "-a", "--format", "json")
    if res.returncode != 0:
        raise NaoSimError(f"docker compose ps failed:\n{res.stderr[-3000:]}")
    # One JSON object per line (Compose 2.21+), or one array (older releases).
    text = res.stdout.strip()
    rows = (
        json.loads(text)
        if text.startswith("[")
        else [json.loads(line) for line in text.splitlines() if line.strip()]
    )
    return sorted(
        (
            ContainerState(
                r.get("Name", ""),
                r.get("Service", ""),
                r.get("State", ""),
                r.get("Health", ""),
            )
            for r in rows
        ),
        key=lambda c: c.name,
    )


def connect(url: str = URL, attempts: int = 5):
    """A qi session, with the retry libqi 3 needs: about one connect in three fails against 2.1."""
    import qi

    error: Exception | None = None
    for _ in range(attempts):
        session = qi.Session()
        try:
            session.connect(url)
            return session
        except RuntimeError as e:
            error = e
            time.sleep(0.5)
    raise NaoSimError(f"could not connect to {url} in {attempts} attempts: {error}")


def read_naosim_status(url: str = URL) -> NaoSimStatus:
    """Read the `NaoSim` service and its ALMemory keys over qi."""
    session = connect(url)
    try:
        naosim = session.service("NaoSim")
        memory = session.service("ALMemory")
        return NaoSimStatus(
            version=naosim.getVersion(),
            naoqi_version=naosim.getNaoqiVersion(),
            ready=bool(naosim.isReady()),
            camera_source=memory.getData("NaoSim/Camera/Source"),
            audio_source=memory.getData("NaoSim/Audio/Source"),
        )
    finally:
        session.close()


def _read_status() -> StackStatus:
    docker_images.require_docker()
    containers = _containers()
    naoqi_healthy = any(
        c.service in {i.service for i in IMAGES.values()}
        and c.state == "running"
        and c.health == "healthy"
        for c in containers
    )
    return StackStatus(containers, read_naosim_status() if naoqi_healthy else None)


async def read_status() -> StackStatus:
    """The state of whatever nao-sim runs on this machine."""
    return await asyncio.to_thread(_read_status)


def _cleanup() -> list[str]:
    docker_images.require_docker()
    try:
        docker_images.require_free(AUDIO_OUTPUT_PORT)
    except NaoSimError:
        raise NaoSimError(
            "a nao-sim is still running (its audio output holds port "
            f"{AUDIO_OUTPUT_PORT}): press Ctrl-C in its terminal to stop it"
        ) from None
    names = [c.name for c in _containers()]
    res = run(
        "docker",
        "compose",
        "-f",
        str(COMPOSE),
        "--profile",
        "*",
        "down",
        timeout=300,
        env=files.compose_env(),
    )
    if res.returncode != 0:
        raise NaoSimError(f"docker compose down failed:\n{res.stderr[-3000:]}")
    return names


async def cleanup() -> list[str]:
    """Remove what a `NaoSim` that died without stopping left behind; returns the containers
    removed. Refuses while a nao-sim is still running."""
    return await asyncio.to_thread(_cleanup)


def show_logs(follow: bool = False, tail: int | None = None) -> int:
    """`docker compose logs` on the nao-sim project, straight to the terminal."""
    docker_images.require_docker()
    args = ["docker", "compose", "-p", PROJECT, "logs"]
    if follow:
        args.append("--follow")
    if tail is not None:
        args += ["--tail", str(tail)]
    try:
        return subprocess.run(args, check=False).returncode
    except KeyboardInterrupt:
        return 0
