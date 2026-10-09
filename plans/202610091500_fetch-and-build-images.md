# Fetch and build images

**Status:** Done

Implements `specs/runtime/api.md` ("Images: `fetch_and_build_images`", "Files on disk" for a checkout, the image part of "Errors"), the `fetch-and-build-images` command of `specs/runtime/cli.md`, and the image label of `specs/container/container.md`. Delivers the one slow step (fetch the vendor files, build the images, verify they boot) and the check `NaoSim.start()` will run on them; leaves out the `NaoSim` object, the config and every other CLI command, and the wheel layout (checkout only).

## Scope

- `src/nao_sim/errors.py` — new: `NaoSimError` and the errors the images step raises (`DockerUnavailableError`, `PortInUseError`, `ImagesMissingError`, `ImagesOutdatedError`, `BootError`, `FetchError`, `ImageBuildError`).
- `src/nao_sim/docker_images.py` (first written as `images.py`) — new: `fetch_and_build_images(versions=None)` (async), `check_images(version)`, the verified-image record `docker/vendor/images.json`.
- `src/nao_sim/suite.py` — `SuiteError` becomes `FetchError`; its `main()` and the `nao-sim-fetch-suite` script go (replaced by the command below).
- `src/nao_sim/cli.py` — new: the `nao-sim` command with its first subcommand, `fetch-and-build-images [2.1] [2.8]`; exit codes per `cli.md`.
- `src/nao_sim/__init__.py` — front door: `fetch_and_build_images`, `check_images`, the errors.
- `pyproject.toml` — `nao-sim` script in, `nao-sim-fetch-suite` out.
- `docker/compose.yaml` — project `name: nao-sim`; `build.labels` `io.nao-sim.version` on the three services.
- `tests/test_docker_images.py` — functional tests against a fake `docker` executable first on PATH.
- `tests/test_suite.py` — follows the rename; the CLI test moves to `tests/test_cli.py`.
- `tests/test_cli.py` — new: the command's exit codes and output.
- `tests-e2e/support.py` — `Stack.up` runs `fetch_and_build_images` when the vendor files are there (instead of `compose up --build`), else requires `check_images` to pass; then `compose up -d` without building.
- `tests-e2e/test_docker_images_live.py` — new: the images carry the label and pass `check_images` after the step.
- Docs: `AGENTS.md` project map, `README.md`, spec frontmatter and statuses (`api.md`, `cli.md`, `container.md`), `specs/_index.md`, this plan's row.

## Steps

1. `errors.py` with the hierarchy above.
2. `compose.yaml`: `name: nao-sim` (the package store volumes become `nao-sim_packages-*`; the old `docker_packages-*` volumes are left in place), and `labels: {io.nao-sim.version: ${NAO_SIM_VERSION:-dev}}` under each `build`.
3. `suite.py`: rename the error, drop `main`.
4. `docker_images.py`:
   - per-version table (NAOqi image tag, compose service, container, profile) and the `tts` image tag;
   - `check_images(version, vendor=VENDOR)`: both images exist (`docker image inspect`), carry the installed nao-sim version in the label, and their IDs are in `images.json`; else `ImagesMissingError` / `ImagesOutdatedError`, each naming `nao-sim fetch-and-build-images <version>`;
   - `fetch_and_build_images(versions=None, vendor=VENDOR)`: checks Docker (`docker info`) and that 9559 is free, then per version: `suite.fetch` (in a thread), `docker compose build tts <service>` with `NAO_SIM_VERSION` set, and the verification boot (`compose up -d`, wait `healthy` within 240 s, the `tts` container answers `/health`, `compose down` in every case). A boot failure is a `BootError` with the end of the logs; a build failure an `ImageBuildError`. Only verified image IDs are recorded.
5. `cli.py` and the script entry; unknown versions are an argparse error (exit 2), a `NaoSimError` prints `error: …` and exits 1.
6. Tests: a fake `docker` (Python script on PATH, state in a JSON file) that answers `info`, `image inspect`, `compose build` (stores an ID and the label from the environment), `compose up`/`down`, `inspect` (health from the fake's settings), `exec` and `logs`.
7. Live tier switch, then the live test.
8. Docs and statuses.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`, and `uv run pytest tests-e2e` (both versions build, verify and pass the existing live tests). Then mark this plan `Done`, `container.md` `Implemented`.
