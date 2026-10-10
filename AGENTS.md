# Agent instructions

Start at [specs/_index.md](specs/_index.md) for an overview of the specs and their status before making design decisions or writing code — it lists each spec and whether it's still open ("Draft"/"Not started"), design-validated ("Stable"), or built ("Implemented"). For what's been (or is being) built, see [plans/_index.md](plans/_index.md), which lists each implementation plan and its status ("Todo"/"In progress"/"Done").

The overview of nao-sim (architecture, licensing rules, NAOqi 2.1/2.8 differences, the state of every concept, milestones) is [specs/_overview.md](specs/_overview.md). Concept specs are carved out of it as work starts on them; until a concept has its own spec, the overview is the reference.

**Never commit Aldebaran assets**: Choregraphe suite tarballs, robot images (`.opn`) and packages (`docker/image-data/`, gitignored), NAO meshes or textures, robot packages, or anything derived from them. Images built from the suite are local only and never pushed.

## Project map

Where things live. This is a coarse, module-level map — for the full file inventory use `git ls-files`; for design detail follow the spec links.

### Top-level layout

| Path | What's there |
|---|---|
| `src/nao_sim/` | The library itself — one module per core concept (see below) |
| `specs/` | Pre-implementation design docs, one per concept, each with a `**Status:**` — indexed by [specs/_index.md](specs/_index.md). Grouped in one folder per architecture layer: `runtime/` (config, `NaoSim` object, CLI), `container/` (the images), `services/` (NAOqi services replaced inside the container), `host/` (host devices, the viewer), `testing/` (testing, CI); `project.md` and the `_` files stay at the root |
| `plans/` | Implementation plans turning settled specs into buildable steps — indexed by [plans/_index.md](plans/_index.md) |
| `tests/` | Fast, deterministic, no-network tests; mirrors the `src/nao_sim/` module structure |
| `tests-e2e/` | Opt-in live tests that start the nao-sim containers themselves, once per NAOqi version (not collected by default `pytest`) |
| `docker/` | Container recipes, shipped in the wheel as `nao_sim/docker/` (all but `image-data/`; [project.md](specs/project.md), "Distribution"): `Dockerfile.naoqi-2.1`, `Dockerfile.naoqi-2.8`, `compose.yaml`, `entrypoint-2.1.sh`/`entrypoint-2.8.sh` and the `entrypoint-lib.sh` they share ([container.md](specs/container/container.md)), `healthcheck.sh` ([status-service.md](specs/container/status-service.md)); `modules/`, Python 2.7 override modules loaded inside NAOqi ([service-replacement.md](specs/container/service-replacement.md), [speech.md](specs/services/speech.md), [status-service.md](specs/container/status-service.md)); `tts/`, the speech engine container ([tts-engine.md](specs/container/tts-engine.md)); `image-data/<version>/`, the suite tarball and `animations.pkg` fetched by `nao-sim fetch-and-build-images` in a checkout, and `image-data/images.json`, the verified image IDs (gitignored; an installed nao-sim keeps them in the user data directory, see `files.py`) |
| `examples/configs/` | Ready-to-use `NaoSimConfig` files for `nao-sim run --config` ([config.md](specs/runtime/config.md), "Example files") |
| `.github/workflows/` | `ci.yml`, the CI workflow on GitHub's hosted runners ([ci.md](specs/testing/ci.md)) |
| `spike/` | Local-only investigation scripts and measurement log (untracked, not committed); findings are folded into the specs |

### `src/nao_sim/` modules

<!-- One row per concept module. Keep this in sync with the code (a test enforces it). -->

| Module | Role | Spec |
|---|---|---|
| `src/nao_sim/audio_output.py` | The audio output device: TCP PCM player the containers stream into, its audio sinks (device, null, WAV, memory) and playing state; run in-process by `NaoSim`, no command of its own | [audio-output.md](specs/host/audio-output.md), [devices.md](specs/host/devices.md) |
| `src/nao_sim/__init__.py` | Front door: re-exports `NaoSim`, the config classes, the audio sinks, `read_status`, `cleanup`, the image functions and the errors | [api.md](specs/runtime/api.md) |
| `src/nao_sim/cli.py` | The `nao-sim` command, a thin shell over the library: `fetch-and-build-images`, `run`, `status`, `cleanup`, `logs` | [cli.md](specs/runtime/cli.md) |
| `src/nao_sim/config.py` | `NaoSimConfig` and its blocks, `ConfigError`, the JSON loaders | [config.md](specs/runtime/config.md) |
| `src/nao_sim/sim.py` | The `NaoSim` object: `start()`/`stop()` over the audio output, the containers and the viewer, with one teardown | [api.md](specs/runtime/api.md) |
| `src/nao_sim/stack.py` | The running containers: compose up/down, readiness, `read_status` and `cleanup` for other terminals, the logs | [api.md](specs/runtime/api.md), [cli.md](specs/runtime/cli.md) |
| `src/nao_sim/viewer.py` | The simulated world: when a config needs nao-viewer, its sim-mode config, the window's launch, watch and close | [viewer.md](specs/host/viewer.md) |
| `src/nao_sim/video_input.py` | The video input device: injects VGA frames from the viewer's top-camera render into `ALVideoDevice` with `putImage` at `video_input.fps`, publishes `NaoSim/Camera/Source`; run in-process by `NaoSim` | [video-input.md](specs/host/video-input.md), [devices.md](specs/host/devices.md) |
| `src/nao_sim/errors.py` | `NaoSimError` and its subclasses, shared by the modules | [api.md](specs/runtime/api.md) |
| `src/nao_sim/docker_images.py` | `fetch_and_build_images` (fetch, build with the version label, verify the boot, record) and `check_images` (what a start checks) | [api.md](specs/runtime/api.md), [container.md](specs/container/container.md) |
| `src/nao_sim/files.py` | Where nao-sim's files are: the recipes (package data when installed, the checkout's `docker/` otherwise), the image data folder (`NAO_SIM_IMAGE_DATA`, the checkout's `docker/image-data/`, or the user data directory) and the environment every compose call gets | [api.md](specs/runtime/api.md), [project.md](specs/project.md) |
| `src/nao_sim/suite.py` | Fetches the pinned Choregraphe suites and the robot image's `animations` package into `docker/image-data/<version>/` (first step of `fetch-and-build-images`) | [container.md](specs/container/container.md) |

**Keep this map current:** when you add, rename, or remove a top-level `src/nao_sim/` module or a root directory, update the map in the same change — same discipline as keeping spec/plan statuses honest (below). A test (`tests/test_project_map.py`) enforces that every `src/nao_sim/*.py` module appears here and vice-versa — and that the spec frontmatter (see below) stays honest too.

## Keeping statuses current

Specs and plans both carry a status, and you are responsible for keeping it honest as work progresses — update it in the same change that does the work, not as an afterthought:

- **Spec status** (`**Status:**` line near the top of each spec, and the Status column in [specs/_index.md](specs/_index.md)) tracks *design maturity* and *whether the code reflects the spec*, as a lifecycle: `Not started` → `Draft` (open questions remain) → `Stable` (design settled, reviewed and validated — open questions are deferrals only — but **not necessarily implemented yet**) → `Implemented` (a `Done` plan has built it and the code matches the spec). Keep the `**Status:**` line and the index row in sync.
  - **`Stable` is the design-review gate, not an implementation claim.** Promote `Draft` → `Stable` once the core design is settled and its remaining open questions are genuine deferrals (not load-bearing unknowns) — this is where the design is validated *before* code is written. No implementation is required to be `Stable`.
  - **`Implemented` means code matches.** Promote `Stable` → `Implemented` only once a plan implementing it is `Done` (lint, type check, tests all pass — see Verification). This is the one transition that asserts design and code are in sync.
  - **When you edit an `Implemented` spec in a way that requires new code, set its status to `Updated` in the same change.** `Updated` means the design is settled but the existing implementation now lags it — a stronger warning than `Stable`, because there is stale code to fix, not just code to write. Then write a new implementation plan for the gap (see below) and, once that plan is `Done`, flip the spec back to `Implemented`. This `Implemented → Updated → Implemented` loop keeps a spec's status an honest signal of whether the code actually matches it — never leave a re-designed spec sitting at `Implemented`.
  - A purely editorial edit to a `Stable` or `Implemented` spec (typos, clarifications, reordering — nothing that changes what the code should do) keeps its status; it does **not** need `Updated`.
- **Plan status** (`**Status:**` line near the top of each plan, and the Status column in [plans/_index.md](plans/_index.md)) tracks *implementation progress*: `Todo` → `In progress` → `Done`. Mark a plan `Done` only once it's implemented and verified (lint, type check, tests all pass — see Verification). Keep the `**Status:**` line and the index row in sync.
- Whenever you add a spec or plan, add its row to the relevant `_index.md`; whenever you change a status, change it in both the file and the index.

## Spec frontmatter

Every spec opens with a YAML frontmatter block naming the code and tests it governs:

```
---
code:
  - src/nao_sim/<module>.py
tests:
  - tests/test_<module>.py
---
```

This is the **spec → code/tests** mapping — the inverse of the module → spec column in the Project map above. Its job is to give the **spec-drift checks** an explicit, version-controlled scope: the exact files to diff a spec against, so a checker never has to guess which code implements a given spec. `code:` names the implementation the spec specifies; `tests:` names the tests that pin its behavior (may be empty/absent).

The mapping is **many-to-many**: a file can be governed by several specs, so the same path legitimately appears in more than one spec's frontmatter.

**Keep it current** (same discipline as statuses): when you move, rename, or delete a file a spec governs — or add a new `src/nao_sim/` module — update the affected spec's `code:`/`tests:` in the same change. `tests/test_project_map.py` enforces these invariants: every listed path exists, every spec has a `**Status:**` line and declares a non-empty `code:` list (a `Draft` or `Not started` spec may leave it empty until its code exists, rather than list files it does not govern), and every concept module in `src/nao_sim/` is named by at least one spec (`__init__.py` is exempt as package glue).

## Testing

- Write functional tests: exercise what a feature/function actually does (inputs → outputs, state changes, side effects), not just that it runs or matches its signature.
- Avoid trivial/tautological tests — e.g. asserting a constant, asserting an object is not `None`, asserting a mock was called. If a test would pass for a broken implementation, it's not worth writing.
- Prefer driving the public API the way a real caller would over asserting on internals.

### Live/e2e tests

Some tests need the nao-sim containers running (built from the user's Choregraphe suite). They live in `tests-e2e/`, a directory separate from `tests/`, so the default `uv run pytest` never runs them — no Docker or suite is needed for the normal dev loop. Run them explicitly with `uv run pytest tests-e2e`: the tests run each NAOqi version with a `NaoSim` (headless, audio into a `MemorySink`), test it over qi on `127.0.0.1:9559` and stop it, so stop any nao-sim you started first. A version whose suite or image is missing, or a machine without Docker, **skips**, not fails. Remember that libqi 3 `connect()` against NAOqi 2.1 fails about one time in three: live tests connect with a retry (`tests-e2e/support.connect`). nao-sim's job is to behave like a NAO in its API; the tests check that, and never target a real robot.

## Code that is not linted here

`docker/modules/` is Python 2.7 that runs inside NAOqi's embedded interpreter (imports `naoqi`, `qi`, `urllib2`), so ruff excludes it and pyright does not include it. Keep it Python 2.7 compatible: no f-strings, no type annotations, no Python 3-only stdlib. `docker/tts/` is Python 3.12 inside its own image: ruff covers it, pyright does not (its dependencies are not in the host venv).

## Implementation plans

- Write implementation plans as files in the [plans](plans/) folder.
- Name each file `YYYYMMDDHHmm_plan-title.md`: a compact date-time prefix, then an underscore, then a kebab-case title (words separated by `-`).
  - Example: `202607201830_world-registry-refactor.md`
- Give each plan a `**Status:**` line just under its title (`Todo`/`In progress`/`Done`) and add a row for it to [plans/_index.md](plans/_index.md). Keep both current as work progresses (see "Keeping statuses current" above).
- Start from [plans/_plan-template.md](plans/_plan-template.md).

## Verification

After any code change, run linting, type checking, and tests, and fix any failures before considering the work done.

## Commands

```
uv sync --dev
uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest
```
