---
code:
tests:
---

# Touch input

**Status:** Draft

## Purpose

The robot's touch sensors as a host device ([devices.md](devices.md)): the three head tactile sensors, the hand sensors, the foot bumpers and the chest button. On nao-sim a person touches the robot by clicking it in the sim window ([viewer.md](viewer.md)), and a test touches it through the API, so code that reacts to touch (Choregraphe's tactile head boxes, `ALBasicAwareness`'s touch stimulus, a client's own handlers) runs as on a NAO.

## Decided

### Where touches come from

- **Clicks in the sim window.** nao-viewer reports a click on a sensor's body part (a planned operation of its protocol, so it raises nao-viewer's protocol version); `NaoSim` turns it into a press, released when the mouse button is.
- **The API, for tests.** A test presses a sensor without a window or a mouse, for example `await sim.touch("Head/Touch/Front", duration_s=0.2)` on the `NaoSim` object ([api.md](../runtime/api.md) gains it with the plan that builds this spec). A headless CI run uses this path ([ci.md](../testing/ci.md)).

### The NAOqi side

- No service is replaced: the device is an ordinary qi client writing ALMemory, as for the video input.
- What the device writes is what a NAO's sensors produce and its clients read: the sensor's value key (`Device/SubDeviceList/<sensor>/Sensor/Value`, 1.0 pressed, 0.0 released) and the events derived from it (`FrontTactilTouched`, `MiddleTactilTouched`, `RearTactilTouched`, `HandRightBackTouched` and the other hand sensors, `RightBumperPressed`, `LeftBumperPressed`, `ChestButtonPressed`, and `TouchChanged` with the list of changed body parts). Which of them the desktop NAOqi derives itself from the value key, and which the device must raise, is to measure (open question 1).
- `ALBasicAwareness` subscribes to `TouchChanged` on both versions (measured, [_overview.md](../_overview.md), "Perception and speech recognition"), so a click can make the robot look at it.

## Open questions

1. **What the desktop NAOqi derives.** Whether writing a sensor's value key makes `ALSensors`/`ALTouch` raise the touch events on 2.1 and 2.8, or whether the device raises every event itself. To measure before this spec can be `Stable`.
2. **A source key.** Whether the device publishes `NaoSim/Touch/Source` (`viewer`, `api`) like the other inputs. It would extend the `NaoSim` service's contract ([status-service.md](../container/status-service.md)), which changes only with a coordinated release.
3. **Clickable parts.** Which bodies of nao-viewer's model map to which sensors, and how a click on the hand or the foot is told apart from a click on the robot as a whole; decided with nao-viewer.
