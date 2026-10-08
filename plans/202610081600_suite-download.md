# Suite download

**Status:** Done

Implements `specs/container.md` ("Suites and licensing"): `nao-sim-fetch-suite` downloads the pinned Choregraphe suites from Aldebaran's GitHub repositories into `docker/vendor/`, keeps a suite already there and verifies every file against `docker/suite-*.sha256`. Leaves out `nao-sim up` (which will call it) and the robot packages, which the user installs into the sim as on a robot.

## Scope

- `src/nao_sim/suite.py` — `Suite`, `SUITES` (from the `.sha256` files plus each repository's LFS media URL), `fetch()`, the `main()` CLI
- `pyproject.toml` — `nao-sim-fetch-suite` script
- `tests/test_suite.py` — download, keep-if-present, bad download, mismatching local file, CLI, pins match the Dockerfiles; against a local HTTP server (no network)
- `tests-e2e/support.py` — the skip message names the command
- `specs/container.md`, `specs/_overview.md`, `AGENTS.md`, `README.md` — the download, the licensing note, the project map

## Steps

1. Read the pinned name and hash from `docker/suite-<version>.sha256`; the URL is the repository's `media.githubusercontent.com` path plus the name.
2. `fetch(suite, vendor)`: an existing file with the pinned hash is kept; with another hash it is an error and left alone; otherwise stream to `<file>.part`, hashing on the fly, and rename only on a hash match (the `.part` is removed either way).
3. `main()`: versions as positionals (default all), `--vendor`, exit 1 on a hash or I/O error.
4. Fast-tier tests against a local HTTP origin that counts requests.
5. Docs and project map.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest` all pass. Checked by hand that both pinned URLs answer 200 with the pinned sizes (431 MB and 1.33 GB), and that `nao-sim-fetch-suite` with both suites already in `docker/vendor/` downloads nothing.
