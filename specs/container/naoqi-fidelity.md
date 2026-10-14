---
code:
  - docker/naoqi/entrypoint-2.1.sh
tests:
  - tests-e2e/test_modules_live.py
  - tests-e2e/test_absent_live.py
  - tests-e2e/test_motion_live.py
  - tests-e2e/test_leds_live.py
  - tests-e2e/test_robot_info_live.py
---

# NAOqi fidelity

**Status:** Implemented

## Purpose

naoqi-sim behaves like a real NAOqi robot in its API, but its NAOqi is the desktop build from the user's Choregraphe suite, not a robot's. This spec is where the two differ: which modules each image runs compared with a real NAOqi robot of the same version (today a NAO: V4/V5 on 2.1, V6 on 2.8), every difference the desktop build shows, and what naoqi-sim does about each one (keeps it, provides what is missing, could provide it, or lives with it). The images and their boot are in [container.md](container.md); the services naoqi-sim replaces or adds have their own specs ([service-replacement.md](service-replacement.md) for the mechanism).

## Decided

### Matching a real NAOqi robot's modules

Each image matches a real NAOqi robot **on the same NAOqi version**, not the other version's image: real robots differ between 2.1 and 2.8 too. The reference is the robot's own `autoload.ini` in the public robot image (`/etc/naoqi/autoload.ini` on 2.1, `/opt/aldebaran/etc/naoqi/autoload.ini` on 2.8), compared with the desktop suite's (measured Oct 9, 2026):

| Difference between the two images | Cause | On real robots too? |
| --- | --- | --- |
| 2.8 only: `ALMood`, `ALBackgroundMovement`, `ALListeningMovement`, `ALSpeakingMovement`, `ALAnimationPlayer`, `Conversation`, `Knowledge`, `ALUserInfo`, ... | 2.8's `dialog`, `expressivity` and `life` packages | Yes |
| 2.1 only: `ALBonjour`, `ALRedBallTracker`, `ALSegmentation3D`, `ALCloseObjectDetection` | Dropped in 2.8 | Yes |
| `ALBasicAwareness`, `ALAutonomousMoves` and the hidden `_ALExpressiveness`, `_ALAutonomousBlinking` missing on 2.1 | The 2.1 desktop suite ships these libraries but leaves them out of its `autoload.ini` | No: naoqi-sim adds them to its autoload copy ([container.md](container.md), "Entrypoint") |

- Entries the robot autoloads that the desktop suite ships but does not load: 2.1 `expressiveness`, `basicawareness`, `autonomousblinking`, `autonomousmoves`, `aldiagnosis`, `facetracker`, `visionrecognition`, `alchestbutton`, `memorywatcher`, `notificationreader`, `voiceemotionanalysis`, `mecalogger`, `dcm_hal`; 2.8 `aldiagnosis`, `memorywatcher`, `voiceemotionanalysis`. Each loads with `launchLocal` on a running image, which stays healthy (`voiceemotionanalysis` and `mecalogger` register nothing).
- The 2.1 entrypoint adds the four that make the autonomous abilities the robot runs on 2.1 (expressiveness, awareness, blinking, autonomous moves) to its autoload copy, in the robot's order, with `autonomouslife` after them, since the robot loads it after them and it may depend on them ([container.md](container.md), "Entrypoint"). The others are added when a client needs them (open questions); vision modules are not wanted.
- Entries the robot autoloads that the desktop suites do not ship at all (audio input, `ALSystem`, face detection, speech recognition, sound localization, photo and video capture, landmark and barcode detection, infrared, laser...) cannot be added. naoqi-sim provides `ALAudioDevice` itself; `ALSystem` stays absent (its absence tells a client the target is not a real robot); detection and recognition are the clients' ([_overview.md](../_overview.md), "Perception and speech recognition").

### Desktop NAOqi facts

How the desktop NAOqi differs from a real robot's, and what each difference means for naoqi-sim:

- **By design**: naoqi-sim keeps the difference on purpose.
- **Patched**: naoqi-sim provides what the desktop lacks.
- **Patchable**: naoqi-sim could provide it, with the lever named. It is a candidate for a plan once a client needs it.
- **Limitation**: the behavior lives inside a large module naoqi-sim cannot replace, and no input it could provide is known to change it. It stays a limitation of naoqi-sim, with its workaround. Patching or decompiling Aldebaran's binaries is never a lever.

The levers, cheapest first: load or configure what the suite ships; publish the data in ALMemory; replace the service with ours from the autoload ([service-replacement.md](service-replacement.md)), worth it for an API naoqi-sim can implement fully; stub it; provide the input a built-in lacks (a stand-in DCM).

- **By design.** No `ALSystem` service and no version key in ALMemory; `RobotConfig/Body/Type` is absent (2.1 and 2.8). The version (and the fact that the target is naoqi-sim) must come from a naoqi-sim service.
- **Patched.** No `ALAudioDevice` on either version (naoqi-sim adds one, [audio-device.md](../services/audio-device.md)); `ALAudioPlayer` is a stub that spawns `/opt/naoqi/bin/sndfile-play`, which fails in Docker (naoqi-sim replaces it, [audio-player.md](../services/audio-player.md)).
- **Patchable (publish in ALMemory).** 2.1 has `Device/SubDeviceList/*` keys in ALMemory; the 2.8 virtual robot has none, having no DCM. So on 2.8 the joints' temperature keys (`Device/SubDeviceList/<joint>/Temperature/Sensor/Value`, which the Motor Heat and Get Temperature boxes read) are missing (measured Oct 13, 2026). naoqi-sim could publish plausible temperatures, and joint positions from `ALMotion.getAngles`; a stand-in DCM would provide them too (open question 2).
- **Patchable (lever to find). No LED state.** Neither virtual robot has the LEDs' actuator keys (`Device/SubDeviceList/Face/Led/Red/Left/0Deg/Actuator/Value`, ...): `ALLeds` accepts every command (`fadeRGB`, `fade`, `on`, `off`, `setIntensity`, `randomEyes`...) but `getIntensity` raises "Data not found", so a client cannot read the LEDs back (2.1 and 2.8, measured Oct 13, 2026). Where `ALLeds`'s commands go is not known yet; depending on it, naoqi-sim would publish the actuator values, or replace `ALLeds` (31 methods), which would also let the sim window show the LEDs (open question 2).
- **Patchable (publish in ALMemory). No body id.** `Device/DeviceList/ChestBoard/BodyId` (the Get Body ID box) is missing on both versions; naoqi-sim could publish a fixed one.
- **Limitation, for now. Collision protections do not follow their setters** (2.1 and 2.8, measured Oct 14, 2026, arms not in collision, `isCollision("Arms")` = `"none"` on 2.1). `setCollisionProtectionEnabled("Arms", False)` answers true, as documented, but `getCollisionProtectionEnabled("LArm")` and `("RArm")` stay true: self-collision protection stays on, which a NAO allows to disable without owner consent (a Pepper needs it for some chains). `getExternalCollisionProtectionEnabled` answers false for every name (`All`, `Move`, `Arms`, `LArm`, `RArm`) whatever `setExternalCollisionProtectionEnabled` was given. Workaround: none; a client should not rely on reading them back. The logic is `ALMotion`'s, which naoqi-sim cannot replace, and faking the read-back would lie about a protection that does not change. On 2.8 `ALMotion` runs in its local mode without a DCM, which may be the cause (open question 2).
- **Limitation. 2.1: `ALRobotPosture.getPostureFamily()` says "Standing" in Crouch** (after `goToPosture("Crouch")` or `ALMotion.rest()`, also 1.5 s later), while `getPosture()` says "Crouch"; 2.8 says "Crouching" (measured Oct 14, 2026). Workaround: read `getPosture()`. Fixing it would mean replacing `ALRobotPosture`, which drives the postures themselves.
- **Limitation, for now. 2.8: `ALRobotPosture` cannot reliably reach "Sit".** The 2.8 desktop suite has no DCM, so its virtual robot has no inertial sensor (2.1's simulated DCM reports the torso upright), and the posture manager reads the lean of the Stand-to-Sit transition as a perturbation (`PostureManager: Perturbation during gotoPosture` in the log). Measured Oct 13, 2026, `ALMotion.wakeUp()` and `setMaxTryNumber(3)`, `goToPosture("Sit", 0.8)`: from Stand, `False` after 16 to 25 s, usually still in `Stand`, sometimes in `Sit` or `Unknown`; from Crouch, `Sit` reached each time but `True` only some of the time (15 to 21 s). Stand and Crouch work, as every move does on 2.1. Workaround: check `getPosture()` rather than the result, go through Crouch, or test Sit on 2.1. What would change it is a stand-in DCM providing an inertial sensor (`spike/RESULTS.md`, "2.8 Sit"; open question 2).

## Open questions

1. **More added built-ins.** The other shipped-but-not-autoloaded modules (2.1: `aldiagnosis`, `memorywatcher`, `alchestbutton`, `notificationreader`, `facetracker`, `visionrecognition`; 2.8: `aldiagnosis`, `memorywatcher`) are left out until a client needs one.
2. **A stand-in DCM, and where `ALLeds` writes.** Several 2.8 differences may share a root, the missing DCM: the `Device/` keys and joint temperatures, Sit, and possibly the LED state and the collision protections. Whether a minimal stand-in DCM (a module named `DCM`, present before `ALMotion` starts) would lift them, at what cost, and where `ALLeds`'s commands go on each version (a `qicli trace` while it fades), are to investigate before deciding each one ("Desktop NAOqi facts").
