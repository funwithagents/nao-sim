---
code:
  - pyproject.toml
tests:
  - tests/test_project_map.py
---

# Project

**Status:** Implemented

## Purpose

Structure and tooling for the nao-sim project itself: Python version, dependency/packaging management with `uv`, repo layout conventions, and development tooling.

## Decided

- **Python version:** 3.10+ minimum for host code (matches nao-bridge and nao-viewer). Code that runs inside NAOqi (`docker/modules/`) is Python 2.7, imposed by the suites' embedded interpreter.
- **Package layout:** `src/` layout — `src/nao_sim/...` — not flat, to avoid accidentally importing an uninstalled package from the repo root.
- **Dependency/venv management:** `uv`. Dev tooling lives in the `dev` dependency group (`uv sync --dev`), not in runtime `dependencies`. Build backend: `hatchling` (wheel packages `src/nao_sim`).
- **Linting/formatting:** `ruff`, excluding `docker/modules/` (Python 2.7).
- **Testing:** `pytest`, in two physically-separated tiers — a fast, deterministic, no-network default run (`tests/`, the only tier `testpaths` collects) and an opt-in live tier (`tests-e2e/`) that calls real external services. Full strategy is specced in [testing.md](testing.md).
- **Type checking:** `pyright` (`standard` mode), a dev dependency run via `uv run pyright`. Config lives in `[tool.pyright]` in `pyproject.toml`, targeting `src`, `tests`, and `tests-e2e`, pinned to the `.venv`. `docker/` is not type-checked: its code runs in container images whose dependencies are not in the host venv.
- **Repo shape:**
  - `src/nao_sim/` — the package, one module per core concept.
  - `specs/` — pre-implementation design docs, one per concept (this folder).
  - `plans/` — implementation plans turning settled specs into buildable steps.
  - `tests/` at repo root, mirroring the `src/nao_sim/` module structure.
  - `tests-e2e/` at repo root, for the live tier above — not collected by the default `pytest` run.
  - `docker/` — container recipes, Python 2.7 override modules (`modules/`), the `tts` engine container (`tts/`), and the gitignored `vendor/` for user-supplied suite tarballs.
- **No Aldebaran assets in git** (see [_overview.md](_overview.md), "Licensing"): `.gitignore` covers suite tarballs, `docker/vendor/`, meshes and textures. An automated asset guard is not built yet.

## Open questions

None currently.
