"""Behaviors as the Behavior Control boxes run them (Run, Start and Stop Behavior, Behavior State;
2.8's Autonomous Abilities), from a host client: a behavior's run is seen in ALBehaviorManager's
state and in the joints it moves (plans/202610132100_api-coverage-from-boxes.md)."""

import threading
import time

import pytest

GESTURE = "animations/Stand/Gestures/Hey_1"
LOOPS = ("animations/Stand/BodyTalk/Thinking/ThinkingLoop_1",)


@pytest.fixture
def standing(nao):
    motion = nao.service("ALMotion")
    motion.wakeUp()
    nao.service("ALRobotPosture").goToPosture("Stand", 0.8)
    yield motion
    motion.rest()


def a_loop(behaviors) -> str:
    installed = set(behaviors.getInstalledBehaviors())
    for name in LOOPS:
        if name in installed:
            return name
    pytest.fail(f"none of {LOOPS} installed")


def test_running_a_behavior_moves_the_robot(nao, standing):
    """Run Behavior: blocks for the behavior, which moves the joints its timeline names."""
    behaviors = nao.service("ALBehaviorManager")
    start = standing.getAngles("Body", True)
    widest = 0.0
    done = threading.Event()

    def watch():
        nonlocal widest
        while not done.is_set():
            now = standing.getAngles("Body", True)
            widest = max(widest, max(abs(a - b) for a, b in zip(now, start)))
            time.sleep(0.1)

    watcher = threading.Thread(target=watch)
    watcher.start()
    try:
        began = time.monotonic()
        behaviors.runBehavior(GESTURE)
        took = time.monotonic() - began
    finally:
        done.set()
        watcher.join()
    assert took > 1.0  # it blocked for the gesture
    assert widest > 0.3
    assert not behaviors.isBehaviorRunning(GESTURE)


def test_start_and_stop_a_behavior(nao, standing):
    """Start Behavior returns at once; Behavior State sees it; Stop Behavior ends it."""
    behaviors = nao.service("ALBehaviorManager")
    loop = a_loop(behaviors)
    behaviors.startBehavior(loop)
    try:
        deadline = time.monotonic() + 5
        while not behaviors.isBehaviorRunning(loop) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert behaviors.isBehaviorRunning(loop)
        assert loop in behaviors.getRunningBehaviors()
        time.sleep(1.0)
    finally:
        behaviors.stopBehavior(loop)
    assert not behaviors.isBehaviorRunning(loop)
    assert loop not in behaviors.getRunningBehaviors()


def test_an_unknown_behavior_is_not_installed(nao):
    behaviors = nao.service("ALBehaviorManager")
    assert not behaviors.isBehaviorInstalled("naoqi-sim-e2e/no-such-behavior")


def test_autonomous_abilities_turn_off_and_on(nao):
    """2.8's Autonomous Abilities box."""
    if nao.version.name != "2.8":
        pytest.skip("the Autonomous Abilities box is 2.8's")
    life = nao.service("ALAutonomousLife")
    ability = "AutonomousBlinking"
    was = life.getAutonomousAbilityEnabled(ability)
    try:
        life.setAutonomousAbilityEnabled(ability, False)
        assert not life.getAutonomousAbilityEnabled(ability)
        life.setAutonomousAbilityEnabled(ability, True)
        assert life.getAutonomousAbilityEnabled(ability)
    finally:
        life.setAutonomousAbilityEnabled(ability, was)
