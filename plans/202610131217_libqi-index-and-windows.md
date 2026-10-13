# libqi from its package index, Windows, connect in one attempt

**Status:** In progress

Implements [project.md](../specs/project.md) ("libqi", "Platforms", "Distribution"), [cli.md](../specs/runtime/cli.md) (how `run` hears Ctrl-C), [api.md](../specs/runtime/api.md), [devices.md](../specs/host/devices.md) and [video-input.md](../specs/host/video-input.md) (one connect attempt), [testing.md](../specs/testing/testing.md) ("Platforms", the live tier's connect) and [ci.md](../specs/testing/ci.md) (the fast tier on three platforms). Follows naoqi-viewer's same change (funwithagents/naoqi-viewer#2): `qi>=3.1.8,<4` from the libqi fork's package index, Windows x64 beside macOS arm64 and Linux x86_64, naoqi-viewer at its merge commit, and no connect retry since libqi 3.1.8. The stack on Windows (Docker Desktop) is not run: CI's Windows runner has no Linux containers.

## Scope

- `pyproject.toml`: `qi>=3.1.8,<4`, the `libqi` index (`explicit = true`), `qi = { index = "libqi" }`, Windows x64 in `environments`, naoqi-viewer at `9964bc00`; the `realtime` and `container_code` markers
- `uv.lock`: relocked (qi 3.1.8 from the index, naoqi-viewer `9964bc00`, colorama)
- `.gitattributes`: every text file checked out with LF
- `src/naoqi_sim/cli.py`: `_route_signals`, the loop's signal handlers or, where the loop has none, a plain Ctrl-C handler with a 0.1 s tick
- `src/naoqi_sim/stack.py`: `connect` in one attempt; `logs` runs the resolved `docker`
- `src/naoqi_sim/docker_images.py`: `resolve` (`shutil.which`, PATHEXT); docker's output read as UTF-8; the image record in UTF-8
- `src/naoqi_sim/suite.py`: the resolved `docker` for `docker_cat`; the hash record in UTF-8
- `src/naoqi_sim/config.py`: config files read as UTF-8
- `tests/conftest.py`: `container_code` tests skip on Windows
- `tests/fake_docker.py`: a `docker.cmd` on Windows
- `tests/test_cli.py`: `run` driven through the loop's signal handlers and without them; Ctrl-C by `signal.raise_signal`
- `tests/test_stack.py`: a failed connect is not retried
- `tests/test_config.py`, `tests/test_files.py`: a Windows path as a regex (escaped), a child Python's environment (inherited)
- `tests/test_audio_*`, `tests/test_speech_core.py`, `tests/test_video_input.py`: `realtime` on the 18 wall-clock tests; `container_code` on the six container-code modules
- `tests-e2e/support.py`: `connect` in one attempt; `tests-e2e/test_install_live.py`: the scratch project declares no `environments`
- `.github/workflows/ci.yml`: `fast-tier` as a matrix over `ubuntu-24.04`, `macos-15`, `windows-2025`, `-m "not realtime"` on macOS
- `README.md`, the specs above, `specs/container/container.md` (platform notes), `specs/_overview.md`, `specs/_index.md`, `AGENTS.md`, this plan, `plans/_index.md`

## Steps

1. The index, the range, Windows and the naoqi-viewer pin; relock. Measure what a project depending on naoqi-sim by git must declare.
2. Windows in the code: UTF-8 for files and docker's output, `docker` resolved by `shutil.which`, Ctrl-C without the loop's signal handlers, `.gitattributes`.
3. One connect attempt in `stack.connect` and `support.connect`, with a fast-tier test that a failed connect is not retried.
4. The fast-tier matrix, then what its first runs showed: on Windows, the fake `docker` as a `docker.cmd`, `container_code` skipped, two test fixes (a path in a regex, a child's environment); on macOS, the `realtime` tests deselected.
5. Specs, README, overview, indexes.
6. Statuses, once a run on GitHub is green with ci.md's expected skips: this plan `Done`; project.md, cli.md, api.md, devices.md, video-input.md, testing.md and ci.md `Implemented`.

## Verification

- Locally on macOS arm64 with qi 3.1.8: lint, format, types, the fast tier (289 passed, 18 of them `realtime`). The `run` tests pass both ways of hearing Ctrl-C; the no-retry test fails on the retrying `connect` and passes on the new one.
- Step 1 measured with uv 0.11.29: a scratch project depending on this commit by git, with no `environments`, locked `qi` 3.1.8 from the index and naoqi-viewer at `9964bc00`.
- First CI runs: [38379478080](https://github.com/funwithagents/naoqi-sim/actions/runs/38379478080) (the live tier green on 2.1 and 2.8 with one connect attempt and the install test without `environments`; macOS 10 timing failures; Windows timed out on the fake `docker`), [38381820922](https://github.com/funwithagents/naoqi-sim/actions/runs/38381820922) (Windows green, 201 passed and 88 `container_code` skipped; macOS 2 more timing failures).
- On GitHub: every job green; fast-tier as ci.md expects.
