"""The `nao-sim` command over the library: what each command prints and its exit code. `run` is
driven with a stand-in `NaoSim` and real signals; `status`, `cleanup` and `logs` with the fake
`docker` (tests/fake_docker.py)."""

import asyncio
import json
import os
import signal
import socket
import threading
from typing import ClassVar

import pytest

from nao_sim import cli, stack
from nao_sim.config import NaoSimConfig
from nao_sim.errors import ImagesMissingError
from nao_sim.stack import NaoSimStatus

STATUS = NaoSimStatus("0.0.1", "2.8.7.4", True, "none", "none")


class StandIn:
    """Stands in for `NaoSim`: records its lifecycle, starts in `start_s`."""

    made: ClassVar[list["StandIn"]] = []
    start_s = 0.0
    start_error: Exception | None = None

    def __init__(self, config: NaoSimConfig):
        self.config = config
        self.events: list[str] = []
        StandIn.made.append(self)

    async def start(self):
        self.events.append("start")
        try:
            await asyncio.sleep(StandIn.start_s)
        except asyncio.CancelledError:
            self.events.append("start cancelled")
            raise
        if StandIn.start_error:
            raise StandIn.start_error
        self.events.append("ready")

    async def stop(self):
        if "stop" not in self.events:
            self.events.append("stop")

    async def status(self):
        return STATUS

    @property
    def url(self):
        return "tcp://127.0.0.1:9559"


@pytest.fixture
def stand_in(monkeypatch):
    StandIn.made, StandIn.start_s, StandIn.start_error = [], 0.0, None
    monkeypatch.setattr(cli, "NaoSim", StandIn)
    return StandIn


def send_sigint_after(seconds: float) -> None:
    threading.Timer(seconds, os.kill, (os.getpid(), signal.SIGINT)).start()


def test_run_starts_until_ctrl_c_then_stops(stand_in, tmp_path, capsys):
    path = tmp_path / "sim.json"
    path.write_text(
        json.dumps({"naoqi": {"version": "2.8"}, "viewer": {"headless": True}})
    )
    send_sigint_after(0.3)

    assert cli.main(["run", "--config", str(path)]) == 0

    [naosim] = stand_in.made
    assert naosim.config.naoqi.version == "2.8" and naosim.config.viewer.headless
    assert naosim.events == ["start", "ready", "stop"]
    assert (
        "nao-sim 0.0.1 on NAOqi 2.8.7.4 ready at tcp://127.0.0.1:9559"
        in capsys.readouterr().out
    )


def test_run_without_a_file_uses_the_defaults(stand_in):
    send_sigint_after(0.3)
    assert cli.main(["run"]) == 0
    assert stand_in.made[0].config == NaoSimConfig()


def test_ctrl_c_during_the_start_cancels_it(stand_in):
    stand_in.start_s = 10
    send_sigint_after(0.2)

    assert cli.main(["run"]) == 130
    assert stand_in.made[0].events == ["start", "start cancelled", "stop"]


def test_a_config_error_exits_2_naming_the_key(stand_in, tmp_path, capsys):
    path = tmp_path / "sim.json"
    path.write_text(json.dumps({"viewer": {"variant": "shiny"}}))

    assert cli.main(["run", "--config", str(path)]) == 2
    assert "viewer.variant" in capsys.readouterr().err
    assert stand_in.made == []


def test_a_failed_start_exits_1_with_its_message(stand_in, capsys):
    stand_in.start_error = ImagesMissingError(
        "run `nao-sim fetch-and-build-images 2.1`"
    )

    assert cli.main(["run"]) == 1
    assert "fetch-and-build-images 2.1" in capsys.readouterr().err


def test_status_exits_0_only_when_ready(docker, monkeypatch, capsys):
    monkeypatch.setattr(stack, "read_naosim_status", lambda url=stack.URL: STATUS)
    assert cli.main(["status"]) == 1
    assert capsys.readouterr().out == "nao-sim is not running\n"

    docker.set(containers={"nao-sim-naoqi28": "starting", "nao-sim-tts": "running"})
    assert cli.main(["status"]) == 1
    assert "not reachable yet" in capsys.readouterr().out

    docker.set(containers={"nao-sim-naoqi28": "healthy", "nao-sim-tts": "running"})
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "nao-sim-naoqi28" in out and "(healthy)" in out
    assert "nao-sim 0.0.1 on NAOqi 2.8.7.4, ready: true" in out


def test_cleanup_prints_what_it_removed(docker, monkeypatch, capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        monkeypatch.setattr(stack, "AUDIO_OUTPUT_PORT", s.getsockname()[1])
    docker.set(containers={"nao-sim-naoqi21": "exited", "nao-sim-tts": "running"})

    assert cli.main(["cleanup"]) == 0
    assert capsys.readouterr().out == "removed nao-sim-naoqi21, nao-sim-tts\n"
    assert cli.main(["cleanup"]) == 0
    assert capsys.readouterr().out == "nothing to remove\n"


def test_logs_passes_its_options_to_compose(docker, capfd):
    assert cli.main(["logs", "--follow", "--tail", "20"]) == 0
    assert "fake log line" in capfd.readouterr().out
    assert docker.calls[-1] == "compose -p nao-sim logs --follow --tail 20"


def test_without_docker_every_command_exits_1(docker, capsys):
    docker.set(down=True)
    for command in (["status"], ["cleanup"], ["logs"]):
        assert cli.main(command) == 1
        assert "Docker is not available" in capsys.readouterr().err
