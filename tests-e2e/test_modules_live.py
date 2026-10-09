"""The modules a NAO of each version runs, on a running nao-sim stack (specs/container.md, "Matching
a NAO's modules"): on 2.1 the entrypoint launches the autonomous abilities the desktop suite ships
without loading, then Autonomous Life after them, as a NAO's autoload does; 2.8 has them as the
expressivity package's services."""


def services(nao) -> set[str]:
    return {s["name"] for s in nao.session.services()}


def test_basic_awareness_runs_as_on_a_nao(nao):
    # What a client such as nao-bridge's set_basic_awareness does with it.
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
