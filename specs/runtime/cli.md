---
code:
  - src/nao_sim/cli.py
  - src/nao_sim/stack.py
  - pyproject.toml
tests:
  - tests/test_cli.py
  - tests/test_docker_images.py
  - tests-e2e/test_naosim_live.py
---

# CLI (`nao-sim`)

**Status:** Implemented

## Purpose

The `nao-sim` command is how a person runs a simulated NAO from a terminal. It is a thin shell over the [API](api.md): every command loads a [config](config.md), drives a `NaoSim` object or reads its state, and turns the API's errors into messages and exit codes. No lifecycle logic lives in the CLI, so the CLI, the live tests and nao-bridge's `sim` backend all run the same code.

## Decided

### Commands

| Command | Does |
| --- | --- |
| `nao-sim fetch-and-build-images [2.1] [2.8]` | Runs `fetch_and_build_images` ([api.md](api.md), "Images"): fetches the image data, builds and verifies the images (default: both versions). The one slow step, run once before `run` and again after changing `docker/` |
| `nao-sim run [--config FILE]` | Loads the config (no `--config`: `NaoSimConfig()`), runs `NaoSim.start()`, prints `sim.url` and the `NaoSim` service's versions once ready, then stays in the foreground until Ctrl-C (or `SIGTERM`), which runs `NaoSim.stop()` |
| `nao-sim cleanup` | Removes what a run that died without stopping left behind (see "Foreground runs") |
| `nao-sim status` | Prints `read_status()` ([api.md](api.md), "Without a `NaoSim` object"): each container's state and health, then the `NaoSim` service's versions, readiness and device sources |
| `nao-sim logs [--follow] [--tail N]` | The containers' logs: `docker compose -p nao-sim logs`, with these two options passed through |

- `nao-sim probe` (the capability report, [_overview.md](../_overview.md), "Capability probe") is deferred with the probe: it gets its spec when the 2.8 validation milestone needs committed reports.
- The API is async: each command runs its coroutine with `asyncio.run`; Ctrl-C cancels it, and `run` still awaits `stop()` on the way out.
- `run` starts nothing itself: every check (Docker, the images, the `viewer` extra, ports) happens in `NaoSim.start()` ([api.md](api.md), "Lifecycle"), and the CLI prints the error's message.
- **Exit codes**, as nao-bridge's CLIs: a `ConfigError` exits 2 with its message (it names the key path); any other `NaoSimError` exits 1 with its message; Ctrl-C after a successful start exits 0 once `stop()` has run.
- **`status` answers in its exit code** too, for scripts: 0 when the robot is ready (`NaoSim/Ready` read from the service), 1 otherwise, with `nao-sim is not running` when no container runs.
- `logging.basicConfig` is called here, never in the library; `--verbose` raises the level to `DEBUG`.

### The config file only

`run` takes the whole description of the simulated NAO from its config file, as nao-bridge's `--config`-only CLIs: no flag overrides a field (`--naoqi`, `--headless`...), so a run is always reproducible from its file. Ready-made files are in `examples/configs/` ([config.md](config.md)); a one-off variation is a copied file.

### Foreground runs

`run` stays in the foreground: the host side of the robot (the audio output, later the audio and video inputs and the viewer window, which on macOS must stay in a process the user launched) lives in its process, and Ctrl-C stops everything in that same process with `NaoSim.stop()`, logs in view. There is no detached mode and no pid file. A caller that needs nao-sim in the background uses the API ([api.md](api.md)), or a shell's `&`, tmux and the like. The name says it: `run`, as `docker run` or `uv run`, not compose's `up`/`down` pair, which suggests a detached stack.

- **`nao-sim cleanup`** is for a run that died without stopping (killed, crashed, laptop closed): it runs `cleanup()` ([api.md](api.md)), which removes the `nao-sim` compose project's containers, every profile, keeping the package store volumes, and prints what it removed. If a run is still alive (port 9562, the audio output's, is taken), it changes nothing, says to press Ctrl-C in that run's terminal and exits 1.
- **`nao-sim status` and `nao-sim logs`** work from any terminal: they read Docker and the `NaoSim` service, so they need no pid file either.
- **Closing the sim window** does not end `run`: the robot keeps running and the terminal says so ([api.md](api.md), "Lifecycle"); Ctrl-C stops it.

### Existing commands

The former `nao-sim-fetch-suite` is now `nao-sim fetch-and-build-images`. The former `nao-sim-speaker` is gone: the audio output is part of a running `NaoSim` ([audio-output.md](../host/audio-output.md)) and has no command of its own. Recording what the robot says is `audio_output.mode = "record"` in the config, and debugging a stack is `nao-sim run` with `nao-sim logs`.

## Open questions

1. **A detached mode** (`run --detach`, with a pid file in the user's runtime directory) is deferred until a real need appears; it would not change the foreground default.
