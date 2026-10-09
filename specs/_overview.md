# nao-sim — Overview

nao-sim is a NAO in a box. NAOqi (`naoqi-bin` from the user's own Choregraphe suite, 2.1.4.13 or 2.8.7.4) runs in a local Docker container, and override modules loaded inside it replace the services a desktop virtual robot lacks, so the container behaves like a NAO in its API on `127.0.0.1:9559`. Any qi client (Choregraphe, existing scripts, client libraries) connects to it exactly as it would to a NAO, with no nao-sim-specific code.

It is unofficial and MIT-licensed, not affiliated with Aldebaran, and ships no Aldebaran assets.

This overview is the map of the whole project and the authority for nao-sim; the toolkit-wide document (nao-bridge, nao-sim, nao-viewer) covers cross-package concerns only and defers to it. Each concept gets its own spec (see [_index.md](_index.md)) when work on it starts; until then, its section here is the reference. Sections whose concept has a spec only summarize it and link to it.

## Goals

- Existing qi code, including Choregraphe behaviours, runs on nao-sim on NAOqi 2.1.4.13 and 2.8 and gets speech, audio and camera images through the standard NAOqi services, with their documented methods, events and timing. nao-sim provides what a NAO's hardware provides; perception and speech recognition run in the clients (see [Perception and speech recognition](#perception-and-speech-recognition-on-the-clients)).
- One command (`nao-sim run`, after the one-time `nao-sim fetch-and-build-images`) reaches a running simulated NAO, given Docker and the user's Choregraphe suite, on the platforms the libqi wheels cover (today macOS arm64 and Linux x86_64; see [Packaging](#packaging-and-platforms)).
- No Aldebaran binary, robot package, mesh or derived file lands in the repository, a package or a published image.

## Scope

| In scope | Out of scope |
| --- | --- |
| NAOqi from the user's suite, Docker only, 2.1 and 2.8 | Running NAOqi natively on the host |
| Override modules for the services the desktop NAOqi lacks: speech, audio input, sound files | Reimplementing NAOqi, its walk engine, fall manager, or vision and audio algorithms |
| Host devices: loudspeaker, microphone or WAV replay, webcam or rendered camera | A physics simulation driving NAOqi (no simulator interface exists for it) |
| The simulated world (window, rendered head cameras), through nao-viewer's sim mode | ROS / ROS 2, Webots |
| A capability probe that measures what a NAOqi target offers | Client libraries: they connect to nao-sim as to any NAO (nao-bridge offers nao-sim as its `[sim]` extra and a `sim` backend that runs a `NaoSim`; nao-sim never depends on it) |
|  | The NAO model, the meshes and the 3D rendering: nao-viewer owns them |
|  | Perception and speech recognition: no replacement of `ALFaceDetection`, `ALPeoplePerception`, `ALMovementDetection` or `ALSpeechRecognition`; clients run them on the camera and microphone streams |
|  | Robot packages beyond the `animations` package (sound set, `dialog_*`, dances): the user, or a client such as nao-bridge, installs them as on a robot |

## Architecture

Two containers and one host side. Every NAOqi-specific decision stays in the containers; the host is a set of dumb devices.

| Part | Runs where | Role | Spec |
| --- | --- | --- | --- |
| NAOqi container | Docker, `linux/amd64` | `naoqi-bin` from the user's suite, one image per version, built locally; publishes 9559 only | [container.md](container/container.md) |
| Override modules | Inside NAOqi (Python 2.7) | Replace or add NAOqi services in-process, so in-process callers (`ALAnimatedSpeech`, `ALDialog`) and host clients both reach them: `ALTextToSpeech`, `ALAudioDevice`, `ALAudioPlayer`, the `NaoSim` status service | [service-replacement.md](container/service-replacement.md); one spec per service in [services/](services/) |
| `tts` container | Docker, native architecture | Turns text, marker and pause items into audio with exact marker offsets (Piper, eSpeak NG) and streams it to the host | [tts-engine.md](container/tts-engine.md) |
| Host devices | Host (Python 3), owned by a running `NaoSim` | Audio output (plays the PCM it receives); audio, video and touch inputs planned | [devices.md](host/devices.md), one spec per device in [host/](host/) |
| `NaoSim` object and config (planned) | Host (Python 3), in the caller's process | Built from a `NaoSimConfig`; `start()`/`stop()` run the containers, the host devices and the simulated world. Behind the CLI, the live tests and nao-bridge's `sim` backend | [api.md](runtime/api.md), [config.md](runtime/config.md) |
| Host link (planned) | Containers to host, one TCP port | Carries what qi cannot: microphone PCM into `ALAudioDevice`, its subscriptions out | [devices.md](host/devices.md), "The host link" |
| Simulated world (planned) | Host, nao-viewer's own viewer process, started by `NaoViewer.launch()` | The NAO model posed from nao-sim's NAOqi in a scene, the window, head-camera renders | [viewer.md](host/viewer.md) |
| `nao-sim` CLI | Host | `fetch-and-build-images` (built), `run`, `cleanup`, `status`, `logs`, over the `NaoSim` object | [cli.md](runtime/cli.md) |

- Clients reach every NAOqi service, built-in or replaced, on `127.0.0.1:9559`, as on a NAO. On 2.8, the suite's own `qi-secure-gateway` serves that port and relays the service processes, as on a NAO 6.
- The containers reach the host through `host.docker.internal` (`host-gateway` on Linux). Today only the `tts` container does, to stream speech to the audio output on 9562.
- Host code that talks to NAOqi uses `qi.Session` and `session.service()` from the libqi Python 3 wheels, never `ALProxy`. One exception lives inside the container: an override module that calls a service a host client registered goes through the broker with `naoqi.ALProxy` (see [service-replacement.md](container/service-replacement.md)).

## Status

| Concept | State |
| --- | --- |
| Container, 2.1 and 2.8 | Built and tested ([container.md](container/container.md)) |
| Service replacement mechanism | Built and tested, used by the speech path ([service-replacement.md](container/service-replacement.md)) |
| `ALTextToSpeech` replacement | Built and tested on both versions ([speech.md](services/speech.md)) |
| `tts` container | Built and tested ([tts-engine.md](container/tts-engine.md)) |
| Audio output | Built and tested as the speaker; audio sinks and the rename not built ([audio-output.md](host/audio-output.md)) |
| `NaoSim` status service, healthcheck | Built and tested ([status-service.md](container/status-service.md)) |
| `NaoSimConfig`, `NaoSim` object, CLI | Specified: config and CLI `Draft`, object `Stable` ([config.md](runtime/config.md), [api.md](runtime/api.md), [cli.md](runtime/cli.md)); only `fetch-and-build-images` built. Today the stack is started with `docker compose` (see [README.md](../README.md)) |
| Host link | Draft ([devices.md](host/devices.md)) |
| Audio input, `ALAudioDevice` replacement, microphone gate | Draft ([audio-input.md](host/audio-input.md), [audio-device.md](services/audio-device.md)) |
| Video input | Draft; `putImage` measured on both versions ([video-input.md](host/video-input.md)) |
| Touch input | Draft ([touch-input.md](host/touch-input.md)) |
| `ALAudioPlayer` shim and replacement | Draft; shim approach measured ([audio-player.md](services/audio-player.md)) |
| Simulated world (nao-viewer sim mode) | Built on the nao-viewer side (`NaoViewer` in sim mode, windowed and headless, `camera_frame`); not wired into nao-sim ([viewer.md](host/viewer.md), Draft) |
| Distribution (wheel with the recipes, user data directory) | Specified, not built ([project.md](project.md), "Distribution") |
| CI | Draft ([ci.md](testing/ci.md)) |
| Capability probe | Spike scripts only; deferred (see [below](#capability-probe)) |
| Asset guard | Planned, deferred (see [Licensing](#licensing)) |
| Perception, speech recognition | Not nao-sim's: clients (nao-bridge, planned) |

## Licensing

The code is MIT. Nothing from Aldebaran is in the repository, a package or a published image:

| Asset | Source | How nao-sim uses it |
| --- | --- | --- |
| Choregraphe suite (`naoqi-bin`, the Python 2.7 SDK) | Aldebaran's downloads and GitHub repositories, under Aldebaran's terms | Downloaded from Aldebaran's GitHub repositories into `docker/vendor/<version>/` (gitignored) by `nao-sim fetch-and-build-images`, or placed there by the user, hash-pinned; the image is built and tagged locally and never pushed |
| `animations` package | Only inside the robot system images (`.opn`, public in the same two repositories) | Extracted from the image by `nao-sim fetch-and-build-images` into `docker/vendor/<version>/`, hash-pinned, built into the local image; never in the repository |
| Sound set and other robot packages | The user's own robot (the store that sold them is gone) | Installed by the user into the running sim as on a robot; kept in a local Docker volume |
| NAO meshes and textures (CC BY-NC-ND 4.0) | `ros-naoqi/nao_meshes` installer | Never touched by nao-sim: nao-viewer fetches them after a typed license acceptance and keeps them in the user's data directory |
| libqi and its Python 3 bindings (BSD-3-Clause) | [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python), a fork of Aldebaran's libqi | Prebuilt wheels from the fork's GitHub Releases, a runtime dependency |

- `.gitignore` covers suite tarballs, `docker/vendor/`, meshes and textures. An automated asset guard (tree, wheel, sdist and Docker build context) is planned and deferred: it gets its spec when packaging starts.
- The suite download fetches Aldebaran's own public files to the user's machine, as the user would by hand; nothing is redistributed. See [container.md](container/container.md).

## NAOqi 2.1 and 2.8

Both lines are supported with one host code base; only the override modules are Python 2.7, and each version has its own image and entrypoint defaults. Each image matches a real NAO **on its own version**, not the other image: the two versions' module sets differ on real robots too (2.8's expressivity and dialog packages, 2.1's removed modules). What the desktop suite leaves out of a version but a NAO on it runs is added back where the suite ships it ([container.md](container/container.md), "Matching a NAO's modules").

| | 2.1.4.13 | 2.8.7.4 |
| --- | --- | --- |
| Image | Ubuntu 14.04, boot about 5 s | Ubuntu 16.04, NAO V6 model, boot about 15 s |
| Public port | `naoqi-bin` broker on 9559 | Suite's gateway on 9559, `naoqi-bin` on loopback 9558 |
| Override object model | `naoqi.ALModule`, registered on the broker | `qi.Session` service, `@qi.multiThreaded()` |
| Replacing a built-in | Defer the dependents in autoload, `exit()` the built-in, load, `launchLocal` the dependents | `ALServiceManager` stop the dependents, `exit()` the built-in, load, start them |

Details and measurements: [container.md](container/container.md) and [service-replacement.md](container/service-replacement.md). The desktop `naoqi-bin` has no `ALSystem`, no version key in ALMemory, no `ALAudioDevice`, no face engine and a stub `ALAudioPlayer`. nao-sim fills the identity, audio input and sound-file gaps below; the missing face engine is left to the clients ([Perception and speech recognition](#perception-and-speech-recognition-on-the-clients)).

## Container

Specified in [container.md](container/container.md), including the robot packages: the `animations` package (the `animations/Stand/Gestures/*` behaviours that `ALAnimatedSpeech` runs) is extracted from the public robot image and installed at boot as a system package; the user installs anything else (the sound set) as on a robot, and a volume per version keeps it. Each image also matches the modules a NAO of its version runs: on 2.1 the entrypoint launches the autonomous abilities the desktop suite ships without loading (`ALBasicAwareness`, `ALAutonomousMoves`, blinking, expressiveness), then Autonomous Life after them ("Matching a NAO's modules").

The **`NaoSim` status service** ([status-service.md](container/status-service.md)) is the identity of a nao-sim target: the desktop `naoqi-bin` has no `ALSystem`, so this is how a client learns that the target is nao-sim, the nao-sim and NAOqi versions, which host devices are attached (`NaoSim/Camera/Source`, `NaoSim/Audio/Source`, `none` until the devices are built; `NaoSim/Audio/Channels` comes with the audio input) and whether boot is complete (`NaoSim/Ready`). The Docker healthcheck calls it. nao-viewer already relies on it (service exists means `nao-sim`), so the name and the keys are a contract between the packages. The images will also pin `VideoInput.xml` to `SimulatorCam`, with the video input ([video-input.md](host/video-input.md), "The image side").

## Host services

Specified in [devices.md](host/devices.md): the simulated robot's inputs and outputs, as dumb devices owned by a running `NaoSim` ([api.md](runtime/api.md)) in the process that started it (`nao-sim run`, a test, nao-bridge). Each is named after its role and has its own spec in [host/](host/):

| Device | Spec | Through |
| --- | --- | --- |
| Audio output (loudspeaker, WAV, memory) | [audio-output.md](host/audio-output.md) | Its own TCP protocol on 9562, fed by the `tts` engine and later `ALAudioPlayer` |
| Audio input (WAV replay, host microphone), with the microphone gate | [audio-input.md](host/audio-input.md) | The host link, into the `ALAudioDevice` replacement |
| Video input (nao-viewer render, webcam) | [video-input.md](host/video-input.md) | qi: `ALVideoDevice.putImage` |
| Touch input (clicks in the sim window, the API in tests) | [touch-input.md](host/touch-input.md) | qi: ALMemory |

- The host knows nothing about NAOqi: no tags, no events, no `say()` semantics. Where it needs NAOqi (video injection, touch, the viewer reading joint state), it is an ordinary qi client.
- The **host link** carries only what qi cannot: microphone PCM into the container and the `ALAudioDevice` subscriptions out, on one port the containers connect out to, with the toolkit's framing ([devices.md](host/devices.md), "The host link").
- Each device is built with the end CI can test first (memory sinks, WAV replay, the render camera), then the one that captures the user. The webcam and the microphone are off by default, enabled by explicit options, with an indicator while live.

## Simulated world: nao-viewer

Specified in [viewer.md](host/viewer.md). nao-viewer is a separate package (its own repository) that owns the NAO MuJoCo model, the license-gated meshes and the 3D rendering, a kinematic mirror rather than a physics simulation. nao-sim drives its **sim mode** through its public API (`NaoViewer(config).launch()`, `camera_frame`, `status()`, `close()`), from its own `viewer` block (`{headless, scene, variant}`), behind the `nao-sim[viewer]` extra:

- a window showing the robot posed from nao-sim's NAOqi in a scene (`empty` by default);
- the head-camera renders the video input injects into `ALVideoDevice` (`video_input.source = "render"`), which close the loop: NAOqi moves the head, the viewer renders what that camera sees;
- later, clicks on the robot that the touch input turns into touches.

The viewer process only reads NAOqi; everything NAOqi-specific stays in nao-sim. Without the extra, nao-sim runs with no window and no render camera, and every NAOqi API still works. The live tier and CI run it headless with the render camera from the start ([ci.md](testing/ci.md)).

## Speech

`ALTextToSpeech.say()` is served by a replacement loaded inside NAOqi. It sends each sentence to the `tts` container, which synthesizes it and streams the PCM to the host speaker, and it raises the NAOqi events itself, on its own clock, from the timings the engine returns. Specified in [speech.md](services/speech.md), [tts-engine.md](container/tts-engine.md) and [audio-output.md](host/audio-output.md). The microphone gate, which keeps the robot from hearing itself, belongs to the audio input ([audio-input.md](host/audio-input.md), "Microphone gate"). Kept here: the fallback.

### Fallback: listening to TTS events

If a NAOqi version did not allow replacing the built-in `ALTextToSpeech`, the host would listen to its ALMemory events and speak each sentence. The built-in's simulated clock then decides alone when a sentence ends (0.204 s per token, measured on 2.1), so:

- a blocking `say()` returns before the voice finishes;
- `ALAnimatedSpeech` gestures follow NAOqi's timeline, not the voice, and drift;
- `ALDialog` may take its turn too early.

No such version is known: the replacement works on 2.1 and 2.8. The probe's TTS timing check would size the error for a version that needed it.

## Media: camera and microphone

Clients get camera images and microphone audio through the standard NAOqi services, with NAO conventions throughout: resolutions (QVGA, VGA), colorspace names, the NAO cameras' field of view, microphone names (front, rear, left, right), and timestamps on every frame and chunk. nao-sim publishes its sources in ALMemory, so a client can tell, for example, a mono microphone duplicated to four channels.

| | NAOqi side | Host side |
| --- | --- | --- |
| Video | `ALVideoDevice` in `SimulatorCam` mode, fed with the public `putImage`: no module | [video-input.md](host/video-input.md): nao-viewer render first, webcam after |
| Audio in | A replacement `ALAudioDevice`, [audio-device.md](services/audio-device.md) | [audio-input.md](host/audio-input.md): WAV replay first, host microphone after; the microphone gate |
| Sound files | The `sndfile-play` shim, then a replacement `ALAudioPlayer`, [audio-player.md](services/audio-player.md) | [audio-output.md](host/audio-output.md) |

## Perception and speech recognition: on the clients

nao-sim provides what a NAO's hardware provides (camera images, microphone audio, a loudspeaker, touch) through the standard NAOqi services, and replaces no perception or speech recognition module. Face, people and movement detection and speech recognition run in the clients (nao-bridge plans them) on the frames they read from `ALVideoDevice` and the audio they read from `ALAudioDevice`, so the same code runs on nao-sim and on a real NAO. As a consequence, code that relies on NAOqi's own detectors or recognizer (`FaceDetected` events, `ALDialog`, the Choregraphe face and speech recognition boxes) gets no results on nao-sim.

What was measured on both desktop suites (Oct 8, 2026) stays here as the reference for those clients:

- Neither suite ships a face engine: 2.1 has no `ALFaceDetection`; 2.8 launches `HumanPerception` as `hp.registerWithoutOkao` and it is not running. The face engine only exists in the robot system image.
- `ALPeoplePerception` and `ALMovementDetection` exist on both and run their `ALModularity` processes on the injected frames (bound at 5 Hz, frames read back correctly), yet produce nothing: an empty population on 2.8, no output on 2.1, no movement events even with moving frames. The modularity graph cannot be fed from outside and its programs are compiled into the libraries: a dead end, not a bug.
- Once started, `ALBasicAwareness` subscribes to exactly three inputs on both versions: `PeoplePerception/PopulationUpdated`, `MovementDetection/MovementDetected` and `TouchChanged` (plus preference events). It tracks people with `ALTracker`'s `People` target, which reads the `PeoplePerception/Person/<id>/Position*` keys.
- **The built-in `ALBasicAwareness` and `ALTracker` work on nao-sim once a client publishes the people-perception contract in ALMemory.** Fake-population test (`spike/fake_people.py`): the host inserts `PeoplePerception/PeopleList`, `VisiblePeopleList`, `NonVisiblePeopleList` and the `Person/<id>/` keys (`PositionInTorsoFrame`, `PositionInRobotFrame`, `PositionInWorldFrame`, `Distance`, `AnglesYawPitch`, `IsVisible`, `IsFaceDetected`, `NotSeenSince`, `PresentSince`, `RealHeight`), raises `JustArrived` once and `PopulationUpdated` plus `PeopleDetected` at 5 Hz. On 2.1 and 2.8, `ALBasicAwareness` raises `StimulusDetected "People"` and `HumanTracked 42`, `ALTracker` switches to its servoing target, and the head turns toward the person (HeadYaw 0.74 rad for a person at 0.6 rad). 2.8 briefly reports `HumanLost` then re-tracks, to tune with the update cadence. Both built-ins are kept as they are.
- 2.1 does not autoload `basicawareness`; `ALLauncher.launchLocal("basicawareness")` registers it (only its sound stimulus fails to initialise). On 2.8 it is the `expressivity.basicawareness` package service, running by default. A NAO has it on both versions, so nao-sim's 2.1 entrypoint launches it ([container.md](container/container.md), "Matching a NAO's modules").
- Sound stimulus: 2.8's awareness logs "Desktop detected, ALSoundLocalization won't be used", a hard-coded check. 2.1: with a stub `ALSoundLocalization` registered first, the stimulus initialises, but a `SoundLocated` event raised from the host produced no reaction.

## CLI

Specified in [cli.md](runtime/cli.md).

| Command | Purpose |
| --- | --- |
| `nao-sim fetch-and-build-images [2.1] [2.8]` | Fetch the vendor files, build and verify the images: the one slow step, before `run` ([api.md](runtime/api.md), "Images") |
| `nao-sim run [--config FILE]` | Load a `NaoSimConfig` ([config.md](runtime/config.md); none: the defaults), start a `NaoSim` ([api.md](runtime/api.md)) and stay in the foreground until Ctrl-C, which stops everything |
| `nao-sim cleanup` | Remove the containers a run that died without stopping left behind |
| `nao-sim status` / `nao-sim logs` | Health of the containers, the overrides and the host link |

`nao-sim probe` (the capability report below) is deferred with the probe.

The CLI is a thin shell over the `NaoSim` object: `run` is `NaoSim.from_json_file(FILE).start()` then waiting for Ctrl-C, and every check (Docker, verified images, the viewer extra) happens in `start()`. Today the stack is started with `docker compose` by hand; the live tests' stack helpers (`tests-e2e/support.py`) are the first code that starts and stops it, and move to `NaoSim` once it exists.

## Capability probe

Deferred: the probe gets its spec when the NAOqi 2.8 validation milestone needs committed reports; the live tier checks most of these facts meanwhile. `nao-sim probe` would measure what a NAOqi target offers, from a Python 3 qi client on the host, and saves a JSON report, so the specs rely on measured facts. It runs against the plain container (overrides off) to learn the baseline, and against nao-sim with the overrides on. Reports go to `capabilities/<naoqi-version>-<plain|nao-sim>.json` and are committed (facts only, no Aldebaran content).

| Check | Why it matters |
| --- | --- |
| A module loaded into NAOqi registers a service a host client can call | Foundation of the overrides. 2.1 and 2.8: pass |
| A service registered by a host client can be called from inside the container | `ALAudioDevice` calls `processRemote` on host subscribers. 2.1: pass through the broker; fails from a module's own `qi.Session`. 2.8: to confirm |
| Full service list (`session.services()`) | Which modules exist on this target |
| Smoke calls: `ALTextToSpeech.say`, `ALBehaviorManager.getInstalledBehaviors`, `ALAnimatedSpeech`, `ALPackageManager` | Which high-level modules work |
| `ALAudioDevice` registered; is the name free | How the audio override is installed |
| `ALVideoDevice` accepts `SimulatorCam` and `putImage`; frame read back with `getImageRemote` | Camera injection |
| TTS events and timing: `say()` blocking time, start-to-done delay, events raised | Size of the error if the speech fallback were ever needed |
| The built-in `ALTextToSpeech` can be removed and the name re-registered | The speech path. 2.1 and 2.8: pass |
| Recording proxy: a replacement that forwards every call to the renamed built-in and logs calls, arguments and events, driven by `ALAnimatedSpeech`, a Choregraphe Say box and an `ALDialog` topic | The exact contract per caller, without reading Aldebaran code |
| Perception modules loaded, results from injected frames | Documents for clients that the built-in detectors give nothing on nao-sim ([Perception and speech recognition](#perception-and-speech-recognition-on-the-clients)) |

The spike scripts (`spike/`, local only) cover these checks by hand today.

## Packaging and platforms

Specified in [project.md](project.md) ("Distribution"): Python 3.12–3.13 host code packaged with uv, the container recipes shipped as package data in the wheel and the vendor files in the user data directory, the `viewer` extra, versions baked into the images.

- The libqi wheels exist for macOS 15+ arm64 and Linux x86_64 (glibc 2.34+), Python 3.10–3.13. Installation elsewhere fails by design: nao-sim's host side cannot work without qi. v1 targets these two platforms only; Windows, Intel macOS, Linux arm64 and older systems are on the roadmap, each waiting on wheels from the libqi fork.
- How pip users get the wheels is open ([project.md](project.md), open questions).
- Containers: Docker Engine on Linux, Docker Desktop or OrbStack on macOS (amd64 emulation for the NAOqi images on Apple Silicon; the `tts` container is native). Measured on OrbStack only.

## Testing

Two tiers ([testing.md](testing/testing.md)): a fast, deterministic `tests/` tier with no Docker, and an opt-in `tests-e2e/` tier that builds, starts and stops each version's stack itself. CI ([ci.md](testing/ci.md)) runs both on GitHub's hosted `ubuntu-24.04` runners, with no self-hosted runner, as reachy-mini-bridge's CI does: a static gate, the fast tier, and a live matrix over 2.1 and 2.8 that fetches, builds and caches the images itself (never pushed), with a headless viewer and the render camera once the viewer is built. Downstream repositories (nao-viewer, nao-bridge) pin a nao-sim commit for their own live jobs; nao-sim's CI does not test them.

## Milestones

The toolkit document numbers the milestones across the three packages; nao-sim's share is below, with the toolkit's number.

1. **Validation spike** (done, Oct 8, 2026; toolkit 1): a module loaded into NAOqi serves a host client; a host-registered service is called back from the container; the built-in `ALTextToSpeech` is replaced, with `ALAnimatedSpeech` using the replacement. On 2.1 and 2.8.
2. **Speech path** (done except the gate and subtitles; toolkit 7): `ALTextToSpeech` replacement, `tts` container, audio output, under test on both versions (plan [202610081257](../plans/202610081257_baseline-tests-speech-path.md)).
   - Still to exit: a Choregraphe behaviour with animated speech and the `animations` package runs with gestures on their words; sound files play through the `ALAudioPlayer` shim; reference sentences within the agreed duration tolerance.
3. **nao-sim run and CI** (started; toolkit 2 and 4): status service, healthcheck and `fetch-and-build-images` (done); `NaoSimConfig` and the `NaoSim` object with the audio sinks, `nao-sim run`/`cleanup`/`status`/`logs` ([config.md](runtime/config.md), [api.md](runtime/api.md), [cli.md](runtime/cli.md), [audio-output.md](host/audio-output.md)); CI ([ci.md](testing/ci.md)); the distribution ([project.md](project.md)).
   - Exit: `nao-sim run` works on Linux and macOS; CI green on both versions.
4. **Media** (toolkit 6), in this order: the viewer and the render camera ([viewer.md](host/viewer.md), [video-input.md](host/video-input.md)), so CI tests the camera loop from the start; the host link, `ALAudioDevice` and the audio input with WAV replay and the microphone gate ([devices.md](host/devices.md), [audio-device.md](services/audio-device.md), [audio-input.md](host/audio-input.md)); the `ALAudioPlayer` shim ([audio-player.md](services/audio-player.md)); then the webcam, the host microphone and touch ([touch-input.md](host/touch-input.md)).
   - Exit: a vision script and an audio script written against the standard NAOqi services run unchanged on nao-sim.
5. **NAOqi 2.8 validation** (toolkit 8): the capability probe and its committed reports for 2.1 and 2.8.

Perception and speech recognition are nao-bridge milestones (see the toolkit document); nao-sim's part is the camera and microphone of milestone 4.

## Open questions and risks

Questions that belong to a concept live in its spec; these cross several.

- [ ] **libqi wheels**: distribution to pip users ([project.md](project.md)), and platform coverage (Windows, Intel macOS, Linux arm64, glibc below 2.34, macOS below 15, Python 3.14).
- [ ] **Connect retries**: `qi.Session.connect()` from the libqi 3 wheels fails about once in three against NAOqi 2.1 (`disconnected`, instant); clients retry. The root cause in the fork is open.
- [ ] **libqi fork, legacy clients**: the fork's server binds objects only after a service-0 capability message that libqi 2.1 clients never send, so a 2.1 client opening a fresh connection to a libqi 3 service fails. Not needed by this design; patch only if a use case appears.
- [ ] **Docker Desktop**: everything was measured on OrbStack; Docker Desktop on macOS, Linux and Windows is to confirm.
- [ ] **Speech duration tolerance**: how close `say()` must be to a NAO's own durations (proposed ±20% per sentence), and the reference values ([speech.md](services/speech.md)).
- **Emulation speed**: the NAOqi images run under amd64 emulation on Apple Silicon. Measured boot is about 5 s (2.1) and 15 s (2.8) with no visible lag; the probe records timing if that changes.

Moved to their specs: the sound set ([audio-player.md](services/audio-player.md)), the virtual robot sensors, the sim window's lifecycle and the NAO V6 geometry ([viewer.md](host/viewer.md)), the render-camera throughput ([video-input.md](host/video-input.md)).

## References

- [Simulated robots – Aldebaran 2.1 docs](https://fileadmin.cs.lth.se/robot/nao/doc/dev/tools/robot-simulation.html): what the virtual robot lacks
- [ALTextToSpeech](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/audio/altexttospeech.html) and [ALSpeechRecognition](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/audio/alspeechrecognition.html): TTS and ASR on virtual robots
- [ALVideoDevice](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/vision/alvideodevice.html) and [ALVideoDevice advanced](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/vision/alvideodevice-indepth.html): `SimulatorCam`, `VideoInput.xml`, `putImage`
- [Aldebaran NAO 6 downloads](https://support.aldebaran.com/support/solutions/articles/80001018812-nao-6-downloads): Choregraphe and SDK for NAOqi 2.8
- [aldebaran/NAO-V5-ressources](https://github.com/aldebaran/NAO-V5-ressources) and [aldebaran/nao6-binaries](https://github.com/aldebaran/nao6-binaries): the pinned suite sources
- [cyberbotics/naoqisim](https://github.com/cyberbotics/naoqisim): deprecated Webots bridge, reference for how NAOqi was wired to a simulator
- [Dutch Nao Team labbook 2026](https://staff.science.uva.nl/a.visser/research/nao/Labbook2026.html): download failures, GitHub mirror, bundled Python 2
- [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python): libqi Python 3 bindings, BSD-3-Clause
