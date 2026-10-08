# Agent instructions

Start at [specs/_index.md](specs/_index.md) for an overview of the specs and their status before making design decisions or writing code — it lists each spec and whether it's still open ("Draft"/"Not started"), design-validated ("Stable"), or built ("Implemented"). For what's been (or is being) built, see [plans/_index.md](plans/_index.md), which lists each implementation plan and its status ("Todo"/"In progress"/"Done").

The overview of nao-sim (architecture, licensing rules, NAOqi 2.1/2.8 differences, the state of every concept, milestones) is [specs/_overview.md](specs/_overview.md). Concept specs are carved out of it as work starts on them; until a concept has its own spec, the overview is the reference.

**Never commit Aldebaran assets**: Choregraphe suite tarballs (`docker/vendor/`, gitignored), NAO meshes or textures, robot packages, or anything derived from them. Images built from the suite are local only and never pushed.

## Project map

Where things live. This is a coarse, module-level map — for the full file inventory use `git ls-files`; for design detail follow the spec links.

### Top-level layout

| Path | What's there |
|---|---|
| `src/nao_sim/` | The library itself — one module per core concept (see below) |
| `specs/` | Pre-implementation design docs, one per concept, each with a `**Status:**` — indexed by [specs/_index.md](specs/_index.md) |
| `plans/` | Implementation plans turning settled specs into buildable steps — indexed by [plans/_index.md](plans/_index.md) |
| `tests/` | Fast, deterministic, no-network tests; mirrors the `src/nao_sim/` module structure |
| `tests-e2e/` | Opt-in live tests that start the nao-sim containers themselves, once per NAOqi version (not collected by default `pytest`) |
| `docker/` | Container recipes: `Dockerfile.naoqi-2.1`, `Dockerfile.naoqi-2.8`, `compose.yaml`, `entrypoint.sh` ([container.md](specs/container.md)); `modules/`, Python 2.7 override modules loaded inside NAOqi ([service-replacement.md](specs/service-replacement.md), [speech.md](specs/speech.md)); `tts/`, the speech engine container ([tts-engine.md](specs/tts-engine.md)); `vendor/`, the suite tarballs fetched by `nao-sim-fetch-suite` or placed by hand (gitignored) |
| `spike/` | Local-only investigation scripts and measurement log (untracked, not committed); findings are folded into the specs |

### `src/nao_sim/` modules

<!-- One row per concept module. Keep this in sync with the code (a test enforces it). -->

| Module | Role | Spec |
|---|---|---|
| `src/nao_sim/__init__.py` | Package glue (no spec needed) | — |
| `src/nao_sim/soundcard.py` | Host sound card: TCP PCM player the containers stream into (`nao-sim-soundcard`) | [soundcard.md](specs/soundcard.md) |
| `src/nao_sim/suite.py` | Downloads the pinned Choregraphe suites into `docker/vendor/` (`nao-sim-fetch-suite`) | [container.md](specs/container.md) |

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

**Keep it current** (same discipline as statuses): when you move, rename, or delete a file a spec governs — or add a new `src/nao_sim/` module — update the affected spec's `code:`/`tests:` in the same change. `tests/test_project_map.py` enforces three invariants: every listed path exists, every spec declares a non-empty `code:` list, and every concept module in `src/nao_sim/` is named by at least one spec (`__init__.py` is exempt as package glue).

## Testing

- Write functional tests: exercise what a feature/function actually does (inputs → outputs, state changes, side effects), not just that it runs or matches its signature.
- Avoid trivial/tautological tests — e.g. asserting a constant, asserting an object is not `None`, asserting a mock was called. If a test would pass for a broken implementation, it's not worth writing.
- Prefer driving the public API the way a real caller would over asserting on internals.

### Live/e2e tests

Some tests need the nao-sim containers running (built from the user's Choregraphe suite). They live in `tests-e2e/`, a directory separate from `tests/`, so the default `uv run pytest` never runs them — no Docker or suite is needed for the normal dev loop. Run them explicitly with `uv run pytest tests-e2e`: the tests bring up each NAOqi version's stack with `docker compose`, test it over qi on `127.0.0.1:9559` and take it down, so stop any stack (or `nao-sim-soundcard`) you started by hand first. A version whose suite or image is missing, or a machine without Docker, **skips**, not fails. Remember that libqi 3 `connect()` against NAOqi 2.1 fails about one time in three: live tests connect with a retry (`tests-e2e/support.connect`). nao-sim's job is to behave like a NAO in its API; the tests check that, and never target a real robot.

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
