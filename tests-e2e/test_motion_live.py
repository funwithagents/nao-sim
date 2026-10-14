"""The robot's body as the Movement boxes drive it (WakeUp, Rest, Set Stiffness, Hands, Timeline,
Move To, Move Toward, Goto Posture, Apply Posture, Set Anti-Collision, Set Fall Manager, Look At,
Point At), from a host client. Each move is checked on the joint sensors or the odometry, not on
the call's answer (plans/202610132100_api-coverage-from-boxes.md). The Move Along box is left out:
its ALNavigation.moveAlong is Pepper's (NAOqi docs, both versions)."""

import math
import time

import pytest
from support import DESKTOP_FACTS, known_issue

SPEED = 0.8


@pytest.fixture(scope="module", autouse=True)
def rest_at_the_end(nao):
    yield
    nao.service("ALMotion").rest()


@pytest.fixture
def standing(nao):
    """Awake and in Stand, as a box expects the robot before it moves."""
    nao.service("ALMotion").wakeUp()
    posture = nao.service("ALRobotPosture")
    if posture.getPosture() != "Stand":
        posture.goToPosture("Stand", SPEED)
    return nao.service("ALMotion")


def sensed(motion, names) -> list[float]:
    return motion.getAngles(names, True)


def test_wake_up_and_rest(request, nao):
    known_issue(
        request, nao, f"2.1 says Standing in Crouch ({DESKTOP_FACTS})", ("2.1",)
    )
    motion = nao.service("ALMotion")
    motion.wakeUp()
    assert motion.robotIsWakeUp()
    assert min(motion.getStiffnesses("Body")) > 0.9

    motion.rest()
    assert not motion.robotIsWakeUp()
    assert max(motion.getStiffnesses("Body")) < 0.1
    posture = nao.service("ALRobotPosture")
    assert posture.getPosture() == "Crouch"
    assert posture.getPostureFamily() == "Crouching"


def test_set_stiffness(standing):
    standing.stiffnessInterpolation("Head", 0.5, 0.2)
    try:
        assert standing.getStiffnesses("Head") == pytest.approx([0.5, 0.5], abs=0.05)
    finally:
        standing.stiffnessInterpolation("Head", 1.0, 0.2)


def test_hands_open_and_close(standing):
    standing.openHand("LHand")
    assert sensed(standing, "LHand")[0] > 0.7
    standing.closeHand("LHand")
    assert sensed(standing, "LHand")[0] < 0.3


def test_a_joint_reaches_its_target(standing):
    """What a Timeline does: interpolations of joint angles."""
    standing.angleInterpolation("HeadYaw", 0.6, 1.0, True)
    try:
        assert sensed(standing, "HeadYaw")[0] == pytest.approx(0.6, abs=0.05)
    finally:
        standing.angleInterpolation("HeadYaw", 0.0, 0.5, True)


def test_move_to_walks_the_distance(standing):
    before = standing.getRobotPosition(False)
    standing.moveTo(0.2, 0.0, 0.0)
    after = standing.getRobotPosition(False)
    assert math.dist(before[:2], after[:2]) == pytest.approx(0.2, abs=0.05)


def test_move_toward_walks_until_stopped(standing):
    """Forward while it walks, still once stopped. Not its speed: the sims walk 3 to 5 cm in 3 s
    at 0.6, which only a robot could say is right."""
    x, y, theta = standing.getRobotPosition(False)
    standing.moveToward(0.6, 0.0, 0.0)
    try:
        time.sleep(2.0)
        assert standing.moveIsActive()
    finally:
        standing.stopMove()
    standing.waitUntilMoveIsFinished()
    assert not standing.moveIsActive()
    x2, y2, _ = standing.getRobotPosition(False)
    forward = (x2 - x) * math.cos(theta) + (y2 - y) * math.sin(theta)
    assert forward > 0.01


@pytest.mark.parametrize(
    "target, family",
    [("Crouch", "Crouching"), ("StandInit", "Standing"), ("Stand", "Standing")],
)
def test_go_to_posture(request, nao, standing, target, family):
    if target == "Crouch":
        known_issue(
            request, nao, f"2.1 says Standing in Crouch ({DESKTOP_FACTS})", ("2.1",)
        )
    posture = nao.service("ALRobotPosture")
    assert posture.goToPosture(target, SPEED)
    assert posture.getPosture() == target
    assert posture.getPostureFamily() == family


def test_sit_down(nao, standing):
    if nao.version.name == "2.8":
        pytest.xfail(
            "2.8's virtual robot has no inertial sensor, so Sit is unreliable "
            f"({DESKTOP_FACTS})"
        )
    posture = nao.service("ALRobotPosture")
    assert posture.goToPosture("Sit", SPEED)
    assert posture.getPosture() == "Sit"
    assert posture.getPostureFamily() == "Sitting"


def test_apply_posture(nao, standing):
    """The Apply Posture box: straight to the posture, no transition."""
    posture = nao.service("ALRobotPosture")
    assert posture.applyPosture("StandZero", SPEED)
    assert posture.getPosture() == "StandZero"


def test_self_collision_protection_toggles(request, nao, standing):
    """The Set Self Anti-Collision box: set on "Arms", read per arm (the getter takes LArm or RArm)."""
    known_issue(request, nao, f"self-collision protection stays on ({DESKTOP_FACTS})")
    standing.setCollisionProtectionEnabled("Arms", False)
    try:
        assert not standing.getCollisionProtectionEnabled("LArm")
        assert not standing.getCollisionProtectionEnabled("RArm")
    finally:
        standing.setCollisionProtectionEnabled("Arms", True)
    assert standing.getCollisionProtectionEnabled("LArm")


def test_external_collision_protection_reads_back(request, nao, standing):
    """The Set External Anti-Collision box, with its default body part."""
    known_issue(
        request, nao, f"external collision protection reads off ({DESKTOP_FACTS})"
    )
    standing.setExternalCollisionProtectionEnabled("Arms", True)
    assert standing.getExternalCollisionProtectionEnabled("Arms")


def test_fall_manager_reads_back(standing):
    standing.setFallManagerEnabled(True)
    assert standing.getFallManagerEnabled()


def test_look_at_turns_the_head(nao, standing):
    """The Look At box: ALTracker.lookAt a point to the robot's left, in FRAME_TORSO."""
    nao.service("ALTracker").lookAt([1.0, 0.8, 0.4], 0, 0.5, False)
    try:
        assert sensed(standing, "HeadYaw")[0] > 0.4
    finally:
        standing.angleInterpolation(["HeadYaw", "HeadPitch"], [0.0, 0.0], 0.5, True)


def test_point_at_raises_the_arm(nao, standing):
    """The Point At box: ALTracker.pointAt with the right arm, in FRAME_TORSO."""
    down = sensed(standing, "RShoulderPitch")[0]
    nao.service("ALTracker").pointAt("RArm", [0.3, -0.1, 0.25], 0, 0.5)
    assert sensed(standing, "RShoulderPitch")[0] < down - 0.5
