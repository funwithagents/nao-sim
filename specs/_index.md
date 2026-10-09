# nao-sim

nao-sim is a NAO in a box: NAOqi (`naoqi-bin` from the user's own Choregraphe suite, 2.1.4.13 or 2.8.7.4) runs in a local Docker container, and Python 2.7 override modules loaded inside it replace the services the desktop NAOqi lacks, so the container behaves like a NAO in its API on `127.0.0.1:9559`. Any qi client (Choregraphe, existing scripts, client libraries) connects to it exactly as it would to a NAO, with no nao-sim-specific code.

- **Containers**: the NAOqi image per version and a `tts` speech engine. Every NAOqi-specific decision stays there.
- **Host**: dumb devices (the sound card today; microphone, webcam and the perception feed planned), Python 3.12–3.13 with libqi.
- **Simulated world** (planned, optional): the `nao-sim[viewer]` extra pulls nao-viewer, whose sim mode poses the NAO model from nao-sim's NAOqi in a scene and renders the head cameras that nao-sim injects into `ALVideoDevice`.

Built and tested on both versions: the container, the service-replacement mechanism, the speech path (`ALTextToSpeech` replacement, `tts` engine, sound card) and the `NaoSim` status service with the Docker healthcheck. Everything else is planned in [_overview.md](_overview.md), the map of the whole project.

## Specs

<!-- One row per concept spec. Keep the Status column in sync with each spec's `**Status:**` line. -->

| Spec | Description | Status |
|---|---|---|
| [project.md](project.md) | Project structure and tooling: Python version, packaging with uv, layout conventions | Implemented |
| [testing.md](testing.md) | Testing strategy: two-tier `tests/`/`tests-e2e/` split, functional-test philosophy, a live tier that drives its own stack per NAOqi version | Implemented |
| [container.md](container.md) | NAOqi 2.1 and 2.8 images, suite and `animations` package download, package store volume, single-port network layout, compose, the entrypoint's configuration interface, the `io.nao-sim.version` image label | Implemented |
| [service-replacement.md](service-replacement.md) | Loading override modules into NAOqi, `ALModule` vs qi service per version, replacing a built-in, calling host-registered services | Implemented |
| [speech.md](speech.md) | `ALTextToSpeech` replacement: the measured contract per caller, tags, event sequence, timing, stop, fallback clock | Implemented |
| [tts-engine.md](tts-engine.md) | Speech engine container: `POST /say` items to audio with exact marker offsets (Piper, eSpeak NG), streamed to the sound card | Implemented |
| [soundcard.md](soundcard.md) | Host sound card: TCP PCM protocol, newest-stream-wins, stop, `--record`/`--silent`, the `AudioSink` seam (`DevicePlayer`, `NullSink`, `WavSink`, `MemorySink`) | Updated |
| [config.md](config.md) | `NaoSimConfig`: which NAOqi version and which host devices (speech engine, speaker, viewer, camera, microphone), nao-bridge's loader conventions (`from_dict`/`from_json`/`from_json_file`, `ConfigError` with key paths), embedded as nao-bridge's `sim` block | Draft |
| [api.md](api.md) | The `NaoSim` object: built from a config, `start()`/`stop()`/`with` lifecycle over the containers, host devices and simulated world, `url` and `status()`, errors, `fetch_and_build_images` and `check_images` (built); the one implementation behind the CLI, the live tests and nao-bridge's `sim` backend | Stable |
| [cli.md](cli.md) | The `nao-sim` command: `fetch-and-build-images` (built), foreground `run --config`, `cleanup`, `status`, `logs`, `probe` as a thin shell over the API, exit codes | Draft |
| [status-service.md](status-service.md) | `NaoSim` status service: identity of a nao-sim target (versions, device sources, readiness) as a service and ALMemory keys, the entrypoint's readiness guarantees, the Docker healthcheck | Implemented |

[_overview.md](_overview.md) is the overview of nao-sim (goals, architecture, licensing, NAOqi 2.1/2.8 differences, every concept with its state, milestones, open questions). It is reference material without a status; concept specs are extracted from it as work on each concept starts, and the overview section then summarizes and points to the spec. Still only in the overview: the host link, the simulated world (nao-viewer sim mode), `ALAudioDevice`, video injection, `ALAudioPlayer`, perception, speech recognition, capability probe.

Each spec also opens with a YAML **frontmatter** block declaring the `code:` and `tests:` files it governs — the spec → code/tests mapping the spec-drift checks use to scope what they compare. Keep it current when files move, and see [AGENTS.md](../AGENTS.md) ("Spec frontmatter") for the full convention.

### Status legend

- **Not started** — no design decisions made yet
- **Draft** — actively being brainstormed/defined, contains open questions
- **Stable** — design settled, reviewed and validated (open questions are deferrals only), **ready to implement but not necessarily implemented yet**. This is the design-review gate, before code is written.
- **Implemented** — a **Stable** spec that a `Done` plan has built: the code now exists and matches the spec (design and code in sync)
- **Updated** — an **Implemented** spec since edited in a way that needs new code, so the code no longer matches it; a new implementation plan is needed (or in progress) to catch up. Returns to **Implemented** once that plan is `Done`.
