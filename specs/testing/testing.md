---
code:
  - tests/conftest.py
  - tests-e2e/conftest.py
  - tests-e2e/support.py
tests:
  - tests/test_speaker.py
  - tests/test_tts_core.py
  - tests/test_tts_engine.py
  - tests/test_status_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_speech_live.py
  - tests-e2e/test_status_live.py
---

# Testing

**Status:** Implemented

## Purpose

nao-sim's testing strategy — the two-tier structure and what a good test looks like. It's a **cross-cutting practice**, not a runtime concept: nothing here ships in the library. It exists as a spec so the decisions have one honest home that stays in sync with the setup, rather than living half in [project.md](../project.md) (the tooling choices) and half in [AGENTS.md](../../AGENTS.md) (the operational how-to). The concrete shell commands to run each tier live in [AGENTS.md](../../AGENTS.md) "Testing".

## Two tiers, physically separated

Tests split into two directories, and the split is structural — a directory boundary, not a marker or an opt-out flag:

| Tier | Directory | Network | Deterministic | Runs by default |
|---|---|---|---|---|
| Unit / integration | `tests/` | never | yes | **yes** |
| Live / e2e | `tests-e2e/` | the nao-sim containers, started by the tests | no | **no** |

- **`tests/` is the normal dev loop.** Fast, deterministic, no real network, no credentials. `pyproject.toml`'s `testpaths = ["tests"]` points the default `uv run pytest` here, so this is what runs on every change and what any contributor or CI can run with zero credentials.
- **`tests-e2e/` is opt-in.** It builds and runs the NAOqi and `tts` containers (Docker, the user's Choregraphe suite, real timing), so it is deliberately *not* collected by the default run. Because `testpaths` already excludes it, no pytest marker or `--run-e2e` flag is needed: the physical separation is the whole mechanism. Run it explicitly (`uv run pytest tests-e2e`).

The `tests/` tier has one `test_<module>.py` per module under test: the `src/nao_sim/` modules and the host-importable container code (`test_tts_core.py` for `docker/modules/nao_sim_tts_core.py`, `test_status_core.py` for `nao_sim_status_core.py`, `test_tts_engine.py` for `docker/tts/server.py`), the container's shell scripts (`test_entrypoint.py` runs `docker/entrypoint-2.1.sh`, `entrypoint-2.8.sh` and `healthcheck.sh` with fake `naoqi-bin` and `qicli` first on `PATH`, so the boot sequence and its failure exits are checked without Docker), plus the `test_project_map.py` drift guard. `tests/conftest.py` puts `docker/modules` and `docker/tts` on `sys.path` (and pyright's `extraPaths`). `tests-e2e/` is organized around live scenarios rather than modules.

## What a good test asserts

- **Functional, not tautological.** Exercise what a feature actually does — inputs → outputs, state changes, side effects — not that it runs or matches its own signature. A test that would pass against a broken implementation (asserting a constant, that an object isn't `None`, that a mock was called) isn't worth writing.
- **Drive the public API like a real caller.** Prefer exercising the public surface the way a consumer would over reaching into internals; assert on the observable result.
- **In the e2e tier, assert on behavior, not exact output.** Timings and synthesized audio vary run to run, so a live test asserts a robust property ("`say()` blocked for about the audio it played", "every bookmark was raised"), never an exact duration or string.

## Test isolation

If the package holds process-global or singleton state, both tiers carry an identical autouse fixture (in each tier's `conftest.py`) that resets it before and after every test, so no state — or background timers/threads — leaks across tests. The fixture is duplicated rather than shared because `tests-e2e/` isn't a package that imports from `tests/`, and it's only a few lines.

## Live tier: the tests drive the stack

nao-sim is tested as what it is: containers that behave like a NAO in their API, reached over qi on `127.0.0.1:9559`. The live tests bring that stack up themselves; there is no target to configure.

- **Per version.** The `nao` fixture (`tests-e2e/conftest.py`) is session-scoped and parametrized over NAOqi 2.1 and 2.8, so every live test runs once per version. For each version it first runs `check_images` ([api.md](../runtime/api.md), "Images"): current images are used as they are; missing or outdated ones (an edit under `docker/` included) are built and verified with `fetch_and_build_images` when the vendor files are in `docker/vendor/`, and the version skips otherwise. Then it runs `docker compose --profile <version> up -d` on `tts` and that version's NAOqi service, waits for `[entrypoint] nao-sim ready` in the container log, connects, and runs `docker compose down` at the end. Versions run one after the other, since both publish 9559.
- **Skip, never fail, without the means.** No Docker, or neither the version's suite tarball nor its image: that version's tests skip. A contributor (or CI) without the suites is never broken.
- **Fail loudly on a conflict.** If 9559 or the speaker's 9562 is already taken (a stack or a `nao-sim-speaker` started by hand), the tests fail with that message rather than test someone else's stack.
- **Connect with a retry**: the libqi 3 wheel fails about one connect in three against NAOqi 2.1, instantly, with `disconnected` (`support.connect`).
- **What was played.** The tests run `nao-sim-speaker --silent` (real-time pacing, no audio device) on 9562, where the `tts` container streams, and read its JSON events: `played_s` is the audio actually played. What the `ALTextToSpeech` replacement received is read from its JSON log in the container.

## Tooling

- **`pytest`** is the runner; **`ruff`** lints/formats; **`pyright`** (`standard` mode) type-checks. All three are the gate after any change — lint, type check, and tests must pass before work is considered done (see [AGENTS.md](../../AGENTS.md), "Verification").
- **`pyright` covers test code too:** its `include` is `src`, `tests`, and `tests-e2e`, so tests are type-checked alongside the library rather than being a blind spot.

## Open questions

1. **CI wiring.** Nothing here sets up continuous integration. The default `tests/` tier is CI-ready (deterministic, no Aldebaran software), and the e2e tier skips cleanly without Docker or the suites. The overview plans GitHub's hosted runners for both tiers, the live one fetching and building the images itself as nao-viewer's CI already does; not built yet. Today all testing is a local, manual command.
2. **Python 2.7 override modules.** The shared core (`nao_sim_tts_core`) is Python 2.7 code kept importable under Python 3, so the fast tier tests it on the host; the version-specific modules (`naoqi`/`qi` objects) are only exercised by the live tier. No automated check proves the modules are still valid Python 2.7: today that is a manual `compile` with the image's `/opt/naoqi/bin/python2`.
