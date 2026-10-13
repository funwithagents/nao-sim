# libqi from its package index, Windows, connect in one attempt

**Status:** In progress

Implements [project.md](../specs/project.md) ("libqi", "Platforms", "Distribution"), [cli.md](../specs/runtime/cli.md) (how `run` hears Ctrl-C), [api.md](../specs/runtime/api.md), [devices.md](../specs/host/devices.md) and [video-input.md](../specs/host/video-input.md) (one connect attempt), [testing.md](../specs/testing/testing.md) ("Platforms", "Tooling", the live tier's connect), [ci.md](../specs/testing/ci.md) (the fast tier on three platforms), [audio-output.md](../specs/host/audio-output.md) (the mixer keeps its schedule) and [api.md](../specs/runtime/api.md) (a cancelled `start()`). Follows naoqi-viewer's same change (funwithagents/naoqi-viewer#2): `qi>=3.1.8,<4` from the libqi fork's package index, Windows x64 beside macOS arm64 and Linux x86_64, naoqi-viewer at its merge commit, and no connect retry since libqi 3.1.8. The stack on Windows (Docker Desktop) is not run: CI's Windows runner has no Linux containers.

## Scope

- `pyproject.toml`: `qi>=3.1.8,<4`, the `libqi` index (`explicit = true`), `qi = { index = "libqi" }`, Windows x64 in `environments`, naoqi-viewer at `9964bc00`; pytest-xdist in `dev` and `-n logical --maxprocesses 8` in `addopts`; the `container_code` marker
- `uv.lock`: relocked (qi 3.1.8 from the index, naoqi-viewer `9964bc00`, colorama)
- `.gitattributes`: every text file checked out with LF
- `src/naoqi_sim/cli.py`: `_route_signals`, the loop's signal handlers or, where the loop has none, a plain Ctrl-C handler with a 0.1 s tick
- `src/naoqi_sim/stack.py`: `connect` in one attempt; `logs` runs the resolved `docker`
- `src/naoqi_sim/docker_images.py`: `resolve` (`shutil.which`, PATHEXT); docker's output read as UTF-8; the image record in UTF-8
- `src/naoqi_sim/suite.py`: the resolved `docker` for `docker_cat`; the hash record in UTF-8
- `src/naoqi_sim/config.py`: config files read as UTF-8
- `src/naoqi_sim/audio_output.py`: the mixer keeps its tick schedule (catch-up, `RESYNC_S`), `playing_until` never before now plus a tick, `_sleep_until` past its deadline
- `src/naoqi_sim/sim.py`: `start()`'s steps through `_step`: cancelled, the step in flight ends before the teardown; the readiness wait aborts
- `src/naoqi_sim/stack.py`, `docker_images.py`: `wait_ready`/`wait_healthy` take an abort event
- `tests/conftest.py`: `container_code` tests skip on Windows; the machine's wake-up lateness, measured, in pytest's header and as the `lateness` fixture
- `tests/ports.py`: ports for the fixed-port tests, per xdist worker, below the ephemeral ranges
- `tests/fake_docker.py`: a `docker.cmd` on Windows; a slow `up` (`up_s`); reads retried over a half-written state
- `tests/test_sim.py`, `tests/test_cli.py`, `tests/test_stack.py`: ports from `tests/ports.py`; the cancelled start with a slow `up`
- `tests/test_audio_output.py`: late wake-ups don't drift the mix; `playing_until` mid-play within the measured lateness
- `src/naoqi_sim/video_input.py`: `missed`, the slots that put no frame
- `tests/test_video_input.py`: "no burst" as no two frames back to back; the schedule as frames put plus `missed`
- `tests-e2e/conftest.py`: the live tier forced serial
- `tests/test_cli.py`: `run` driven through the loop's signal handlers and without them; Ctrl-C by `signal.raise_signal`
- `tests/test_stack.py`: a failed connect is not retried
- `tests/test_config.py`, `tests/test_files.py`: a Windows path as a regex (escaped), a child Python's environment (inherited)
- the six container-code test modules: `container_code`
- `tests-e2e/support.py`: `connect` in one attempt; `tests-e2e/test_install_live.py`: the scratch project declares no `environments`
- `.github/workflows/ci.yml`: `fast-tier` as a matrix over `ubuntu-24.04`, `macos-15`, `windows-2025`, `-m "not container_code"` off Linux
- `README.md`, the specs above, `specs/container/container.md` (platform notes), `specs/_overview.md`, `specs/_index.md`, `AGENTS.md`, this plan, `plans/_index.md`

## Steps

1. The index, the range, Windows and the naoqi-viewer pin; relock. Measure what a project depending on naoqi-sim by git must declare.
2. Windows in the code: UTF-8 for files and docker's output, `docker` resolved by `shutil.which`, Ctrl-C without the loop's signal handlers, `.gitattributes`.
3. One connect attempt in `stack.connect` and `support.connect`, with a fast-tier test that a failed connect is not retried.
4. The fast-tier matrix, then what its first runs showed: on Windows, the fake `docker` as a `docker.cmd`, `container_code` skipped, two test fixes (a path in a regex, a child's environment); on macOS, a dozen timing failures.
5. Timing, fixed rather than excluded (a first try deselected `realtime` tests on macOS, dropped): the mixer keeps its schedule; the machine's wake-up lateness measured and added to the bounds of reaction times; the camera's "no burst" bound on the behavior; `_sleep_until` past its deadline. CI tests the container code on Linux only.
6. A cancelled `start()` waits for the step in flight (found on Windows: a `compose up` racing the teardown's `down`).
7. The fast tier in parallel (pytest-xdist, as reachy-mini-bridge), the live tier serial; per-worker test ports (found on macOS: a reserved port taken by another worker).
8. Specs, README, overview, indexes.
9. Statuses, once a run on GitHub is green with ci.md's expected skips: this plan `Done`; project.md, cli.md, api.md, devices.md, video-input.md, audio-output.md, testing.md and ci.md `Implemented`.

## Verification

- Locally on macOS arm64 with qi 3.1.8: lint, format, types, the fast tier (290 passed, about 18 s on eight workers against 105 s serially). The `run` tests pass both ways of hearing Ctrl-C. Each new test fails on the code before its fix and passes after: the no-retry test (5 attempts against 1), the drift test (ticks 20 then 30 to 40 ms apart on the old mixer), the cancelled start (containers left running).
- Step 1 measured with uv 0.11.29: a scratch project depending on this commit by git, with no `environments`, locked `qi` 3.1.8 from the index and naoqi-viewer at `9964bc00`.
- First CI runs: [38379478080](https://github.com/funwithagents/naoqi-sim/actions/runs/38379478080) (the live tier green on 2.1 and 2.8 with one connect attempt and the install test without `environments`; macOS 10 timing failures; Windows timed out on the fake `docker`), [38381820922](https://github.com/funwithagents/naoqi-sim/actions/runs/38381820922) (Windows green, 201 passed and 88 `container_code` skipped; macOS 2 more timing failures).
- On GitHub: every job green; fast-tier as ci.md expects.
