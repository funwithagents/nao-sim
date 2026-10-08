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

- **Python version:** 3.12 or 3.13 for host code (`requires-python = ">=3.12,<3.14"`, as nao-viewer), capped by the libqi wheels. Code that runs inside NAOqi (`docker/modules/`) is Python 2.7, imposed by the suites' embedded interpreter. `.python-version` pins 3.12 for the dev venv.
- **libqi:** `qi==3.1.6` is a runtime dependency: nao-sim's host side talks to NAOqi over qi (camera injection, perception feed, viewer, probe, live tests), so it does not run without it. The wheels come from the GitHub Releases of the [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python) fork, one direct URL per platform and Python version in `[tool.uv.sources]`, exactly as in nao-viewer; this also keeps uv from picking Aldebaran's older `qi` 3.1.5 on PyPI.
- **Platforms:** the fork ships wheels for macOS 15+ on arm64 and Linux x86_64 (glibc 2.34+) only, so `[tool.uv] environments` limits the lock to those two. Elsewhere (Windows, Intel macOS, Linux arm64, older glibc or macOS) installation fails instead of producing a nao-sim that cannot reach NAOqi; wider coverage is a libqi fork task (see the overview's open questions).
- **Package layout:** `src/` layout — `src/nao_sim/...` — not flat, to avoid accidentally importing an uninstalled package from the repo root.
- **Dependency/venv management:** `uv`. Dev tooling lives in the `dev` dependency group (`uv sync --dev`), not in runtime `dependencies`. Build backend: `hatchling` (wheel packages `src/nao_sim`).
- **Linting/formatting:** `ruff`, excluding `docker/modules/` (Python 2.7) and the local `spike/` scripts.
- **Testing:** `pytest`, in two physically-separated tiers — a fast, deterministic, no-network default run (`tests/`, the only tier `testpaths` collects) and an opt-in live tier (`tests-e2e/`) that builds and runs the nao-sim containers. Full strategy is specced in [testing.md](testing.md).
- **Type checking:** `pyright` (`standard` mode), a dev dependency run via `uv run pyright`. Config lives in `[tool.pyright]` in `pyproject.toml`, targeting `src`, `tests`, and `tests-e2e`, pinned to the `.venv`. `docker/` is not itself in pyright's `include` (its code runs in container images whose dependencies are not in the host venv), but `extraPaths` lists `docker/modules` and `docker/tts`, so the tests that import that code type-check.
- **Repo shape:**
  - `src/nao_sim/` — the package, one module per core concept.
  - `specs/` — pre-implementation design docs, one per concept (this folder).
  - `plans/` — implementation plans turning settled specs into buildable steps.
  - `tests/` at repo root, one test file per module under test.
  - `tests-e2e/` at repo root, for the live tier above — not collected by the default `pytest` run.
  - `docker/` — container recipes, Python 2.7 override modules (`modules/`), the `tts` engine container (`tts/`), and the gitignored `vendor/` for user-supplied suite tarballs.
- **No Aldebaran assets in git** (see [_overview.md](_overview.md), "Licensing"): `.gitignore` covers suite tarballs, `docker/vendor/`, meshes and textures. An automated asset guard is not built yet.

## Open questions

None currently.
