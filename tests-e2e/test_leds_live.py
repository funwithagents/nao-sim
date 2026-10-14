"""The LEDs as the LEDs boxes drive them (Eye LEDs, Ear LEDs, Set LEDs, Single LED, Blink, Random
Eyes, Twinkle), from a host client: each change is read back on the LEDs it targets
(plans/202610132100_api-coverage-from-boxes.md). Neither desktop virtual robot keeps the LEDs'
state, so every read-back is a known issue until naoqi-sim provides it."""

import time

import pytest
from support import DESKTOP_FACTS, known_issue

NO_LED_STATE = f"no LED state, getIntensity raises ({DESKTOP_FACTS})"


@pytest.fixture
def leds(nao):
    service = nao.service("ALLeds")
    yield service
    service.reset("AllLeds")


def colour(leds, group: str, channel: str) -> list[float]:
    """Intensities of the group's LEDs of one colour (Red, Green or Blue)."""
    names = [n for n in leds.listGroup(group) if f"/{channel}/" in n]
    assert names, f"no {channel} LED in {group}"
    return [leds.getIntensity(n) for n in names]


def test_the_robot_has_its_led_groups(leds):
    groups = set(leds.listGroups())
    assert {"FaceLeds", "EarLeds", "ChestLeds", "FeetLeds", "AllLeds"} <= groups


def test_eyes_fade_to_a_colour(request, nao, leds):
    known_issue(request, nao, NO_LED_STATE)
    leds.fadeRGB("FaceLeds", 0xFF0000, 0.1)
    assert min(colour(leds, "FaceLeds", "Red")) > 0.9
    assert max(colour(leds, "FaceLeds", "Green")) < 0.1
    assert max(colour(leds, "FaceLeds", "Blue")) < 0.1


def test_a_named_colour(request, nao, leds):
    known_issue(request, nao, NO_LED_STATE)
    leds.fadeRGB("FaceLeds", "blue", 0.1)
    assert min(colour(leds, "FaceLeds", "Blue")) > 0.9
    assert max(colour(leds, "FaceLeds", "Red")) < 0.1


def test_ears_fade_to_an_intensity(request, nao, leds):
    known_issue(request, nao, NO_LED_STATE)
    leds.fade("EarLeds", 0.3, 0.1)
    names = leds.listGroup("EarLeds")
    assert [leds.getIntensity(n) for n in names] == pytest.approx(
        [0.3] * len(names), abs=0.05
    )


def test_a_single_led(request, nao, leds):
    known_issue(request, nao, NO_LED_STATE)
    name = leds.listGroup("ChestLeds")[0]
    leds.setIntensity(name, 0.7)
    assert leds.getIntensity(name) == pytest.approx(0.7, abs=0.05)


def test_off_and_on(request, nao, leds):
    known_issue(request, nao, NO_LED_STATE)
    leds.off("FaceLeds")
    assert max(colour(leds, "FaceLeds", "Red")) < 0.1
    leds.on("FaceLeds")
    assert min(colour(leds, "FaceLeds", "Red")) > 0.9


def test_random_eyes_lasts_its_duration_and_changes_the_eyes(request, nao, leds):
    known_issue(request, nao, NO_LED_STATE)
    leds.fadeRGB("FaceLeds", 0x000000, 0.0)
    start = time.monotonic()
    leds.randomEyes(1.0)
    assert time.monotonic() - start == pytest.approx(1.0, abs=0.5)
    lit = colour(leds, "FaceLeds", "Red") + colour(leds, "FaceLeds", "Green")
    assert max(lit) > 0.0
