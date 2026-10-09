# nao-sim — Overview

nao-sim is a NAO in a box. NAOqi (`naoqi-bin` from the user's own Choregraphe suite, 2.1.4.13 or 2.8.7.4) runs in a local Docker container, and override modules loaded inside it replace the services a desktop virtual robot lacks, so the container behaves like a NAO in its API on `127.0.0.1:9559`. Any qi client (Choregraphe, existing scripts, client libraries) connects to it exactly as it would to a NAO, with no nao-sim-specific code.

It is unofficial and MIT-licensed, not affiliated with Aldebaran, and ships no Aldebaran assets.

This overview is the map of the whole project and the authority for nao-sim; the toolkit-wide document (nao-bridge, nao-sim, nao-viewer) covers cross-package concerns only and defers to it. Each concept gets its own spec (see [_index.md](_index.md)) when work on it starts; until then, its section here is the reference. Sections whose concept has a spec only summarize it and link to it.

## Goals

- Existing qi code, including Choregraphe behaviours, runs on nao-sim on NAOqi 2.1.4.13 and 2.8 and gets speech, audio, camera images and perception through the standard NAOqi services, with their documented methods, events and timing.
- One command (`nao-sim up`) reaches a running simulated NAO, given Docker and the user's Choregraphe suite, on the platforms the libqi wheels cover (today macOS arm64 and Linux x86_64; see [Packaging](#packaging-and-platforms)).
- No Aldebaran binary, robot package, mesh or derived file lands in the repository, a package or a published image.

## Scope

| In scope | Out of scope |
| --- | --- |
| NAOqi from the user's suite, Docker only, 2.1 and 2.8 | Running NAOqi natively on the host |
| Override modules for the services the desktop NAOqi lacks: speech, audio input, sound files, perception | Reimplementing NAOqi, its walk engine, fall manager, or vision and audio algorithms |
| Host devices: loudspeaker, microphone or WAV replay, webcam or rendered camera | A physics simulation driving NAOqi (no simulator interface exists for it) |
| The simulated world (window, rendered head cameras), through nao-viewer's sim mode | ROS / ROS 2, Webots |
| A capability probe that measures what a NAOqi target offers | Client libraries: they connect to nao-sim as to any NAO (nao-bridge offers nao-sim as its `[sim]` extra; nao-sim never depends on it) |
|  | The NAO model, the meshes and the 3D rendering: nao-viewer owns them |

## Architecture

Two containers and one host side. Every NAOqi-specific decision stays in the containers; the host is a set of dumb devices.

| Part | Runs where | Role | Spec |
| --- | --- | --- | --- |
| NAOqi container | Docker, `linux/amd64` | `naoqi-bin` from the user's suite, one image per version, built locally; publishes 9559 only | [container.md](container.md) |
| Override modules | Inside NAOqi (Python 2.7) | Replace or add NAOqi services in-process, so in-process callers (`ALAnimatedSpeech`, `ALDialog`) and host clients both reach them | [service-replacement.md](service-replacement.md) |
| `tts` container | Docker, native architecture | Turns text, marker and pause items into audio with exact marker offsets (Piper, eSpeak NG) and streams it to the host | [tts-engine.md](tts-engine.md) |
| Host sound card | Host (Python 3) | Plays the PCM it receives; `--silent`/`--record` for tests | [soundcard.md](soundcard.md) |
| Host services (planned) | Host (Python 3) | Microphone, camera, perception feed, link to the containers | [Host services](#host-services) |
| Simulated world (planned) | Host, its own process (`nao-viewer sim`) | The NAO model posed from nao-sim's NAOqi in a scene, the window, head-camera renders | [Simulated world: nao-viewer](#simulated-world-nao-viewer) |
| `nao-sim` CLI (planned) | Host | `up`, `down`, `status`, `logs`, `probe` | [CLI](#cli) |

- Clients reach every NAOqi service, built-in or replaced, on `127.0.0.1:9559`, as on a NAO. On 2.8, the suite's own `qi-secure-gateway` serves that port and relays the service processes, as on a NAO 6.
- The containers reach the host through `host.docker.internal` (`host-gateway` on Linux). Today only the `tts` container does, to stream speech to the sound card on 9562.
- Host code that talks to NAOqi uses `qi.Session` and `session.service()` from the libqi Python 3 wheels, never `ALProxy`. One exception lives inside the container: an override module that calls a service a host client registered goes through the broker with `naoqi.ALProxy` (see [service-replacement.md](service-replacement.md)).

## Status

| Concept | State |
| --- | --- |
| Container, 2.1 and 2.8 | Built and tested ([container.md](container.md)) |
| Service replacement mechanism | Built and tested, used by the speech path ([service-replacement.md](service-replacement.md)) |
| `ALTextToSpeech` replacement | Built and tested on both versions; microphone gate and subtitles not built ([speech.md](speech.md)) |
| `tts` container | Built and tested ([tts-engine.md](tts-engine.md)) |
| Host sound card | Built and tested ([soundcard.md](soundcard.md)) |
| `NaoSim` status service, healthcheck | Built and tested ([status-service.md](status-service.md)) |
| Host link and host services | Planned; the sound card's protocol predates the design |
| `ALAudioDevice` replacement | Planned |
| Video injection | Measured (`putImage` works on both versions), not built |
| `ALAudioPlayer` shim and replacement | Measured (shim approach), not built |
| Perception replacements | Measured (fake population drives awareness on both versions), not built |
| CLI | Planned; today the stack is started with `docker compose` (see [README.md](../README.md)) |
| Simulated world (nao-viewer sim mode) | Designed on the nao-viewer side (draft); not built on either side |
| Capability probe | Spike scripts only |
| Speech recognition | v2 |

## Licensing

The code is MIT. Nothing from Aldebaran is in the repository, a package or a published image:

| Asset | Source | How nao-sim uses it |
| --- | --- | --- |
| Choregraphe suite (`naoqi-bin`, the Python 2.7 SDK) | Aldebaran's downloads and GitHub repositories, under Aldebaran's terms | Downloaded from Aldebaran's GitHub repositories into `docker/vendor/<version>/` (gitignored) by `nao-sim-fetch-suite`, or placed there by the user, hash-pinned; the image is built and tagged locally and never pushed |
| `animations` package | Only inside the robot system images (`.opn`, public in the same two repositories) | Extracted from the image by `nao-sim-fetch-suite` into `docker/vendor/<version>/`, hash-pinned, built into the local image; never in the repository |
| Sound set and other robot packages | The user's own robot (the store that sold them is gone) | Installed by the user into the running sim as on a robot; kept in a local Docker volume |
| NAO meshes and textures (CC BY-NC-ND 4.0) | `ros-naoqi/nao_meshes` installer | Never touched by nao-sim: nao-viewer fetches them after a typed license acceptance and keeps them in the user's data directory |
| libqi and its Python 3 bindings (BSD-3-Clause) | [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python), a fork of Aldebaran's libqi | Prebuilt wheels from the fork's GitHub Releases, a runtime dependency |

- `.gitignore` covers suite tarballs, `docker/vendor/`, meshes and textures. An automated asset guard (tree, wheel, sdist and Docker build context) is planned.
- The suite download fetches Aldebaran's own public files to the user's machine, as the user would by hand; nothing is redistributed. See [container.md](container.md).

## NAOqi 2.1 and 2.8

Both lines are supported with one host code base; only the override modules are Python 2.7, and each version has its own image and entrypoint defaults.

| | 2.1.4.13 | 2.8.7.4 |
| --- | --- | --- |
| Image | Ubuntu 14.04, boot about 5 s | Ubuntu 16.04, NAO V6 model, boot about 15 s |
| Public port | `naoqi-bin` broker on 9559 | Suite's gateway on 9559, `naoqi-bin` on loopback 9558 |
| Override object model | `naoqi.ALModule`, registered on the broker | `qi.Session` service, `@qi.multiThreaded()` |
| Replacing a built-in | Defer the dependents in autoload, `exit()` the built-in, load, `launchLocal` the dependents | `ALServiceManager` stop the dependents, `exit()` the built-in, load, start them |

Details and measurements: [container.md](container.md) and [service-replacement.md](service-replacement.md). The desktop `naoqi-bin` has no `ALSystem`, no version key in ALMemory, no `ALAudioDevice`, no face engine and a stub `ALAudioPlayer`; nao-sim fills each of these gaps below.

## Container

Specified in [container.md](container.md), including the robot packages: the `animations` package (the `animations/Stand/Gestures/*` behaviours that `ALAnimatedSpeech` runs) is extracted from the public robot image and installed at boot as a system package; the user installs anything else (the sound set) as on a robot, and a volume per version keeps it.

The **`NaoSim` status service** ([status-service.md](status-service.md)) is the identity of a nao-sim target: the desktop `naoqi-bin` has no `ALSystem`, so this is how a client learns that the target is nao-sim, the nao-sim and NAOqi versions, which host devices are attached (`NaoSim/Camera/Source`, `NaoSim/Audio/Source`, `NaoSim/Perception/Source`, `none` until the device specs are built; `NaoSim/Audio/Channels` comes with `ALAudioDevice`) and whether boot is complete (`NaoSim/Ready`). The Docker healthcheck calls it. nao-viewer already relies on it (service exists means `nao-sim`, version from `NaoSim/Version`), so the name and the keys are a contract between the packages. Still to build:

- **Camera source**: pin `VideoInput.xml` to `SimulatorCam` in the image. The desktop suites already accept `putImage` as shipped (see [Media](#media-camera-and-microphone)).

## Host services

- One Python 3 process started by `nao-sim up`: webcam capture, microphone capture or WAV replay, the sound card, the camera feeder (webcam or sim renders into `ALVideoDevice`), optional local speech recognition. It launches and drives the simulated world as a separate process (see [Simulated world: nao-viewer](#simulated-world-nao-viewer)).
- The host knows nothing about NAOqi: no tags, no events, no `say()` semantics. It is a set of devices. Where the host does need NAOqi (camera injection, the perception feed; the sim process reading joint state), it is an ordinary qi client.
- **Host link** (design, not built): the override modules and the `tts` container connect out to the host on one TCP port, with length-prefixed messages (`u32 header_len | u32 payload_len | JSON header | raw payload`, the framing nao-viewer's sim protocol already uses):
  - host to container: microphone PCM chunks, camera frames already in NAO format;
  - container to host: PCM to play (speech, later sound files), subscription changes (which camera, rate and resolution are wanted; whether audio is subscribed), stop-playback requests, playing state for the microphone gate.
- As built, speech output does not use this link: the `tts` container streams to the sound card with its own one-connection-per-stream protocol ([soundcard.md](soundcard.md)). Whether the link replaces it or sits next to it is the first decision of the host-link spec.
- Webcam and microphone are off by default, enabled by explicit options, with an indicator in the sim window while live.

## Simulated world: nao-viewer

nao-viewer is a separate package (its own repository) that owns the NAO MuJoCo model, the license-gated meshes and the 3D rendering. It is a kinematic mirror, not a physics simulation: it reads joint angles and the torso pose from any NAOqi over qi (`ALMotion.getAngles("Body", True)` and `getTransform("Torso", 1, True)` at 50 Hz), writes them into the model and renders at 60 Hz. nao-sim uses its **sim mode**, whose design lives with nao-viewer:

| | nao-viewer (sim process) | nao-sim (host process) |
| --- | --- | --- |
| Process | `nao-viewer sim --naoqi URL [--scene FILE] [--port N] [--headless] [--variant V]`, its own process, so MuJoCo's window, OpenGL and the macOS `mjpython` constraint stay out of nao-sim | Launches it, and stops it on `nao-sim down` |
| Robot pose | Reads it from nao-sim's NAOqi over qi, like any client | Nothing: NAOqi is the source of truth |
| Scene | Loads and renders it (`scenes/default.xml`: floor, lights, a table with objects in front of the robot) | Chooses the scene file (`nao-sim up --scene FILE`) |
| Head cameras | Renders RGB frames of `CameraTop`/`CameraBottom` on request, at the robot's current pose | Decides which camera, resolution and rate from `ALVideoDevice.getSubscribers()`, converts to the NAO colorspace, calls `putImage` |
| Model variant | Mesh model if the user ran `nao-viewer fetch-meshes`, else the primitive model | Nothing: the meshes never pass through nao-sim |

- nao-sim drives it with `nao_viewer.sim_client`: `Sim.launch(naoqi_url, scene=..., headless=...)` starts the process and waits for its ready line; `camera_frame(camera, width, height)` returns an RGB frame with the pose sequence and age it was rendered at; `close()` stops it; a window closed by the user raises `SimClosed`. The client imports neither MuJoCo nor qi.
- The sim process never writes to NAOqi. Everything NAOqi-specific on the device side (colorspaces, subscriptions, `putImage`) stays in nao-sim, which keeps the sim generic.
- With `--camera render` the loop closes: NAOqi moves the head, the sim renders what that camera sees, nao-sim injects it, NAOqi serves it to its subscribers.
- Planned sim operations that nao-sim will consume: touch events from clicks on the robot (`ALTouch`, an awareness stimulus) and human figures in scenes with their positions (the [perception](#perception) feed without a webcam). Each comes as a new operation of the sim protocol.
- **Dependency**: through an extra, `nao-sim[viewer]`, which pulls nao-viewer (and with it MuJoCo). Without it, nao-sim runs with no window and no render camera: every NAOqi API, speech, microphone, webcam camera and perception from the webcam all work, which suits CI and servers; what is lost is the robot in its scene, the render camera, touch from clicks and people placed in the scene. nao-viewer depends on libqi only, never on nao-sim, so the chain stays one-way. `nao-bridge[sim]` pulls `nao-sim[viewer]`, so the full experience stays one install.
- **`headless` setting** (nao-sim's configuration, default `false`; `--headless` on `up`): it decides the window, and the camera decides whether the sim runs at all:

  | `headless` | Camera | Sim process | Needs `nao-sim[viewer]` |
  | --- | --- | --- | --- |
  | `false` | any | `nao-viewer sim` with its window | Yes |
  | `true` | `render` | `nao-viewer sim --headless` (no window, also on macOS without `mjpython`) | Yes |
  | `true` | `webcam` or none | None | No |

  When the extra is needed and missing, `nao-sim up` fails before starting anything, with a message naming the extra.

## Speech

`ALTextToSpeech.say()` is served by a replacement loaded inside NAOqi. It sends each sentence to the `tts` container, which synthesizes it and streams the PCM to the host sound card, and it raises the NAOqi events itself, on its own clock, from the timings the engine returns. Specified in [speech.md](speech.md), [tts-engine.md](tts-engine.md) and [soundcard.md](soundcard.md). Kept here: the fallback and the microphone gate.

### Fallback: listening to TTS events

If a NAOqi version did not allow replacing the built-in `ALTextToSpeech`, the host would listen to its ALMemory events and speak each sentence. The built-in's simulated clock then decides alone when a sentence ends (0.204 s per token, measured on 2.1), so:

- a blocking `say()` returns before the voice finishes;
- `ALAnimatedSpeech` gestures follow NAOqi's timeline, not the voice, and drift;
- `ALDialog` may take its turn too early.

No such version is known: the replacement works on 2.1 and 2.8. The probe's TTS timing check would size the error for a version that needed it.

### Microphone gate

The host has both the microphone and the exact audio it plays, on one clock. The default is a gate: the microphone is muted while speech plays, plus a 300 ms tail (configurable). Real echo cancellation is possible later for the same reason. The gate needs the playing state from the sound card and the host link (see [soundcard.md](soundcard.md), open questions).

## Media: camera and microphone

Clients get camera images and microphone audio through the standard NAOqi services, with NAO conventions throughout: resolutions (QVGA, VGA), colorspace names, the NAO cameras' field of view, microphone names (front, rear, left, right), and timestamps on every frame and chunk. nao-sim publishes its sources in ALMemory, so a client can tell, for example, a mono microphone duplicated to four channels.

| | Source on nao-sim |
| --- | --- |
| Video | `ALVideoDevice` in `SimulatorCam` mode, fed with `putImage` from the host webcam or the sim's head-camera renders |
| Audio | A replacement `ALAudioDevice`, fed by the host microphone or a WAV file |

### Video injection

- No container module: `ALVideoDevice.putImage(camera, width, height, rgb)` is public, and the host calls it over qi. Verified on 2.1 and 2.8: injected frames come back through `subscribeCamera`/`getImageRemote`.
- The host reads `ALVideoDevice.getSubscribers()` and the subscribers' resolution and frame rate to decide what to produce.
- Sources: webcam (OpenCV, cropped and scaled to the NAO field of view) or render (`Sim.camera_frame` from nao-viewer's sim mode, RGB at the robot's current pose; see [Simulated world](#simulated-world-nao-viewer)). Either way nao-sim converts to the subscriber's colorspace before `putImage`.
- Fallback if a version refused `putImage`: replace `ALVideoDevice` itself (subscribe, `getImageRemote`, `getImagesRemote`, camera parameters), as for audio.

### ALAudioDevice replacement

The desktop NAOqi has no audio input, and neither version registers `ALAudioDevice`, so an override module registers one directly (no built-in to remove).

- Methods: `subscribe`, `unsubscribe`, `setClientPreferences`, `openAudioInputs`, `closeAudioInputs`, `enableEnergyComputation`, `getFrontMicEnergy` and the other microphones, `getOutputVolume`, `setOutputVolume`, `isInputMuted`.
- Delivery: each subscriber's `processRemote(nbOfChannels, nbOfSamplesByChannel, timeStamp, buffer)` with interleaved 16-bit samples, called through the broker (`naoqi.ALProxy(subscriber)`), which reaches a host subscriber over the socket the host opened. Verified on 2.1; 2.8 is to confirm ([service-replacement.md](service-replacement.md), open questions).
- The same rules as NAOqi's device: 48 kHz with all 4 channels, or 16 kHz with all channels or one; invalid combinations refused the same way. Chunk size and cadence match NAOqi's; the reference values are still to be supplied.
- Sources: the host microphone over the host link, or WAV replay, including 4-channel recordings, for repeatable tests.
- Mono policy: duplicate to all channels (default) or silence the missing ones, published as `NaoSim/Audio/Channels` next to `NaoSim/Audio/Source` (the values are this spec's to define).
- Muted by the microphone gate while the robot speaks.

### Sound files: ALAudioPlayer

- The desktop `ALAudioPlayer` is a stub on 2.1 and 2.8 alike: `playFile`, `playFileInLoop`, `playFileFromPosition` (each with a volume and pan overload) and `pause(id)`; no `loadFile`/`play`, `stop(id)`, `stopAll`, `playSine` or sound sets.
- It plays by spawning `/opt/naoqi/bin/sndfile-play <file>` and blocks until that process exits; in Docker the binary fails for lack of a sound device. nao-sim installs a shim at that path that streams the file to the host sound card and exits when playback ends, so `playFile` blocks for the real duration with no NAOqi change (measured with a sleep stand-in).
- The Choregraphe box library only calls `playFileFromPosition`, `playFileInLoop` and `stop(id)` (the Play Sound File box, embedded by every sound-playing box); animations never touch `ALAudioPlayer`. The shim covers the library except `stop(id)`.
- A full `ALAudioPlayer` replacement (same pattern as `ALAudioDevice`, PCM over the host link) comes later, for `stop(id)`, `loadFile`/`play`, `playSine` and the sound sets that `^runSound`/`^startSound` in animated speech need.
- The sound card plays one stream at a time, so speech and sound files do not mix yet ([soundcard.md](soundcard.md), open questions).

## Perception

Measured on both desktop suites (Oct 8, 2026): the built-in detectors produce nothing on nao-sim, but `ALBasicAwareness` and `ALTracker` work, as long as the people-perception contract is published in ALMemory. So nao-sim replaces the detectors' API surface, runs detection on the host, and feeds the real awareness and tracking modules.

### What was measured

- Neither suite ships a face engine: 2.1 has no `ALFaceDetection`; 2.8 launches `HumanPerception` as `hp.registerWithoutOkao` and it is not running. The face engine only exists in the robot system image.
- `ALPeoplePerception` and `ALMovementDetection` exist on both and run their `ALModularity` processes on the injected frames (bound at 5 Hz, frames read back correctly), yet produce nothing: an empty population on 2.8, no output on 2.1, no movement events even with moving frames. The modularity graph cannot be fed from outside and its programs are compiled into the libraries: a dead end, not a bug.
- Once started, `ALBasicAwareness` subscribes to exactly three inputs on both versions: `PeoplePerception/PopulationUpdated`, `MovementDetection/MovementDetected` and `TouchChanged` (plus preference events). It tracks people with `ALTracker`'s `People` target, which reads the `PeoplePerception/Person/<id>/Position*` keys.
- Fake-population test (`spike/fake_people.py`): the host inserts `PeoplePerception/PeopleList`, `VisiblePeopleList`, `NonVisiblePeopleList` and the `Person/<id>/` keys (`PositionInTorsoFrame`, `PositionInRobotFrame`, `PositionInWorldFrame`, `Distance`, `AnglesYawPitch`, `IsVisible`, `IsFaceDetected`, `NotSeenSince`, `PresentSince`, `RealHeight`), raises `JustArrived` once and `PopulationUpdated` plus `PeopleDetected` at 5 Hz. On 2.1 and 2.8, `ALBasicAwareness` raises `StimulusDetected "People"` and `HumanTracked 42`, `ALTracker` switches to its servoing target, and the head turns toward the person (HeadYaw 0.74 rad for a person at 0.6 rad). 2.8 briefly reports `HumanLost` then re-tracks, to tune with the update cadence.
- 2.1 does not autoload `basicawareness`; `ALLauncher.launchLocal("basicawareness")` registers it (only its sound stimulus fails to initialise). On 2.8 it is the `expressivity.basicawareness` package service, running by default.

### Design

| Module | nao-sim | Why |
| --- | --- | --- |
| `ALFaceDetection` | Replacement fed by host detections; publishes `FaceDetected` in NAOqi's layout | No engine in the suites; applications and Choregraphe boxes read `FaceDetected` |
| `ALPeoplePerception` | Replacement: the ALMemory contract above, the events, and the methods subscribers call (`subscribe`, `unsubscribe`, `setFaceDetectionEnabled`, `getTimeBeforePersonDisappears`...); built-in removed like `ALTextToSpeech` (2.1: not autoloaded; 2.8: `ALServiceManager`) | Built-in produces nothing on injected frames; its outputs are what awareness and applications consume |
| `ALMovementDetection` | Replacement publishing `MovementDetection/MovementDetected` from host frame differencing | Built-in produces nothing on injected frames; awareness stimulus |
| `ALBasicAwareness` | Built-in, kept (2.1: loaded with `launchLocal`) | Works on the published contract |
| `ALTracker` | Built-in, kept | Works with the `People` target on the published keys |
| `ALTouch`, `TouchChanged` | Built-in; touch events come from clicks in the sim window (a planned sim operation) | Awareness stimulus |
| Sound stimulus | None in v1 | 2.8: awareness logs "Desktop detected, ALSoundLocalization won't be used", a hard-coded check. 2.1: with a stub `ALSoundLocalization` registered first, the stimulus initialises, but a `SoundLocated` event raised from the host produced no reaction; left open |

- The detection runs on the host, from the webcam or the rendered scene (OpenCV or MediaPipe, with the head pose read over qi to turn image positions into torso-frame positions; human figures in the sim scene, with their positions from the sim, give detections without a webcam). Awareness only reads ALMemory, so any qi client may also publish the contract itself.
- The replacements publish their source in ALMemory (`NaoSim/Perception/*`).
- The exact value layouts of `FaceDetected`, `PeopleDetected`, `PopulationUpdated` and `MovementDetected` are copied from the version's documentation at implementation time; awareness tolerates the `PeopleDetected`-style tuple for `PopulationUpdated`.

## Speech recognition (v2)

An optional `ALSpeechRecognition` replacement in the container, backed by a host recognizer (Vosk or Whisper) on the microphone stream: `setVocabulary`, `subscribe`, `WordRecognized` and `SpeechDetected` behave as NAOqi's, so `ALDialog` and existing recognition code run on nao-sim.

## CLI

| Command | Purpose |
| --- | --- |
| `nao-sim up --naoqi 2.1\|2.8 --suite PATH [--camera webcam:0\|render] [--audio mic\|wav:FILE] [--scene FILE] [--headless]` | Build the image if needed, start the containers and the host services, and launch the sim (with `nao-sim[viewer]`; `--headless` overrides the `headless` setting, see [Simulated world](#simulated-world-nao-viewer)) |
| `nao-sim down` | Stop everything |
| `nao-sim status` / `nao-sim logs` | Health of the containers, the overrides and the host link |
| `nao-sim probe` | Capability report (see below) |

The first `up` checks Docker and asks for the suite path. Today the stack is started with `docker compose` by hand; the live tests' stack helpers (`tests-e2e/support.py`) are the first code that starts and stops it, and should call the CLI once it exists.

## Capability probe

`nao-sim probe` measures what a NAOqi target offers, from a Python 3 qi client on the host, and saves a JSON report, so the specs rely on measured facts. It runs against the plain container (overrides off) to learn the baseline, and against nao-sim with the overrides on. Reports go to `capabilities/<naoqi-version>-<plain|nao-sim>.json` and are committed (facts only, no Aldebaran content).

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
| Perception modules loaded, results from injected frames | See [Perception](#perception) |

The spike scripts (`spike/`, local only) cover these checks by hand today.

## Packaging and platforms

- Python 3.12–3.13 host code, packaged with uv ([project.md](project.md)), the same range and platforms as nao-viewer. Runtime dependencies: `numpy`, `sounddevice`, `qi` (the libqi wheels); planned: `opencv-python-headless` (webcam) and the optional `viewer` extra (nao-viewer, for the sim window and the render camera). nao-sim installs and runs on its own; nao-bridge, a separate package, offers it as its `[sim]` extra.
- The libqi wheels exist for macOS 15+ arm64 and Linux x86_64 (glibc 2.34+), Python 3.10–3.13. Installation elsewhere fails by design: nao-sim's host side cannot work without qi. v1 targets these two platforms only; Windows, Intel macOS, Linux arm64 and older systems are on the roadmap, each waiting on wheels from the libqi fork.
- How pip users get the wheels is open: uv resolves them from the fork's GitHub Releases through `[tool.uv.sources]`, but those sources do not reach a published package's metadata, where a plain `qi` would resolve to Aldebaran's older `qi` 3.1.5 on PyPI. Options: a find-links URL, a package index on GitHub Pages, or PyPI under a distinct name.
- Containers: Docker Engine on Linux, Docker Desktop or OrbStack on macOS (amd64 emulation for the NAOqi images on Apple Silicon; the `tts` container is native). Measured on OrbStack only.

## Testing

Two tiers ([testing.md](testing.md)): a fast, deterministic `tests/` tier with no Docker, and an opt-in `tests-e2e/` tier that builds, starts and stops each version's stack itself. Planned:
- hosted CI for the fast tier and the asset guard;
- a self-hosted nightly runner holding the suites for the live tier, running audio, video and speech tests with WAV and image fixtures.

## Milestones

1. **Validation spike** (done, Oct 8, 2026): a module loaded into NAOqi serves a host client; a host-registered service is called back from the container; the built-in `ALTextToSpeech` is replaced, with `ALAnimatedSpeech` using the replacement. On 2.1 and 2.8.
2. **Speech path** (done except gate and subtitles): `ALTextToSpeech` replacement, `tts` container, host sound card, under test on both versions (plan [202610081257](../plans/202610081257_baseline-tests-speech-path.md)).
   - Still to exit: a Choregraphe behaviour with animated speech and the `animations` package runs with gestures on their words; sound files play through the `ALAudioPlayer` shim; reference sentences within the agreed duration tolerance.
3. **Container and probe** (started): `NaoSim` status service, healthcheck and entrypoint hardening (done, [status-service.md](status-service.md)); `nao-sim up`/`down`, the host-link spec, the probe with committed reports for 2.1 and 2.8.
   - Exit: `nao-sim up` works on Linux and macOS; capability reports committed.
4. **Media**: video injection (webcam and render), the sim window through `nao-sim[viewer]`, `ALAudioDevice` replacement, microphone gate.
   - Exit: a vision script and an audio script written against the standard NAOqi services run unchanged on nao-sim.
5. **Perception**: `ALFaceDetection`, `ALPeoplePerception` and `ALMovementDetection` replacements backed by host detection, feeding the built-in awareness and tracking; human figures in world scenes.
   - Exit: a face-tracking script and a basic-awareness behaviour run unchanged on nao-sim (webcam or render).
6. **Speech recognition (v2)**: `ALSpeechRecognition` replacement backed by a host recognizer.
   - Exit: an `ALDialog` conversation runs on nao-sim with the host microphone.

## Open questions and risks

- [ ] **Sound set**: confirm the user's `soundsetaldebaran` installs into the running sim and that `^runSound` finds it once `ALAudioPlayer` is replaced.
- [ ] **libqi wheels**: distribution to pip users, and platform coverage (Windows, Intel macOS, Linux arm64, glibc below 2.34, macOS below 15, Python 3.14).
- [ ] **Connect retries**: `qi.Session.connect()` from the libqi 3 wheels fails about once in three against NAOqi 2.1 (`disconnected`, instant); clients retry. The root cause in the fork is open.
- [ ] **libqi fork, legacy clients**: the fork's server binds objects only after a service-0 capability message that libqi 2.1 clients never send, so a 2.1 client opening a fresh connection to a libqi 3 service fails. Not needed by this design; patch only if a use case appears.
- [ ] **Docker Desktop**: everything was measured on OrbStack; Docker Desktop on macOS, Linux and Windows is to confirm.
- [ ] **Speech duration tolerance**: how close `say()` must be to a NAO's own durations (proposed ±20% per sentence), and the reference values.
- [ ] **Virtual robot sensors**: what `getAngles(..., True)` and the ALMemory sensor keys return on the desktop NAOqi (likely the commanded values); matters for the sim's pose and the render camera.
- [ ] **Sim lifecycle**: whether closing the sim window restarts the sim or means `nao-sim down` (nao-viewer's client only reports `SimClosed`; the decision is nao-sim's).
- [ ] **Render-camera throughput**: the sim protocol pulls one frame per request (0.9 MB per VGA frame over loopback). Two cameras at 30 fps may need a streaming operation or shared memory on the nao-viewer side; to decide with measurements.
- [ ] **NAO V6 geometry**: nao-viewer's model is V5 (camera field of view 47.64° vertical). Whether 2.8 (NAO V6) needs its own model is open on the nao-viewer side.
- **Emulation speed**: the NAOqi images run under amd64 emulation on Apple Silicon. Measured boot is about 5 s (2.1) and 15 s (2.8) with no visible lag; the probe records timing if that changes.

## References

- [Simulated robots – Aldebaran 2.1 docs](https://fileadmin.cs.lth.se/robot/nao/doc/dev/tools/robot-simulation.html): what the virtual robot lacks
- [ALTextToSpeech](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/audio/altexttospeech.html) and [ALSpeechRecognition](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/audio/alspeechrecognition.html): TTS and ASR on virtual robots
- [ALVideoDevice](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/vision/alvideodevice.html) and [ALVideoDevice advanced](https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/vision/alvideodevice-indepth.html): `SimulatorCam`, `VideoInput.xml`, `putImage`
- [Aldebaran NAO 6 downloads](https://support.aldebaran.com/support/solutions/articles/80001018812-nao-6-downloads): Choregraphe and SDK for NAOqi 2.8
- [aldebaran/NAO-V5-ressources](https://github.com/aldebaran/NAO-V5-ressources) and [aldebaran/nao6-binaries](https://github.com/aldebaran/nao6-binaries): the pinned suite sources
- [cyberbotics/naoqisim](https://github.com/cyberbotics/naoqisim): deprecated Webots bridge, reference for how NAOqi was wired to a simulator
- [Dutch Nao Team labbook 2026](https://staff.science.uva.nl/a.visser/research/nao/Labbook2026.html): download failures, GitHub mirror, bundled Python 2
- [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python): libqi Python 3 bindings, BSD-3-Clause
