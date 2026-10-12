---
code:
  - pyproject.toml
  - src/nao_sim/files.py
tests:
  - tests/test_project_map.py
  - tests/test_files.py
  - tests-e2e/test_install_live.py
---

# Project

**Status:** Implemented

## Purpose

Structure and tooling for the nao-sim project itself: Python version, dependency/packaging management with `uv`, repo layout conventions, development tooling, and how nao-sim is distributed.

## Decided

- **Python version:** 3.12 or 3.13 for host code (`requires-python = ">=3.12,<3.14"`, as nao-viewer), capped by the libqi wheels. Code that runs inside NAOqi (`docker/modules/`) is Python 2.7, imposed by the suites' embedded interpreter. `.python-version` pins 3.12 for the dev venv.
- **libqi:** `qi==3.1.6` is a runtime dependency: nao-sim's host side talks to NAOqi over qi (camera injection, viewer, probe, live tests), so it does not run without it. The wheels come from the GitHub Releases of the [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python) fork, one direct URL per platform and Python version in `[tool.uv.sources]`, exactly as in nao-viewer; this also keeps uv from picking Aldebaran's older `qi` 3.1.5 on PyPI.
- **Platforms:** the fork ships wheels for macOS 15+ on arm64 and Linux x86_64 (glibc 2.34+) only, so `[tool.uv] environments` limits the lock to those two. Elsewhere (Windows, Intel macOS, Linux arm64, older glibc or macOS) installation fails instead of producing a nao-sim that cannot reach NAOqi; wider coverage is a libqi fork task (see the overview's open questions).
- **Package layout:** `src/` layout — `src/nao_sim/...` — not flat, to avoid accidentally importing an uninstalled package from the repo root.
- **Dependency/venv management:** `uv`. Dev tooling lives in the `dev` dependency group (`uv sync --dev`), not in runtime `dependencies`. Build backend: `hatchling` (wheel packages `src/nao_sim`).
- **Linting/formatting:** `ruff`, excluding `docker/modules/` (Python 2.7) and the local `spike/` scripts.
- **Testing:** `pytest`, in two physically-separated tiers — a fast, deterministic, no-network default run (`tests/`, the only tier `testpaths` collects) and an opt-in live tier (`tests-e2e/`) that builds and runs the nao-sim containers. Full strategy is specced in [testing.md](testing/testing.md).
- **Type checking:** `pyright` (`standard` mode), a dev dependency run via `uv run pyright`. Config lives in `[tool.pyright]` in `pyproject.toml`, targeting `src`, `tests`, and `tests-e2e`, pinned to the `.venv`. `docker/` is not itself in pyright's `include` (its code runs in container images whose dependencies are not in the host venv), but `extraPaths` lists `docker/modules` and `docker/tts`, so the tests that import that code type-check.
- **Repo shape:**
  - `src/nao_sim/` — the package, one module per core concept.
  - `specs/` — pre-implementation design docs, one per concept, in one folder per architecture layer (`runtime/`, `container/`, `services/`, `host/`, `testing/`); this spec, the overview, the index and the template stay at the root.
  - `plans/` — implementation plans turning settled specs into buildable steps.
  - `tests/` at repo root, one test file per module under test.
  - `tests-e2e/` at repo root, for the live tier above — not collected by the default `pytest` run.
  - `docker/` — container recipes, Python 2.7 override modules (`modules/`), the `tts` engine container (`tts/`), and the gitignored `image-data/` for user-supplied suite tarballs.
  - `examples/configs/` — ready-to-use config files ([config.md](runtime/config.md), "Example files"), once the config is built.
  - `.github/workflows/` — CI ([ci.md](testing/ci.md)), once built.
- **No Aldebaran assets in git** (see [_overview.md](_overview.md), "Licensing"): `.gitignore` covers suite tarballs, `docker/image-data/`, meshes and textures. An automated asset guard is not built yet.

### Distribution

nao-sim is distributed through its GitHub repository, not PyPI: another project depends on it as a **uv git dependency** pinned to a commit or tag. pip is not supported (see "Dependencies of a git install").

- **In a project**: the project's `pyproject.toml` declares

  ```toml
  [project]
  requires-python = ">=3.12,<3.14"            # the libqi wheels' range
  dependencies = ["nao-sim[viewer]"]          # or "nao-sim" for no window and no render camera

  [tool.uv.sources]
  nao-sim = { git = "https://github.com/funwithagents/nao-sim", rev = "<commit or tag>" }

  [tool.uv]
  environments = [                             # the platforms the libqi wheels exist for
      "sys_platform == 'darwin' and platform_machine == 'arm64'",
      "sys_platform == 'linux' and platform_machine == 'x86_64'",
  ]
  ```

  then, once per machine, `uv run nao-sim fetch-and-build-images` (the images) and, for Aldebaran's look in the window, `uv run nao-viewer fetch-meshes` (its typed license acceptance); `uv run nao-sim run --config ...` or a `NaoSim` in the project's code then runs the simulated NAO. Docker, the suite download, the images and the meshes are never uv's job.
- **Dependencies of a git install.** uv applies nao-sim's own `[tool.uv.sources]` to a git dependency (measured with uv 0.11): `qi` resolves to the libqi fork's wheels and nao-viewer to its pinned commit, with nothing for the depending project to repeat. That project only has to stay within the wheels' platforms and Pythons (`requires-python` and `environments` above); without them the lock fails on the platforms with no `qi` 3.1.6. It must not pin nao-viewer itself at another commit: nao-sim's pin is the one tested with it. pip ignores `[tool.uv.sources]` and would look for `qi` 3.1.6 on PyPI, which has none.
- **The wheel** a git install builds holds `nao_sim` and, as its package data, the container recipes under `nao_sim/docker/`: everything under `docker/` but `image-data/` and Python caches (Dockerfiles and their ignore files, compose, entrypoints, healthcheck, `modules/`, `relay/`, the native relay's C++ source, `tts/`), none of it an Aldebaran file. Hatch maps `src/nao_sim` and `docker` into the package (`only-include` and `sources`) and excludes `docker/image-data`, so even a wheel built from a checkout holding the suites carries none; `dev-mode-dirs = ["src"]` keeps the editable install of a checkout working, since hatch cannot make an editable install from a remapped path. The sdist is the repository's tracked files, which never include the image data either.
- **Where the files are** ([api.md](runtime/api.md), "Files on disk"): an installed nao-sim reads its recipes from the package and keeps the image data in the user data directory; a checkout uses `docker/` and `docker/image-data/` as today. Both build the images the same way, and compute the same `io.nao-sim.recipes` digest from the same recipes.
- **nao-viewer behind the extra** needs nothing more: its model and scenes are its package data, its meshes live in its own user data directory (`platformdirs.user_data_dir("nao-viewer")/meshes`), so one `fetch-meshes` serves every project and checkout on the machine, and its `nao-viewer` command and MuJoCo's `mjpython` (the macOS window) are installed in the depending project's environment with it.
- **Runtime dependencies**: `numpy`, `qi`, `sounddevice`, `platformdirs`; the `viewer` extra adds nao-viewer. The webcam's OpenCV is decided with [video-input.md](host/video-input.md).
- **Versions**: a depending project pins a commit or tag in its `[tool.uv.sources]` and moves it on purpose. The package version is baked into the images (`io.nao-sim.version`, `NaoSim/Version`) next to the recipes digest, which is what tells a commit's images from another's: moving to a commit that changed `docker/` makes `start()` ask for a rebuild, and one that did not reuses the images. The version is bumped by hand, with a tag, when a change is worth naming; the README carries the compatibility of nao-sim, nao-viewer and the NAOqi versions.
- **Tested** by the live tier (`tests-e2e/test_install_live.py`): a scratch project installs this checkout as the wheel a git dependency builds, and runs `nao-sim run` from it on each version.

## Open questions

1. **pip.** Installing with pip from the repository needs the libqi wheels from somewhere pip looks (a find-links URL, an index on GitHub Pages); deferred until someone needs pip.
