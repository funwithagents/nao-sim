# nao-sim as a uv git dependency

**Status:** Done

Implements [specs/project.md](../specs/project.md) ("Distribution"), [specs/runtime/api.md](../specs/runtime/api.md) ("Files on disk") and the build-context change of [specs/container/container.md](../specs/container/container.md) ("Images"): a project that depends on `nao-sim[viewer]` from git runs `uv run nao-sim fetch-and-build-images`, `uv run nao-viewer fetch-meshes` and `uv run nao-sim run`, or a `NaoSim` in its code, exactly as a checkout does. It leaves out pip installs (project.md, open question 1) and changes nothing in nao-viewer, which is already install-safe.

## What was measured before writing it

- uv 0.11 applies nao-sim's `[tool.uv.sources]` to a git dependency: in a scratch project depending on `nao-sim[viewer]` at `09a5f43`, `qi` locked to the fork's wheels and nao-viewer to its pinned commit. The lock fails without the project's own `environments` (no `qi` 3.1.6 elsewhere).
- Installed that way today, `docker_images.DOCKER` is `.venv/lib/python3.13/docker` (missing), `recipes_digest()` is the empty hash, the 2.1 suite is downloaded into `.venv/lib/python3.13/docker/vendor/`, and the build fails on the missing `compose.yaml`.
- Hatch: `force-include` of `docker` also takes `docker/vendor/` (it ignores `exclude`). `only-include` + `sources` (`src/nao_sim` → `nao_sim`, `docker` → `nao_sim/docker`) + `exclude = ["docker/vendor", ...]` gives a wheel with the 17 recipe files and no vendor file, even from a checkout holding the suites; the sdist has none either. That remapping breaks hatch's editable install unless `dev-mode-dirs = ["src"]`, with which `uv sync` works and the editable `nao_sim` has no `docker/` (so a checkout falls back to its own).
- Compose 5.1 (OrbStack): `additional_contexts: vendor: ${NAO_SIM_VENDOR:-./vendor}/2.1` with `COPY --from=vendor` builds from a folder outside the context; `up --no-build` and `down` do not mind a missing vendor folder.
- In the scratch project, `nao-viewer` (with `fetch-meshes`) and `mjpython` are installed next to `nao-sim`, and nao-viewer's meshes resolve to the user's existing `~/Library/Application Support/nao-viewer/meshes/V40-r1`.

## Scope

- `pyproject.toml` — the wheel's `only-include`, `sources`, `exclude`, `dev-mode-dirs`; `platformdirs` as a runtime dependency; relock
- `src/nao_sim/files.py` — new: `RECIPES` (package data or the checkout's `docker/`), `VENDOR` (`NAO_SIM_VENDOR`, else the checkout's `docker/vendor/` or `platformdirs.user_data_dir("nao-sim")/vendor`), `INSTALLED`, and `compose_env()` (the environment every compose call gets, with `NAO_SIM_VENDOR`)
- `src/nao_sim/docker_images.py` — `DOCKER`/`COMPOSE`/`VENDOR` from `files`; `_build` and `_verify` pass `NAO_SIM_VENDOR` for the vendor folder they were given
- `src/nao_sim/suite.py` — `VENDOR` from `files`; its docstring stops naming `docker/vendor/` as the only place
- `src/nao_sim/stack.py` — compose calls get `files.compose_env()`
- `src/nao_sim/viewer.py` — the missing-extra message names the extra as a dependency (`nao-sim[viewer]`), not `pip install`
- `src/nao_sim/cli.py` — `--vendor`'s default from `files.VENDOR`
- `docker/compose.yaml` — `additional_contexts` on `naoqi21` and `naoqi28`
- `docker/Dockerfile.naoqi-2.1`, `docker/Dockerfile.naoqi-2.8` — `COPY --from=vendor` for the suite and `animations.pkg`
- `docker/Dockerfile.naoqi-2.{1,8}.dockerignore` — leave out all of `vendor/`
- `tests/test_files.py` — new: the locations in a checkout layout, an installed layout and with `NAO_SIM_VENDOR`
- `tests/test_docker_images.py`, `tests/fake_docker.py` — the vendor folder reaches compose as `NAO_SIM_VENDOR`
- `tests-e2e/test_install_live.py` — new: nao-sim installed in a scratch project as the wheel a git dependency builds (see Verification)
- `README.md` — "Use from another project": the `pyproject.toml` block of project.md, the three commands, `NAO_SIM_VENDOR`
- `AGENTS.md` — `files.py` in the module map; the `docker/` row says it ships as package data
- Spec frontmatter: `files.py` and `tests/test_files.py` into api.md; `tests-e2e/test_install_live.py` into project.md; back to `Implemented`: project.md, api.md, container.md (file and index)

## Steps

1. **Packaging.** Edit `[tool.hatch.build.targets.wheel]` as measured (comment: the recipes ship as package data, never the vendor files). Add `platformdirs`; `uv lock`. Check by hand: `uv build --wheel` lists `nao_sim/docker/...` and no `vendor`, and `uv sync` still installs editable.
2. **`files.py`.** `RECIPES = _package / "docker" if (_package / "docker" / "compose.yaml").is_file() else _package.parents[1] / "docker"`; `INSTALLED` says which. `VENDOR = Path(os.environ["NAO_SIM_VENDOR"])` when set, else `RECIPES / "vendor"` in a checkout and `user_data_dir("nao-sim") / "vendor"` installed. `compose_env(vendor=VENDOR)` returns `os.environ` plus `NAO_SIM_VENDOR=<vendor, absolute>`. The module reads the environment at import, as the rest of the package does with its paths.
3. **Use it.** `docker_images.DOCKER = files.RECIPES`, `COMPOSE = RECIPES / "compose.yaml"`, `VENDOR = files.VENDOR`; `_fetch_build_verify` builds its env from `compose_env(vendor)` plus the version and the digest; `suite.VENDOR = files.VENDOR` (no import cycle: `files` imports neither). `stack.py`'s compose calls take `compose_env()`. `cli.py`'s default follows. `recipes_digest` keeps skipping a top-level `vendor/`, which only a checkout has.
4. **Recipes.** In each NAOqi service of `compose.yaml`, `additional_contexts: {vendor: "${NAO_SIM_VENDOR:-./vendor}/<version>"}`. In each Dockerfile, `COPY --from=vendor ${SUITE} /tmp/suite.tar.gz` and `COPY --from=vendor animations.pkg ...`; the header comment says where the vendor files come from. The ignore files leave out `vendor/` whole. This changes the recipes digest: every machine rebuilds once, and CI's next run builds cold.
5. **Messages and docs.** `viewer.py`'s missing-extra message; README's "Use from another project"; AGENTS.md map.
6. **Fast tests.** `tests/test_files.py` drives `files` through a reload (or a pure function behind the constants, `locate(package_dir, environ)`, which the constants call) over tmp layouts: a package directory holding `docker/compose.yaml` is installed (recipes inside, vendor in the user data directory, with `platformdirs` pointed at a tmp home); one without it is a checkout (recipes and vendor beside `src/`); `NAO_SIM_VENDOR` wins in both. In `tests/test_docker_images.py`, a build with `vendor=tmp` gives compose `NAO_SIM_VENDOR=tmp` (the fake Docker records the environment it was called with).
7. **Live test, `tests-e2e/test_install_live.py`.** A module-scoped fixture writes a scratch project in `tmp_path` with project.md's `pyproject.toml` block, except that the source is `nao-sim = { path = "<checkout>", editable = false }`: uv then builds and installs the wheel exactly as from git, with nao-sim's own sources, without pushing a commit. It runs `uv sync` there (`unavailable()` without `uv`). Tests, each running Python or the commands of the scratch project's `.venv`:
   - the installed package holds `nao_sim/docker/compose.yaml`, both Dockerfiles, `modules/` and `tts/`, and no `vendor`;
   - its `recipes_digest()` equals the checkout's, so it accepts the images a checkout built;
   - `nao-sim --help` and `nao-viewer fetch-meshes --help` exit 0 (both commands are there for the project);
   - with `NAO_SIM_VENDOR` set to the checkout's `docker/vendor/`, `check_images(<version>)` passes in the scratch project;
   - with the same variable, the scratch project's `nao-sim run --config` of a headless, silent config boots the fixture's version from the installed recipes (the `nao` fixture is stopped first and restarted after, as the sim-window test does) and `nao-sim status` there reports it ready.
8. **Specs.** Frontmatter and statuses as in Scope; plan and index to `Done`.

## Verification

- `uv run ruff check .`, `uv run ruff format --check src tests tests-e2e docker/tts`, `uv run pyright`, `uv run pytest`.
- `uv run pytest tests-e2e -rs` on both versions (the images rebuild once for the new recipes), the new install tests among them.
- By hand, outside the repository: a scratch project depending on `nao-sim[viewer]` from the pushed branch's commit (`rev = <sha>`), with no `NAO_SIM_VENDOR`: `uv run nao-sim fetch-and-build-images 2.1` downloads into `~/Library/Application Support/nao-sim/vendor/2.1/` and builds; `uv run nao-viewer fetch-meshes` (already done on this machine: it reports the installed meshes); `uv run nao-sim run` opens the window with Aldebaran's meshes and speaks.
- CI green on the pull request: a cold build on both entries (new recipes digest), then the install tests in each.
