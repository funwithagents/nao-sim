---
code:
  - src/naoqi_sim/cli.py
  - src/naoqi_sim/stack.py
  - pyproject.toml
tests:
  - tests/test_cli.py
  - tests/test_docker_images.py
  - tests-e2e/test_naoqisim_live.py
---

# CLI (`naoqi-sim`)

**Status:** Updated

## Purpose

The `naoqi-sim` command is how a person runs a simulated NAO from a terminal. It is a thin shell over the [API](api.md): every command loads a [config](config.md), drives a `NaoqiSim` object or reads its state, and turns the API's errors into messages and exit codes. No lifecycle logic lives in the CLI, so the CLI, the live tests and naoqi-bridge's `sim` backend all run the same code.

## Decided

### Commands

| Command | Does |
| --- | --- |
| `naoqi-sim fetch-and-build-images [2.1] [2.8]` | Runs `fetch_and_build_images` ([api.md](api.md), "Images"): fetches the image data, builds and verifies the images (default: both versions). The one slow step, run once before `run` and again after changing `docker/` |
| `naoqi-sim run [--config FILE]` | Loads the config (no `--config`: `NaoqiSimConfig()`), runs `NaoqiSim.start()`, prints `sim.url` and the `NaoqiSim` service's versions once ready, then stays in the foreground until Ctrl-C (or `SIGTERM`), which runs `NaoqiSim.stop()` |
| `naoqi-sim cleanup` | Removes what a run that died without stopping left behind (see "Foreground runs") |
| `naoqi-sim status` | Prints `read_status()` ([api.md](api.md), "Without a `NaoqiSim` object"): each container's state and health, then the `NaoqiSim` service's versions, readiness and device sources |
| `naoqi-sim logs [--follow] [--tail N]` | The containers' logs: `docker compose -p naoqi-sim logs`, with these two options passed through |

- `naoqi-sim probe` (the capability report, [_overview.md](../_overview.md), "Capability probe") is deferred with the probe: it gets its spec when the 2.8 validation milestone needs committed reports.
- The API is async: each command runs its coroutine with `asyncio.run`; Ctrl-C cancels it, and `run` still awaits `stop()` on the way out.
- **How `run` hears Ctrl-C.** On Linux and macOS through the event loop (`loop.add_signal_handler`, for `SIGINT` and `SIGTERM`). Windows' event loops have none (`NotImplementedError`), and Windows never delivers `SIGTERM`: there `run` installs a plain `SIGINT` handler that hands over to the loop (`call_soon_threadsafe`), and keeps a 0.1 s tick on the loop so that Python runs the handler promptly even while the loop waits for I/O. The fast tier drives `run` both ways on every platform, with real signals (`signal.raise_signal`; `os.kill` on Windows terminates the process instead).
- `run` starts nothing itself: every check (Docker, the images, the `viewer` extra, ports) happens in `NaoqiSim.start()` ([api.md](api.md), "Lifecycle"), and the CLI prints the error's message.
- **Exit codes**, as naoqi-bridge's CLIs: a `ConfigError` exits 2 with its message (it names the key path); any other `NaoqiSimError` exits 1 with its message; Ctrl-C after a successful start exits 0 once `stop()` has run.
- **`status` answers in its exit code** too, for scripts: 0 when the robot is ready (`NaoqiSim/Ready` read from the service), 1 otherwise, with `naoqi-sim is not running` when no container runs.
- `logging.basicConfig` is called here, never in the library; `--verbose` raises the level to `DEBUG`.

### The config file only

`run` takes the whole description of the simulated NAO from its config file, as naoqi-bridge's `--config`-only CLIs: no flag overrides a field (`--naoqi`, `--headless`...), so a run is always reproducible from its file. Ready-made files are in `examples/configs/` ([config.md](config.md)); a one-off variation is a copied file.

### Foreground runs

`run` stays in the foreground: the host side of the robot (the audio output, later the audio and video inputs and the viewer window, which on macOS must stay in a process the user launched) lives in its process, and Ctrl-C stops everything in that same process with `NaoqiSim.stop()`, logs in view. There is no detached mode and no pid file. A caller that needs naoqi-sim in the background uses the API ([api.md](api.md)), or a shell's `&`, tmux and the like. The name says it: `run`, as `docker run` or `uv run`, not compose's `up`/`down` pair, which suggests a detached stack.

- **`naoqi-sim cleanup`** is for a run that died without stopping (killed, crashed, laptop closed): it runs `cleanup()` ([api.md](api.md)), which removes the `naoqi-sim` compose project's containers, every profile, keeping the package store volumes, and prints what it removed. If a run is still alive (port 9562, the audio output's, is taken), it changes nothing, says to press Ctrl-C in that run's terminal and exits 1.
- **`naoqi-sim status` and `naoqi-sim logs`** work from any terminal: they read Docker and the `NaoqiSim` service, so they need no pid file either.
- **Closing the sim window** does not end `run`: the robot keeps running and the terminal says so ([api.md](api.md), "Lifecycle"); Ctrl-C stops it.

### Existing commands

The former `naoqi-sim-fetch-suite` is now `naoqi-sim fetch-and-build-images`. The former `naoqi-sim-speaker` is gone: the audio output is part of a running `NaoqiSim` ([audio-output.md](../host/audio-output.md)) and has no command of its own. Recording what the robot says is `audio_output.mode = "record"` in the config, and debugging a stack is `naoqi-sim run` with `naoqi-sim logs`.

## Open questions

1. **A detached mode** (`run --detach`, with a pid file in the user's runtime directory) is deferred until a real need appears; it would not change the foreground default.
