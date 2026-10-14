"""The modules a real NAOqi robot of each version runs, on a running naoqi-sim stack
(specs/container/naoqi-fidelity.md, "Matching a real NAOqi robot's modules"): on 2.1 the
entrypoint's autoload copy adds the autonomous abilities the desktop suite ships without loading,
with Autonomous Life after them, as the robot's autoload does; 2.8 has them as the expressivity
package's services. Every module in the image is also checked as Python 2.7."""

import subprocess


def services(nao) -> set[str]:
    return {s["name"] for s in nao.session.services()}


def test_basic_awareness_runs_as_on_a_nao(nao):
    # What a client turning basic awareness on does with it.
    awareness = nao.service("ALBasicAwareness")
    awareness.startAwareness()
    try:
        assert awareness.isAwarenessRunning() is True
    finally:
        awareness.stopAwareness()
    assert awareness.isAwarenessRunning() is False


def test_autonomous_life_answers(nao):
    assert nao.service("ALAutonomousLife").getState() in {
        "solitary",
        "interactive",
        "disabled",
        "safeguard",
    }


def test_the_autonomous_abilities_of_2_1_are_there(nao):
    if nao.version.name != "2.1":
        # 2.8 has no ALAutonomousMoves: its abilities are ALBackgroundMovement and friends.
        assert {"ALBackgroundMovement", "ALAutonomousBlinking"} <= services(nao)
        return
    assert {
        "ALAutonomousMoves",
        "_ALAutonomousBlinking",
        "_ALExpressiveness",
    } <= services(nao)


def test_the_modules_are_python_2_7(nao):
    # Every override module in the image, the ones this version does not load included,
    # compiled by the image's own Python 2.7 (specs/testing/ci.md, "Python 2.7 check").
    res = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "sh",
            nao.version.image,
            "-c",
            "python2 -m compileall -q /opt/naoqi/modules",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
