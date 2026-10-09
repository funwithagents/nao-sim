# nao-sim

nao-sim is a NAO in a box: NAOqi (`naoqi-bin` from the user's own Choregraphe suite, 2.1.4.13 or 2.8.7.4) runs in a local Docker container, and Python 2.7 override modules loaded inside it replace the services the desktop NAOqi lacks, so the container behaves like a NAO in its API on `127.0.0.1:9559`. Any qi client (Choregraphe, existing scripts, client libraries) connects to it exactly as it would to a NAO, with no nao-sim-specific code.

- **Containers**: the NAOqi image per version and a `tts` speech engine. Every NAOqi-specific decision stays there.
- **Host**: dumb devices named after their role (the audio output today; audio, video and touch inputs planned), Python 3.12–3.13 with libqi. Perception and speech recognition are the clients' job, not nao-sim's.
- **Simulated world** (planned, optional): the `nao-sim[viewer]` extra pulls nao-viewer, whose sim mode poses the NAO model from nao-sim's NAOqi in a scene and renders the head cameras that nao-sim injects into `ALVideoDevice`.

Built and tested on both versions: the container, the service-replacement mechanism, the speech path (`ALTextToSpeech` replacement, `tts` engine, audio output) the `NaoSim` status service with the Docker healthcheck, and `nao-sim run`: the `NaoSim` object with its config, the sim window and the CLI. Everything else is planned in [_overview.md](_overview.md), the map of the whole project.

## Specs

<!-- One row per concept spec, in the section of its folder. Keep the Status column in sync with each spec's `**Status:**` line. -->

### Project

How the repository is built and laid out.

| Spec | Description | Status |
|---|---|---|
| [project.md](project.md) | Project structure and tooling: Python version, packaging with uv, layout conventions; distribution (recipes as package data in the wheel, vendor files in the user data directory, the `viewer` extra, versions) | Updated |

### Runtime: `runtime/`

The host-side front door: the config, the `NaoSim` object and the `nao-sim` command.

| Spec | Description | Status |
|---|---|---|
| [config.md](runtime/config.md) | `NaoSimConfig`: which NAOqi version and which host devices (speech engine, `audio_output`, `audio_input`, `video_input`, viewer with its scene and variant), nao-bridge's loader conventions (`from_dict`/`from_json`/`from_json_file`, `ConfigError` with key paths), embedded as nao-bridge's `sim` block, JSON | Implemented |
| [api.md](runtime/api.md) | The `NaoSim` object: built from a config, `start()`/`stop()`/`with` lifecycle over the containers, host devices and simulated world, `url` and `status()`, errors, `fetch_and_build_images` and `check_images`, `read_status` and `cleanup` for other terminals; the one implementation behind the CLI, the live tests and nao-bridge's `sim` backend | Implemented |
| [cli.md](runtime/cli.md) | The `nao-sim` command: `fetch-and-build-images`, foreground `run --config`, `cleanup`, `status`, `logs` as a thin shell over the API, exit codes; `probe` deferred | Implemented |

### Containers: `container/`

The Docker images and what makes them a NAO: the NAOqi image, how override modules get in, the identity service, the speech engine.

| Spec | Description | Status |
|---|---|---|
| [container.md](container/container.md) | NAOqi 2.1 and 2.8 images, suite and `animations` package download, package store volume, single-port network layout, compose, the entrypoint's configuration interface, the `io.nao-sim.version` image label; matching a NAO's modules per version (autonomous abilities added on 2.1, `autonomouslife` after them) | Implemented |
| [service-replacement.md](container/service-replacement.md) | Loading override modules into NAOqi, `ALModule` vs qi service per version, replacing a built-in, calling host-registered services | Implemented |
| [status-service.md](container/status-service.md) | `NaoSim` status service: identity of a nao-sim target (versions, device sources, readiness) as a service and ALMemory keys, the entrypoint's readiness guarantees, the Docker healthcheck | Implemented |
| [tts-engine.md](container/tts-engine.md) | Speech engine container: `POST /say` items to audio with exact marker offsets (Piper, eSpeak NG), streamed to the audio output | Implemented |

### NAOqi services: `services/`

The NAOqi services nao-sim replaces or adds, as Python 2.7 modules inside NAOqi.

| Spec | Description | Status |
|---|---|---|
| [speech.md](services/speech.md) | `ALTextToSpeech` replacement: the measured contract per caller, tags, event sequence, timing, stop, fallback clock | Implemented |
| [audio-device.md](services/audio-device.md) | `ALAudioDevice` replacement: registered directly, NAO's subscription rules and methods, energy, delivery to `processRemote` through the broker from the host link | Draft |
| [audio-player.md](services/audio-player.md) | `ALAudioPlayer`: the `sndfile-play` shim streaming sound files to the audio output, then a full replacement with mixing and sound sets | Draft |

### Host: `host/`

The simulated robot's inputs and outputs on the host, owned by a running `NaoSim`, each named after its role; and the simulated world.

| Spec | Description | Status |
|---|---|---|
| [devices.md](host/devices.md) | The contract every host device follows (owned by `NaoSim`, config block named after the device, pluggable edge, CI-testable end first, `Source` key, real time, qi when qi suffices) and the host link (port 9563, containers connect out, toolkit framing) | Draft |
| [audio-output.md](host/audio-output.md) | The robot's loudspeaker: TCP PCM protocol, newest stream wins, stop, the `AudioSink` seam (device, null, WAV, memory), playing state for the gate | Implemented |
| [audio-input.md](host/audio-input.md) | The robot's microphones: WAV replay then host microphone, format and mono policy, the microphone gate on the host, messages on the host link | Draft |
| [video-input.md](host/video-input.md) | The robot's head cameras: nao-viewer render then webcam, driven by `ALVideoDevice`'s subscribers, `putImage`, `SimulatorCam` pinned in the images | Draft |
| [touch-input.md](host/touch-input.md) | The robot's touch sensors: clicks in the sim window and an API for tests, written to ALMemory | Draft |
| [viewer.md](host/viewer.md) | The simulated world: nao-viewer's sim mode driven through its public API, which viewer runs, the `viewer` extra, the window closed by the user, headless with the render camera in the live tier and CI | Stable |

### Testing: `testing/`

How nao-sim is verified, locally and in CI.

| Spec | Description | Status |
|---|---|---|
| [testing.md](testing/testing.md) | Testing strategy: two-tier `tests/`/`tests-e2e/` split, functional-test philosophy, a live tier that drives its own stack per NAOqi version | Implemented |
| [ci.md](testing/ci.md) | GitHub Actions on hosted runners: `check`, `fast-tier`, an `e2e-sim` matrix over 2.1 and 2.8 that builds and caches its images, a headless viewer once built; the Python 2.7 check | Draft |

[_overview.md](_overview.md) is the overview of nao-sim (goals, architecture, licensing, NAOqi 2.1/2.8 differences, every concept with its state, milestones, open questions). It is reference material without a status; concept specs are extracted from it as work on each concept starts, and the overview section then summarizes and points to the spec. Still only in the overview: the capability probe and the asset guard (both deferred), and the perception measurements kept for clients.

Each spec also opens with a YAML **frontmatter** block declaring the `code:` and `tests:` files it governs — the spec → code/tests mapping the spec-drift checks use to scope what they compare. Keep it current when files move, and see [AGENTS.md](../AGENTS.md) ("Spec frontmatter") for the full convention.

### Status legend

- **Not started** — no design decisions made yet
- **Draft** — actively being brainstormed/defined, contains open questions
- **Stable** — design settled, reviewed and validated (open questions are deferrals only), **ready to implement but not necessarily implemented yet**. This is the design-review gate, before code is written.
- **Implemented** — a **Stable** spec that a `Done` plan has built: the code now exists and matches the spec (design and code in sync)
- **Updated** — an **Implemented** spec since edited in a way that needs new code, so the code no longer matches it; a new implementation plan is needed (or in progress) to catch up. Returns to **Implemented** once that plan is `Done`.
