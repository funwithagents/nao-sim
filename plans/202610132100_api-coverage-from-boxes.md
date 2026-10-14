# API coverage from the Choregraphe boxes

**Status:** Done

Implements the live tier's rule in [testing.md](../specs/testing/testing.md) ("Live tier: the tests drive the stack") more widely: naoqi-sim behaves like a NAO in its API, so the live tier checks the features a NAO user calls, not only the services naoqi-sim replaces. The list of features comes from the Choregraphe box library of each version's suite; each feature gets a test written as a Python 3 libqi client on the host, which checks an outcome observed somewhere other than the API it called where it can. This first step writes the tests and measures how long they take, to decide whether the live tier splits into a fast tier (PRs, `main`) and a full one (nightly or by hand). The tiers were decided from that measurement (step 4).

Built-ins are tested like our replacements: the desktop `naoqi-bin` is not the robot's build (2.8 has no DCM, 2.1's suite leaves modules unloaded), so a built-in failing on naoqi-sim is a gap too. Who owns the service decides only what a failure leads to: a fix in naoqi-sim, or a known issue in the spec with its workaround and a strict `xfail` pointing to it.

## Inventory (box library scan, Oct 13, 2026)

2.1.4.13: 160 boxes; 2.8.7.4: 357 (most of them 2.8's dialog animation timelines). Grouped by feature, with the services the box scripts call. Boxes with no NAOqi call (flow control, math, data edition, Get Date, e-mail, Internet Connection) are left out.

| Feature (boxes) | Services and keys | Versions | Test |
|---|---|---|---|
| Say, Animated Say, Set Language | `ALTextToSpeech`, `ALAnimatedSpeech` | Both | `test_speech_live.py` (existing) |
| Play Sound | `ALAudioPlayer` | Both (2 boxes on 2.1, 16 on 2.8) | `test_audio_player_live.py` (existing) |
| Set Speaker Vol. | `ALAudioDevice.setOutputVolume` | Both | `test_sound_live.py` |
| Record Sound | `ALAudioDevice.startMicrophonesRecording`/`stopMicrophonesRecording` | Both | `test_sound_live.py` |
| Dialog, Choice | `ALDialog` | Both | `test_sound_live.py` (Dialog) |
| Select Camera | `ALVideoDevice.setActiveCamera` | 2.8 (2.1: `setParam`) | `test_robot_info_live.py` |
| Get Data, Insert Data, Raise Event, Remove Data, Subscribe to Event | `ALMemory` | Both | `test_memory_live.py` |
| Expression Watcher | `ALExpressionWatcher` | 2.8 | `test_memory_live.py` |
| Run/Start/Stop Behavior, Behavior State | `ALBehaviorManager` | Both | `test_behaviors_live.py` |
| Autonomous Abilities | `ALAutonomousLife.setAutonomousAbilityEnabled` | 2.8 | `test_behaviors_live.py` |
| WakeUp, Rest, Motor On/Off, Set Stiffness, Hands | `ALMotion` | Both | `test_motion_live.py` |
| Timeline, animations | `ALMotion` (angle interpolation), `ALBehaviorManager` | Both | `test_motion_live.py`, `test_behaviors_live.py` |
| Move To, Move Toward, Walk Toward | `ALMotion` | Both | `test_motion_live.py` (Move Along's `ALNavigation.moveAlong` is Pepper's in the docs of both versions: not tested) |
| Goto Posture, Apply Posture, Posture Family, Robot Posture, Stand Up, Sit Down | `ALRobotPosture` | Both | `test_motion_live.py` |
| Set Self/External Anti-Collision, Set Fall Manager | `ALMotion` | Both | `test_motion_live.py` |
| Look At, Point At | `ALTracker` | Both | `test_motion_live.py` |
| Motor Heat, Get Temperature | `ALMemory` `Device/SubDeviceList/<joint>/Temperature/Sensor/Value` | Both | `test_robot_info_live.py` |
| Eye/Ear LEDs, Set LEDs, Single LED, Blink, Random Eyes, Twinkle | `ALLeds` | Both | `test_leds_live.py` |
| Battery, Has Hardware, Get Body ID | `ALBattery`, `ALRobotModel`, `Device/DeviceList/ChestBoard/BodyId` | Both | `test_robot_info_live.py` |
| Sonar | `ALSonar`, `Device/SubDeviceList/US/*` | Both | `test_robot_info_live.py` |
| Tactile Head/Hands, Bumpers, Foot Contact, Fall Detector | ALMemory events | Both | `test_robot_info_live.py` (events declared; raising them is [touch-input.md](../specs/host/touch-input.md), Draft) |
| Basic Awareness | `ALBasicAwareness` | Both | `test_modules_live.py` (existing) |
| Reboot, Shutdown, Get Name | `ALSystem` | Both | `test_absent_live.py` (absent by design, [container.md](../specs/container/container.md)) |
| Speech Reco., Face Detection/Reco., Learn Face, NAOMark, Vision Reco., Take Picture, Record Video, Sound Loc., Sound Peak, Is Backlit, Is In Darkness, IR, Tablet, Get Age/Expression/Mood/Smile/Gender | `ALSpeechRecognition`, `ALFaceDetection`, `ALLandMarkDetection`, `ALVisionRecognition`, `ALPhotoCapture`, `ALVideoRecorder`, `ALSoundLocalization`, `ALSoundDetection`, `ALBacklightingDetection`, `ALDarknessDetection`, `ALInfrared`, `ALTabletService`, `ALFaceCharacteristics` | Both | `test_absent_live.py` (the suites do not ship them; perception is the clients') |
| Trackers (Face, Red Ball, People, Sound, Movement, LandMark), World Representation, Compass Move To | `ALTracker`, `ALRedBallTracker`, `ALWorldRepresentation`, `ALVisualCompass` | Both | Not in this step: need perception results naoqi-sim does not produce |

## Scope

- `tests-e2e/test_memory_live.py` — ALMemory data and events, `ALExpressionWatcher` (2.8)
- `tests-e2e/test_motion_live.py` — stiffness, hands, joints, walking, postures, safety settings, `ALTracker` look and point
- `tests-e2e/test_leds_live.py` — `ALLeds` fades and animations
- `tests-e2e/test_behaviors_live.py` — start/stop/state of behaviors, their moves, autonomous abilities
- `tests-e2e/test_sound_live.py` — speaker volume, recording, a dialog topic
- `tests-e2e/test_robot_info_live.py` — battery, model, body id, temperatures, sonar, sensor events, camera selection
- `tests-e2e/test_absent_live.py` — services a NAO has and naoqi-sim does not, per version
- `tests-e2e/support.py` — `copy_out`; `known_issue`, a strict expected failure on the versions given, whose reason points to where the issue is documented
- `specs/container/naoqi-fidelity.md` ("Desktop NAOqi facts"), `specs/services/audio-device.md` (open question 3) — the known issues the tests mark

## Steps

1. Write the tests above, each asserting what a NAO does.
2. Run the whole live tier on both versions with `--durations=0`; record the time per version, per file, and the slowest tests, against the baseline (the live tier before this plan).
3. Sort the failures: a naoqi-sim gap to fix (later plan), or a known issue to document with a strict `xfail`. Done Oct 14, 2026, after checking the doubtful ones against the NAOqi docs and on both sims:
   - **Known issues of the desktop virtual robots**, in naoqi-fidelity.md's "Desktop NAOqi facts", marked with `known_issue` (21 tests): no LED state (`getIntensity` raises; 6 tests per version), no body id, 2.8's missing joint temperatures, collision protections that do not follow their setters (self-collision stays on, external reads off; 2 per version), 2.1's posture family "Standing" in Crouch (2).
   - **naoqi-sim's own gaps**, marked with `known_issue` pointing to audio-device.md's open questions (4): `setOutputVolume` keeps the value only (open question 2), no `startMicrophonesRecording` (open question 3).
   - **Test faults** (3): `ALNavigation.moveAlong` is Pepper's, so its test is removed (2); `getCollisionProtectionEnabled` takes `LArm` or `RArm`, not `Arms`; `moveToward` checked on forward progress, not a speed only a robot could confirm (1).
   - The mocked keys (LED state, body id, 2.8's temperatures) and the `ALAudioDevice` gaps are candidates for later plans; fixing one turns its strict `xfail` into a failure, which removes the mark.
4. With the user, decide the tiers (fast on PRs and `main`, full nightly or by hand) and write them into [testing.md](../specs/testing/testing.md) and [ci.md](../specs/testing/ci.md). Decided Oct 14, 2026: **one live tier, always run**, the tests per feature in it (testing.md, "Live tier"); a CI live entry took 10 to 12 minutes of its 45 before them.

## Measurements

Oct 13, 2026, Apple Silicon Mac with OrbStack, both versions one after the other:

- The live tier before this plan: **621 s**, 122 tests. The end-to-end `naoqi-sim run` and install tests and the sim window take 60 to 70 s each per version, the restarts 30 s.
- The new tests alone: **253 s**, 98 tests, each version's stack start (about 30 s) included. Most take 1 to 6 s; motion (waking up, postures, walking) is the slow part.

The first run had 33 failures; 5 were test faults fixed at once, 2.8's `ALDialog` holding a stale `ALTextToSpeech` (the one naoqi-sim bug) was fixed by plan 202610140900 and again by plan 202610141100, and the remaining 28 are sorted in step 3.

## Result (Oct 14, 2026)

The whole live tier, both versions, every change in: 2.1, 91 passed, 8 skipped, 13 expected failures; 2.8, 94 passed, 6 skipped, 13 expected failures (the 25 `known_issue` tests and 2.8's Sit); no failure, no unexpected pass. A first try of the 2.1 half stopped at its start on "127.0.0.1:9559 is taken" while the image was being verified, with nothing of ours left running; free minutes later, cause not found.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`, and `uv run pytest tests-e2e` on both versions. `Done` once the failures are sorted and the tiers decided.
