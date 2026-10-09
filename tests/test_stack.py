"""What other terminals read and do without a `NaoSim` object, against the fake `docker`
(tests/fake_docker.py): `read_status` and `cleanup`. The qi read of the `NaoSim` service is
replaced; the live tier covers it."""

import asyncio
import socket

import pytest

from nao_sim import stack
from nao_sim.errors import DockerUnavailableError, NaoSimError
from nao_sim.stack import ContainerState, NaoSimStatus

STATUS = NaoSimStatus("0.0.1", "2.1.4.13", True, "none", "none")


@pytest.fixture
def qi_reads(monkeypatch) -> list[str]:
    reads: list[str] = []

    def read(url=stack.URL):
        reads.append(url)
        return STATUS

    monkeypatch.setattr(stack, "read_naosim_status", read)
    return reads


def test_nothing_running(docker, qi_reads):
    status = asyncio.run(stack.read_status())

    assert status.containers == [] and status.naoqi is None and not status.ready
    assert qi_reads == []


def test_a_ready_robot(docker, qi_reads):
    docker.set(containers={"nao-sim-naoqi28": "healthy", "nao-sim-tts": "running"})

    status = asyncio.run(stack.read_status())

    assert status.containers == [
        ContainerState("nao-sim-naoqi28", "naoqi28", "running", "healthy"),
        ContainerState("nao-sim-tts", "tts", "running", ""),
    ]
    assert status.naoqi == STATUS and status.ready
    assert qi_reads == ["tcp://127.0.0.1:9559"]


@pytest.mark.parametrize("boot", ["starting", "unhealthy", "exited"])
def test_the_service_is_read_only_once_naoqi_is_healthy(docker, qi_reads, boot):
    docker.set(containers={"nao-sim-naoqi21": boot, "nao-sim-tts": "running"})

    status = asyncio.run(stack.read_status())

    assert len(status.containers) == 2
    assert status.naoqi is None and not status.ready
    assert qi_reads == []


def test_cleanup_removes_what_a_dead_run_left(docker, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        monkeypatch.setattr(stack, "AUDIO_OUTPUT_PORT", s.getsockname()[1])
    docker.set(containers={"nao-sim-naoqi21": "healthy", "nao-sim-tts": "running"})

    removed = asyncio.run(stack.cleanup())

    assert removed == ["nao-sim-naoqi21", "nao-sim-tts"]
    assert docker.read()["containers"] == {}
    assert any("--profile * down" in c for c in docker.calls)
    assert asyncio.run(stack.cleanup()) == []


def test_cleanup_refuses_while_a_run_is_alive(docker, monkeypatch):
    docker.set(containers={"nao-sim-naoqi21": "healthy", "nao-sim-tts": "running"})
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        monkeypatch.setattr(stack, "AUDIO_OUTPUT_PORT", s.getsockname()[1])
        with pytest.raises(NaoSimError, match="Ctrl-C"):
            asyncio.run(stack.cleanup())
    assert len(docker.read()["containers"]) == 2
    assert not any("down" in c for c in docker.calls)


def test_both_need_docker(docker):
    docker.set(down=True)
    with pytest.raises(DockerUnavailableError):
        asyncio.run(stack.read_status())
    with pytest.raises(DockerUnavailableError):
        asyncio.run(stack.cleanup())
