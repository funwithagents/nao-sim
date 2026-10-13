"""What other terminals read and do without a `NaoqiSim` object, against the fake `docker`
(tests/fake_docker.py): `read_status` and `cleanup`. The qi read of the `NaoqiSim` service is
replaced; the live tier covers it."""

import asyncio
import socket
import threading
import time

import pytest
from ports import free_port

from naoqi_sim import stack
from naoqi_sim.errors import DockerUnavailableError, NaoqiSimError
from naoqi_sim.stack import ContainerState, NaoqiSimStatus

STATUS = NaoqiSimStatus("0.0.1", "2.1.4.13", True, "none", "none")


@pytest.fixture
def qi_reads(monkeypatch) -> list[str]:
    reads: list[str] = []

    def read(url=stack.URL):
        reads.append(url)
        return STATUS

    monkeypatch.setattr(stack, "read_naoqisim_status", read)
    return reads


def test_nothing_running(docker, qi_reads):
    status = asyncio.run(stack.read_status())

    assert status.containers == [] and status.naoqi is None and not status.ready
    assert qi_reads == []


def test_a_ready_robot(docker, qi_reads):
    docker.set(containers={"naoqi-sim-naoqi28": "healthy", "naoqi-sim-tts": "running"})

    status = asyncio.run(stack.read_status())

    assert status.containers == [
        ContainerState("naoqi-sim-naoqi28", "naoqi28", "running", "healthy"),
        ContainerState("naoqi-sim-tts", "tts", "running", ""),
    ]
    assert status.naoqi == STATUS and status.ready
    assert qi_reads == ["tcp://127.0.0.1:9559"]


@pytest.mark.parametrize("boot", ["starting", "unhealthy", "exited"])
def test_the_service_is_read_only_once_naoqi_is_healthy(docker, qi_reads, boot):
    docker.set(containers={"naoqi-sim-naoqi21": boot, "naoqi-sim-tts": "running"})

    status = asyncio.run(stack.read_status())

    assert len(status.containers) == 2
    assert status.naoqi is None and not status.ready
    assert qi_reads == []


def test_cleanup_removes_what_a_dead_run_left(docker, monkeypatch):
    monkeypatch.setattr(stack, "AUDIO_OUTPUT_PORT", free_port())
    docker.set(containers={"naoqi-sim-naoqi21": "healthy", "naoqi-sim-tts": "running"})

    removed = asyncio.run(stack.cleanup())

    assert removed == ["naoqi-sim-naoqi21", "naoqi-sim-tts"]
    assert docker.read()["containers"] == {}
    assert any("--profile * down" in c for c in docker.calls)
    assert asyncio.run(stack.cleanup()) == []


def test_cleanup_refuses_while_a_run_is_alive(docker, monkeypatch):
    docker.set(containers={"naoqi-sim-naoqi21": "healthy", "naoqi-sim-tts": "running"})
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        monkeypatch.setattr(stack, "AUDIO_OUTPUT_PORT", s.getsockname()[1])
        with pytest.raises(NaoqiSimError, match="Ctrl-C"):
            asyncio.run(stack.cleanup())
    assert len(docker.read()["containers"]) == 2
    assert not any("down" in c for c in docker.calls)


def test_both_need_docker(docker):
    docker.set(down=True)
    with pytest.raises(DockerUnavailableError):
        asyncio.run(stack.read_status())
    with pytest.raises(DockerUnavailableError):
        asyncio.run(stack.cleanup())


def test_a_failed_connect_is_not_retried():
    # A server that hangs up at once, as NAOqi 2.1 seemed to for libqi 3.1.6 (an instant
    # `disconnected`): one attempt, then NaoqiSimError naming the URL.
    accepted: list[socket.socket] = []
    with socket.create_server(("127.0.0.1", 0)) as server:
        server.settimeout(0.1)

        def hang_up() -> None:
            while server.fileno() != -1:
                try:
                    peer, _ = server.accept()
                except TimeoutError:
                    continue
                except OSError:  # the server closed
                    return
                accepted.append(peer)
                peer.close()

        threading.Thread(target=hang_up, daemon=True).start()
        url = f"tcp://127.0.0.1:{server.getsockname()[1]}"
        with pytest.raises(NaoqiSimError, match=url):
            stack.connect(url)
        time.sleep(1.0)  # room for a retry (the old one came after 0.5 s)
    assert len(accepted) == 1
