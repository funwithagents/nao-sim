"""The containers' entrypoints (one per NAOqi version) and the healthcheck, run on the host against fake `naoqi-bin` and `qicli`.

The fakes sit first on PATH. `qicli` logs every invocation, lists `FAKE_QICLI_SERVICES` (minus
the names that are "down", plus names that appear late) on `info` without a name, answers `info
NAME` with failure while NAME is down, takes a name down on `call NAME.exit`, brings one back when
the module (or the library, by file name) that registers it is loaded (`FAKE_QICLI_REGISTERS`),
keeps the names our modules add down until then (`FAKE_QICLI_ABSENT`), and serves
`NaoSim.setReady` and `NaoSim.isReady` in either suite's output style.
"""

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

DOCKER = Path(__file__).resolve().parent.parent / "docker"
ENTRYPOINTS = {v: DOCKER / f"entrypoint-{v}.sh" for v in ("2.1", "2.8")}
HEALTHCHECK = DOCKER / "healthcheck.sh"

FAKE_QICLI = textwrap.dedent(
    """\
    import os, sys
    fake = os.environ["FAKE_DIR"]
    args = sys.argv[1:]
    with open(os.path.join(fake, "qicli.log"), "a") as f:
        f.write(" ".join(args) + "\\n")
    down_file = os.path.join(fake, "down")
    down = set(open(down_file).read().split()) if os.path.exists(down_file) else set()
    registered_file = os.path.join(fake, "registered")
    registered = set(open(registered_file).read().split()) if os.path.exists(registered_file) else set()
    down |= set(os.environ.get("FAKE_QICLI_ABSENT", "").split()) - registered
    registers = dict(
        item.split("=") for item in os.environ.get("FAKE_QICLI_REGISTERS", "").split(",") if item
    )
    def save():
        open(down_file, "w").write(" ".join(sorted(down)))
        open(registered_file, "w").write(" ".join(sorted(registered)))
    def register(name):
        if name:
            down.discard(name); registered.add(name)
        save()
    counter = os.path.join(fake, "info.count")
    if args[0] == "info":
        n = int(open(counter).read()) + 1 if os.path.exists(counter) else 1
        open(counter, "w").write(str(n))
        if n <= int(os.environ.get("FAKE_QICLI_READY_AFTER", "0")):
            sys.exit(1)
        if args[1] == "--qi-url":  # no name: list the services, as `NNN [Name]` lines
            late = dict(
                item.split(":") for item in os.environ.get("FAKE_QICLI_LATE", "").split(",") if item
            )
            for i, name in enumerate(os.environ["FAKE_QICLI_SERVICES"].split()):
                if name not in down and n >= int(late.get(name, 0)):
                    print("%03d [%s]" % (i + 1, name))
            sys.exit(0)
        sys.exit(1 if args[1] in down else 0)
    target = args[1]
    if target.endswith(".exit"):
        down.add(target[: -len(".exit")]); save(); sys.exit(0)
    if target == "ALLauncher.launchPythonModule":
        register(registers.get(args[2], "")); sys.exit(0)
    if target == "ALLauncher.launchLocal":  # the modules the library registered, as 2.1 prints them
        empty = os.environ.get("FAKE_QICLI_EMPTY_LAUNCH", "").split()
        name = os.path.basename(args[2])
        if name in empty:
            print("ALLauncher.launchLocal: [  ]")
        else:
            register(registers.get(name, ""))
            print('ALLauncher.launchLocal: [ "%s" ]' % registers.get(name, name))
        sys.exit(0)
    if target.startswith("NaoSim."):
        if "NaoSim" in down:
            sys.stderr.write("Call failed: no such service\\n"); sys.exit(1)
        if target == "NaoSim.setReady":
            open(os.path.join(fake, "ready"), "w").close()
        if target == "NaoSim.isReady":
            value = "true" if os.path.exists(os.path.join(fake, "ready")) else "false"
            if os.environ.get("FAKE_QICLI_STYLE") == "2.8":  # bare value, then warnings on stdout
                print(value + "\\n[W] 1791533267.881648 1744 qitype.signal: disconnect: No subscription")
            else:
                print("NaoSim.isReady: " + value)
    sys.exit(0)
    """
)

FAKE_NAOQI_BIN = textwrap.dedent(
    """\
    #!/bin/bash
    echo "$@" > "$FAKE_DIR/naoqi-bin.args"
    echo "${NAO_SIM_INTERNAL_PORT:-unset}" > "$FAKE_DIR/naoqi-bin.port"
    [ -n "${FAKE_NAOQI_EXIT:-}" ] && exit "$FAKE_NAOQI_EXIT"
    trap 'exit 0' TERM INT
    while :; do sleep 0.1; done
    """
)

AUTOLOAD = "pythonbridge\nanimatedspeech\naudioout\nalpanoramacompass\nautonomouslife\ndialog\n"
SERVICES = (
    "ServiceDirectory ALMemory ALLauncher ALPythonBridge ALTextToSpeech ALAudioPlayer "
    "ALServiceManager ALAutonomousLife ALPanoramaCompass"
)

RELAY = "libnaosim_audiorelay.so"
ADDED = "ALAudioDevice _NaoSimAudioRelay"
REGISTERS_21 = (
    "nao_sim_status_almodule=NaoSim,nao_sim_tts_almodule=ALTextToSpeech,"
    f"nao_sim_audiodevice_almodule=ALAudioDevice,{RELAY}=_NaoSimAudioRelay"
)
REGISTERS_28 = (
    "nao_sim_status_qiservice=NaoSim,nao_sim_tts_qiservice=ALTextToSpeech,"
    f"nao_sim_audiodevice_qiservice=ALAudioDevice,{RELAY}=_NaoSimAudioRelay"
)


class Fakes:
    def __init__(self, tmp_path: Path):
        self.dir = tmp_path / "fake"
        self.bin = self.dir / "bin"
        self.bin.mkdir(parents=True)
        (self.bin / "qicli").write_text(f"#!{sys.executable}\n{FAKE_QICLI}")
        (self.bin / "naoqi-bin").write_text(FAKE_NAOQI_BIN)
        for f in self.bin.iterdir():
            f.chmod(0o755)
        self.naoqi_home = tmp_path / "naoqi"
        (self.naoqi_home / "etc" / "naoqi").mkdir(parents=True)
        (self.naoqi_home / "etc" / "naoqi" / "autoload.ini").write_text(AUTOLOAD)
        self.tmp = tmp_path / "tmp"
        self.tmp.mkdir()

    def env(self, extra: dict[str, str]) -> dict[str, str]:
        return {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FAKE_DIR": str(self.dir),
            "NAOQI_HOME": str(self.naoqi_home),
            "TMPDIR": str(self.tmp),
            "NAO_SIM_POLL_INTERVAL": "0.05",
            "FAKE_QICLI_SERVICES": SERVICES,
            "FAKE_QICLI_ABSENT": ADDED,
            **extra,
        }

    def calls(self) -> list[str]:
        log = self.dir / "qicli.log"
        return log.read_text().splitlines() if log.exists() else []

    def naoqi_bin_args(self) -> str:
        return (self.dir / "naoqi-bin.args").read_text().strip()

    def naoqi_bin_port_env(self) -> str:
        """NAO_SIM_INTERNAL_PORT as naoqi-bin (and so naoqi-service, our modules) inherits it."""
        return (self.dir / "naoqi-bin.port").read_text().strip()


class Entrypoint:
    def __init__(self, fakes: Fakes, version: str, extra: dict[str, str]):
        self.fakes = fakes
        self.out = fakes.dir / "stdout"
        self.proc = subprocess.Popen(
            ["bash", str(ENTRYPOINTS[version])],
            env=fakes.env(extra),
            stdout=self.out.open("w"),
            stderr=subprocess.STDOUT,
        )

    def output(self) -> str:
        return self.out.read_text() if self.out.exists() else ""

    def wait_for_ready(self, timeout: float = 10) -> None:
        end = time.time() + timeout
        while "[entrypoint] nao-sim ready" not in self.output():
            if self.proc.poll() is not None:
                pytest.fail(
                    f"entrypoint exited {self.proc.returncode}:\n{self.output()}"
                )
            if time.time() > end:
                self.stop()
                pytest.fail(f"no ready line after {timeout}s:\n{self.output()}")
            time.sleep(0.05)

    def wait_exit(self, timeout: float = 10) -> int:
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.stop()
            pytest.fail(f"entrypoint still running after {timeout}s:\n{self.output()}")

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(5)


@pytest.fixture
def fakes(tmp_path):
    return Fakes(tmp_path)


def calls_only(fakes: Fakes) -> list[str]:
    return [c for c in fakes.calls() if c.startswith("call ")]


def test_sequence_on_2_1(fakes):
    ep = Entrypoint(fakes, "2.1", {"FAKE_QICLI_REGISTERS": REGISTERS_21})
    ep.wait_for_ready()
    ep.stop()

    url = "--qi-url tcp://127.0.0.1:9559"
    assert calls_only(fakes) == [
        f"call ALTextToSpeech.exit {url}",
        f"call ALLauncher.launchLocal {fakes.naoqi_home}/lib/nao-sim/{RELAY} {url}",
        f"call ALPythonBridge.eval import sys; sys.path.insert(0, '{fakes.naoqi_home}/modules') {url}",
        f"call ALLauncher.launchPythonModule nao_sim_status_almodule {url}",
        f"call ALLauncher.launchPythonModule nao_sim_tts_almodule {url}",
        f"call ALLauncher.launchPythonModule nao_sim_audiodevice_almodule {url}",
        # Late, in a NAO's autoload order: the TTS dependents, the built-ins a NAO autoloads and
        # the desktop does not, and autonomouslife after those.
        f"call ALLauncher.launchLocal expressiveness {url}",
        f"call ALLauncher.launchLocal animatedspeech {url}",
        f"call ALLauncher.launchLocal basicawareness {url}",
        f"call ALLauncher.launchLocal autonomousblinking {url}",
        f"call ALLauncher.launchLocal autonomousmoves {url}",
        f"call ALLauncher.launchLocal autonomouslife {url}",
        f"call ALLauncher.launchLocal dialog {url}",
        f"call NaoSim.setReady {url}",
    ]
    # The service list is polled until stable (1 + 3 polls), then the replaced name and the added
    # ones are checked after loading, right before setReady.
    assert "NAOqi ready after 4 polls, 9 services" in ep.output()
    assert fakes.calls()[-4:-1] == [
        f"info ALTextToSpeech {url}",
        f"info ALAudioDevice {url}",
        f"info _NaoSimAudioRelay {url}",
    ]
    # naoqi-bin got the broker arguments and the autoload copy with the late entries it lists
    # deferred; the others were never in it.
    args = fakes.naoqi_bin_args()
    assert args.startswith("-b 0.0.0.0 -p 9559 --autoload-file ")
    autoload = Path(args.split("--autoload-file ")[1]).read_text()
    assert autoload == (
        "pythonbridge\n#deferred animatedspeech\naudioout\nalpanoramacompass\n"
        "#deferred autonomouslife\n#deferred dialog\n"
    )


def test_sequence_on_2_8(fakes):
    ep = Entrypoint(fakes, "2.8", {"FAKE_QICLI_REGISTERS": REGISTERS_28})
    ep.wait_for_ready()
    ep.stop()

    url = "--qi-url tcp://127.0.0.1:9558"
    assert calls_only(fakes) == [
        f"call ALServiceManager.stopService expressivity.autonomousabilitiesmodules {url}",
        f"call ALTextToSpeech.exit {url}",
        f"call ALLauncher.launchLocal {fakes.naoqi_home}/lib/nao-sim/{RELAY} {url}",
        f"call ALPythonBridge.eval import sys; sys.path.insert(0, '{fakes.naoqi_home}/modules') {url}",
        f"call ALLauncher.launchPythonModule nao_sim_status_qiservice {url}",
        f"call ALLauncher.launchPythonModule nao_sim_tts_qiservice {url}",
        f"call ALLauncher.launchPythonModule nao_sim_audiodevice_qiservice {url}",
        f"call ALServiceManager.startService expressivity.autonomousabilitiesmodules {url}",
        f"call NaoSim.setReady {url}",
    ]
    args = fakes.naoqi_bin_args()
    assert args == (
        "--qi-listen-url tcp://127.0.0.1:9558 "
        f"--autoload-file {fakes.naoqi_home}/etc/naoqi/autoload.ini"
    )
    # The qi services connect back to NAOqi on the port the script exports.
    assert fakes.naoqi_bin_port_env() == "9558"


def test_polls_until_naoqi_answers(fakes):
    ep = Entrypoint(
        fakes,
        "2.1",
        {"FAKE_QICLI_REGISTERS": REGISTERS_21, "FAKE_QICLI_READY_AFTER": "4"},
    )
    ep.wait_for_ready()
    ep.stop()
    assert (
        "NAOqi ready after 8 polls" in ep.output()
    )  # four refusals, then 1 + 3 stable


def test_waits_for_the_required_services_and_a_settled_list(fakes):
    # The ready service only appears at the 3rd listing, and another service keeps the list
    # changing until the 6th: stable at polls 7, 8, 9, so nothing is called before the 9th.
    ep = Entrypoint(
        fakes,
        "2.8",
        {
            "FAKE_QICLI_REGISTERS": REGISTERS_28,
            "FAKE_QICLI_LATE": "ALPanoramaCompass:3,ALAudioPlayer:6",
        },
    )
    ep.wait_for_ready()
    ep.stop()
    assert "NAOqi ready after 9 polls" in ep.output()
    listings_before_acting = 0
    for c in fakes.calls():
        if c.startswith("call "):
            break
        listings_before_acting += 1
    assert listings_before_acting == 9


def test_gives_up_when_naoqi_never_answers(fakes):
    (fakes.dir / "down").write_text("ALLauncher")
    ep = Entrypoint(fakes, "2.1", {"NAO_SIM_READY_TRIES": "3"})
    assert ep.wait_exit() == 1
    assert "not ready after 3 polls" in ep.output()
    assert "nao-sim ready" not in ep.output()
    assert calls_only(fakes) == []


def test_gives_up_when_a_required_service_never_appears(fakes):
    (fakes.dir / "down").write_text("ALPythonBridge")
    ep = Entrypoint(fakes, "2.1", {"NAO_SIM_READY_TRIES": "3"})
    assert ep.wait_exit() == 1
    assert "not ready after 3 polls" in ep.output()
    assert "ALPythonBridge" in ep.output()
    assert calls_only(fakes) == []


def test_fails_when_a_replacement_did_not_register(fakes):
    # The tts module is loaded but registers nothing: ALTextToSpeech stays gone.
    ep = Entrypoint(
        fakes,
        "2.1",
        {"FAKE_QICLI_REGISTERS": REGISTERS_21.replace("=ALTextToSpeech", "=")},
    )
    assert ep.wait_exit() == 1
    assert "replaced service ALTextToSpeech does not answer" in ep.output()
    assert "nao-sim ready" not in ep.output()
    assert not [c for c in fakes.calls() if "setReady" in c]


@pytest.mark.parametrize("version", ["2.1", "2.8"])
def test_fails_when_the_relay_registers_nothing(fakes, version):
    registers = REGISTERS_21 if version == "2.1" else REGISTERS_28
    ep = Entrypoint(
        fakes,
        version,
        {"FAKE_QICLI_REGISTERS": registers, "FAKE_QICLI_EMPTY_LAUNCH": RELAY},
    )
    assert ep.wait_exit() == 1
    assert f"the relay {fakes.naoqi_home}/lib/nao-sim/{RELAY} registered no module" in (
        ep.output()
    )
    # Nothing is loaded after it, and the robot is never marked ready.
    assert not [c for c in fakes.calls() if "launchPythonModule" in c]
    assert not [c for c in fakes.calls() if "setReady" in c]


@pytest.mark.parametrize("version", ["2.1", "2.8"])
def test_fails_when_the_audio_device_does_not_register(fakes, version):
    registers = REGISTERS_21 if version == "2.1" else REGISTERS_28
    ep = Entrypoint(
        fakes,
        version,
        {"FAKE_QICLI_REGISTERS": registers.replace("=ALAudioDevice", "=")},
    )
    assert ep.wait_exit() == 1
    assert "added service ALAudioDevice does not answer" in ep.output()
    assert "nao-sim ready" not in ep.output()
    assert not [c for c in fakes.calls() if "setReady" in c]


def test_fails_when_a_late_built_in_registers_nothing(fakes):
    ep = Entrypoint(
        fakes,
        "2.1",
        {
            "FAKE_QICLI_REGISTERS": REGISTERS_21,
            "FAKE_QICLI_EMPTY_LAUNCH": "basicawareness",
        },
    )
    assert ep.wait_exit() == 1
    assert "launching basicawareness registered no module" in ep.output()
    assert "nao-sim ready" not in ep.output()
    # Nothing after the failed launch: no later built-in, no ready mark.
    launched = [
        c.split()[2] for c in calls_only(fakes) if "launchLocal" in c and RELAY not in c
    ]
    assert launched == ["expressiveness", "animatedspeech", "basicawareness"]
    assert not [c for c in fakes.calls() if "setReady" in c]


def test_fails_when_the_status_module_is_missing(fakes):
    (fakes.dir / "down").write_text("NaoSim")
    ep = Entrypoint(
        fakes, "2.1", {"FAKE_QICLI_REGISTERS": REGISTERS_21.replace("=NaoSim", "=")}
    )
    assert ep.wait_exit() == 1
    assert "NaoSim.setReady failed" in ep.output()
    assert "nao-sim ready" not in ep.output()


def test_fails_when_naoqi_bin_dies(fakes):
    (fakes.dir / "down").write_text("ALLauncher")
    ep = Entrypoint(fakes, "2.1", {"FAKE_NAOQI_EXIT": "3"})
    assert ep.wait_exit() == 1
    assert "naoqi-bin exited" in ep.output()


@pytest.mark.parametrize("style", ["2.1", "2.8"])
def test_healthcheck_follows_the_ready_flag(fakes, style):
    def run() -> int:
        env = fakes.env({"FAKE_QICLI_STYLE": style})
        return subprocess.run(
            ["bash", str(HEALTHCHECK)], env=env, check=False
        ).returncode

    assert run() == 1  # NaoSim answers false before setReady
    (fakes.dir / "ready").touch()
    assert run() == 0
    (fakes.dir / "down").write_text("NaoSim")
    assert run() == 1  # the service is gone
    assert all("tcp://127.0.0.1:9559" in c for c in fakes.calls())
