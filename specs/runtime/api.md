---
code:
  - src/nao_sim/sim.py
  - src/nao_sim/stack.py
  - src/nao_sim/__init__.py
  - src/nao_sim/errors.py
  - src/nao_sim/docker_images.py
  - src/nao_sim/audio_output.py
  - docker/compose.yaml
  - tests-e2e/conftest.py
  - tests-e2e/support.py
tests:
  - tests/test_sim.py
  - tests/test_stack.py
  - tests/test_docker_images.py
  - tests-e2e/test_naosim_live.py
  - tests-e2e/test_docker_images_live.py
  - tests-e2e/test_speech_live.py
---

# API: the simulated NAO (`NaoSim`)

**Status:** Implemented

## Purpose

`NaoSim` is the one object that runs a simulated NAO on the host: built from a [config](config.md), its `start()` brings up the containers, the host devices and the simulated world, and its `stop()` takes them all down. Every way of running nao-sim goes through it, so there is one implementation of the stack's lifecycle:

- the `nao-sim` CLI ([cli.md](cli.md)), whose `run` loads a config file, starts a `NaoSim` and stays in the foreground;
- the live tests (`tests-e2e/`), which build their stacks from configs instead of driving `docker compose` themselves;
- nao-bridge's `sim` backend (`{"backend": "sim", "sim": {…}}`, the block a `NaoSimConfig`), which awaits a `NaoSim`'s start, connects its ordinary qi backend to `url` and stops it with the bridge; it has no other sim-specific behaviour;
- any Python caller that wants a NAO for the duration of a script or a test.

It replaces the overview's "one host process started by `nao-sim up`" (now `nao-sim run`): the host services are what a running `NaoSim` owns. A client of the simulated robot never needs it: once started, nao-sim is reached at `sim.url` with any qi client, as a NAO.

## Decided

### Construction

- `NaoSim(config: NaoSimConfig | NaoqiVersion | None = None, *, sink: AudioSink | None = None)`. With no config it uses `NaoSimConfig()` ([config.md](config.md)). A bare version string is shorthand for `NaoSimConfig(naoqi=NaoqiSettings(version=...))`, so `NaoSim("2.8")` is the one-liner.
- `sink` is where the audio output's audio goes ([audio-output.md](../host/audio-output.md), "Audio sinks"). Without one, the config's `audio_output` block picks it: `play` a `DevicePlayer`, `silent` a `NullSink`, `record` a `WavSink`. A test passes a `MemorySink` and asserts on the audio actually played. As in tts-engine, the sink is fixed for the object's lifetime.
- `NaoSim.from_dict(data)`, `from_json(text)` and `from_json_file(path)` build the config, then the object (they take the same `sink=`).
- Constructing it does nothing else: no Docker call, no thread, no port opened.
- `config` (read-only) and `running: bool`.

### Lifecycle

The API is **async**, as `NaoBridge`: `await sim.start()`, `await sim.stop()`, `async with NaoSim(...) as sim:`. Blocking work (Docker, qi calls) runs in `asyncio.to_thread`; the host devices run on their own threads, so nothing they do blocks the caller's event loop. nao-bridge's `sim` backend awaits it directly; the CLI wraps it in `asyncio.run`.

**`await start()`** runs these steps in order, and returns once the robot is ready:

1. **Environment checks**, before anything starts, each failing with its own error (see "Errors"):
   - Docker answers;
   - the images are there: the version's NAOqi image and the `tts` image exist, carry the installed nao-sim version (image label `io.nao-sim.version`), were built from the recipes as they are now (`io.nao-sim.recipes`) and were verified by `fetch_and_build_images` (see "Images"). `start()` never downloads or builds;
   - the `viewer` extra is installed when the config needs it (`headless = false`, or `video_input.source = "render"`; the error names the extra), and the `NaoViewerConfig` built from the `viewer` block is valid (nao-viewer's own check of the scene, re-raised as a `ConfigError` with key `viewer.scene`);
   - every configured source is built (see [config.md](config.md), "Sources not built yet") and its file exists (`audio_input.wav`);
   - ports 9559, 9562 and, once the audio input is built, the host link's 9563 are free (another nao-sim, a hand-started stack or audio output).
2. **Audio output**: start the audio output ([audio-output.md](../host/audio-output.md)) in-process, feeding the sink, and open the host link ([devices.md](../host/devices.md), "The host link") once a device uses it.
3. **Containers**: `docker compose up -d` (no build) for the `tts` service and the version's NAOqi service, with the environment generated from the config (`NAO_SIM_TTS_ENGINE` = `speech.engine`, the version's profile, `2.1` or `2.8`). The compose project is always `nao-sim`.
4. **Ready**: wait until the NAOqi container is `healthy` ([status-service.md](../container/status-service.md), "Healthcheck"), up to `naoqi.ready_timeout_s`. A container that exits or turns `unhealthy` fails the start at once, with the end of its log in the error. Verified images can still fail here (a volume, the host), so this wait happens on every start.
5. **Host devices**: the video input and the audio input, as the config's sources ask ([video-input.md](../host/video-input.md), [audio-input.md](../host/audio-input.md)). Each writes its `NaoSim/*/Source` key.
6. **Simulated world**: when the config calls for it ([viewer.md](../host/viewer.md), "Which viewer runs"), build a `NaoViewer` in sim mode from the `viewer` block and `url`, and `launch()` it (in `asyncio.to_thread`; nao-viewer's API is synchronous). Its `LaunchError` fails the start like any other step.

**The window closed by the user** stops the viewer only: the robot keeps running, as a NAO does when nobody watches it, so a nao-bridge app or a test that owns the `NaoSim` never loses its robot to a click. A `NaoSim` notices it from a thread waiting on the viewer (`NaoViewer.wait()`) and logs it once, at warning level, saying the robot is still running; it does not reopen the window. What the render camera does then is the video input's business ([video-input.md](../host/video-input.md)).

If any step fails, everything already started is stopped, in reverse order, and the error propagates. Calling `start()` on a running `NaoSim` raises `NaoSimError`.

**`await stop()`** stops the simulated world, the host devices, the containers (`docker compose down`, keeping the package store volumes) and the audio output, in that order. It carries on through every step even if one fails, then raises the first failure. It is a no-op when not running, and `start()` may follow it.

**`async with NaoSim(...) as sim:`** runs `start()` then `stop()` on every way out.

### Images: `fetch_and_build_images`

Everything slow or downloaded happens once, before any start, in `await fetch_and_build_images(versions=None)` (CLI: `nao-sim fetch-and-build-images [2.1] [2.8]`, [cli.md](cli.md)); with no versions, both. For each version, in order:

1. **Fetch** the vendor files: the pinned suite and `animations.pkg`, with the rules of [container.md](../container/container.md) ("Fetching the vendor files": kept when the hash matches, `.part` downloads, extraction from the robot image). It replaces the former `nao-sim-fetch-suite` command.
2. **Build** the version's NAOqi image and the `tts` image with the installed nao-sim version as build argument (`NAO_SIM_VERSION`) and as the label `io.nao-sim.version`, and the digest of the recipes as the label `io.nao-sim.recipes`: SHA-256 over every file under `docker/` with its relative path, leaving out `vendor/` (pinned by hash already), hidden files and Python caches. Docker's cache keeps a rebuild cheap.
3. **Verify**: boot the version's containers (compose project `nao-sim`) until the NAOqi one is `healthy` (within 240 s) and the `tts` engine answers its `/health`, then take them down, whatever happened. The verified image IDs are recorded (`images.json`, see "Files on disk"). A build that does not boot is reported with the end of its log and not recorded.

An unknown version is a `ValueError`. Docker is checked first (`DockerUnavailableError`), and each verification needs port 9559 free (`PortInUseError`); the audio output's 9562 is not used by a boot, so a running audio output does not stop it.

So `start()` only checks: an image missing or not verified raises `ImagesMissingError`, an image built by another nao-sim version or from other recipes raises `ImagesOutdatedError` (its override modules are stale, or `docker/` was edited since); both name the command to run. Working on `docker/modules/` means rerunning `fetch-and-build-images`; the live tier runs it only for a version whose images fail `check_images`.

### Files on disk

| What | From a checkout | From an installed wheel |
| --- | --- | --- |
| Recipes (Dockerfiles, compose, entrypoint, healthcheck, `modules/`, `tts/`) | `docker/` | Package data inside `nao_sim` (no Aldebaran file, so allowed in the wheel) |
| Vendor files (suites, `animations.pkg`) | `docker/vendor/<version>/` | `platformdirs.user_data_dir("nao-sim")/vendor/<version>/` |
| Build context | `docker/` | The same user data directory: `fetch_and_build_images` assembles the context there, recipes copied next to the vendor files |
| `images.json` (verified image IDs) | `docker/vendor/images.json` (gitignored with the vendor files) | Next to the vendor files |

The checkout layout is today's. The wheel layout, and how the recipes become package data, are detailed in [project.md](../project.md), "Distribution", and built with it (that spec is `Updated` until then).

### What a running `NaoSim` offers

| Member | Returns | Meaning |
| --- | --- | --- |
| `url` | `str` | `tcp://127.0.0.1:9559`, the address any qi client connects to |
| `await status()` | `NaoSimStatus` | Read from the `NaoSim` service over qi, with the connect retry libqi 3 needs against 2.1: `version`, `naoqi_version`, `ready`, `camera_source`, `audio_source` |
| `config` | `NaoSimConfig` | The config it was built from |
| `running` | `bool` | Between a successful `start()` and `stop()` |

- `NaoSim` holds no qi session of its own for clients: callers open their own (`qi.Session().connect(sim.url)`), exactly as on a NAO. `status()` opens and closes one.
- `url` and `status()` raise `NotRunningError` when not running.

### Without a `NaoSim` object

Two functions serve the commands run from another terminal than the one that started nao-sim ([cli.md](cli.md)), so the CLI holds no Docker or qi logic of its own:

- **`await read_status() -> StackStatus`**: the state of whatever runs on this machine. `containers` lists each container of the `nao-sim` compose project with its service, state and health (empty when nothing runs); `naoqi` is the `NaoSimStatus` read from the `NaoSim` service on `tcp://127.0.0.1:9559` (with the connect retry), or `None` when no NAOqi container is `healthy`. `NaoSim.status()` uses the same reader for its `NaoSimStatus`.
- **`await cleanup() -> list[str]`**: removes what a `NaoSim` that died without stopping left behind (killed, crashed): `docker compose --profile '*' down` on the `nao-sim` project, keeping the package store volumes, and returns the names of the containers removed. If a nao-sim is still running (port 9562, the audio output's, is taken), it removes nothing and raises `NaoSimError` saying so.

Both check Docker first (`DockerUnavailableError`).

### Errors

| Error | Raised for |
| --- | --- |
| `NaoSimError(RuntimeError)` | The base of nao-sim's own errors; raised as such for lifecycle misuse (a double `start()`) |
| `NotRunningError(NaoSimError)` | `url` or `status()` when not running |
| `DockerUnavailableError`, `ImagesMissingError`, `ImagesOutdatedError`, `MissingExtraError`, `DeviceNotBuiltError`, `PortInUseError` (each a `NaoSimError`) | Step 1 of `start()`, each naming what to do (start Docker, run `nao-sim fetch-and-build-images`, `pip install nao-sim[viewer]`, which device is missing, which port is taken) |
| `BootError(NaoSimError)` | The NAOqi container exited, turned `unhealthy` or was not `healthy` within `ready_timeout_s` (at start or at verification); carries the end of its log |
| `FetchError(NaoSimError)`, `ImageBuildError(NaoSimError)` | `fetch_and_build_images`: a download or hash failure (naming the file), a failed `docker build` (with the end of its output) |

`ConfigError` ([config.md](config.md)) comes from the loaders, before a `NaoSim` exists.

### Naming

The `NaoSim` *class* (`nao_sim.NaoSim`, on the host) keeps the name of the `NaoSim` *service* inside NAOqi ([status-service.md](../container/status-service.md)), which nao-viewer already relies on: the class starts the stack, the service reports on it from inside, and `status()` reads the service. Specs and logs say "the `NaoSim` object" or "the `NaoSim` service".

### Front door

`from nao_sim import NaoSim` re-exports what a caller needs: `NaoSim`, `NaoSimStatus`, `fetch_and_build_images`, `read_status` and `StackStatus`, `cleanup`, the config classes (`NaoSimConfig` and its blocks, the `Literal` types), the audio sinks (`AudioSink`, `DevicePlayer`, `NullSink`, `WavSink`, `MemorySink`), `ConfigError` and the errors above. Library modules only use `logging.getLogger(__name__)`; `logging.basicConfig` belongs to the CLI.

### One nao-sim per machine

Ports 9559 and 9562 are fixed, the compose project name is fixed and the containers have fixed names, so one `NaoSim` runs per machine. A second `start()` (in another process or the same one) fails at step 1 with `PortInUseError`. Several instances are a later option (ports in the config; see [config.md](config.md), open questions).

## Open questions

None currently.
