# Faster live tier

**Status:** Done

Implements two refinements of `specs/api.md` ("Images") and `specs/container.md` ("Fetching the vendor files"), and the live-tier rule of `specs/testing.md`: the live tier builds and verifies a version only when its images do not pass `check_images`, and fetching re-hashes a vendor file only when it changed. Leaves the tests themselves unchanged: speech plays in real time on purpose.

## Scope

- `src/nao_sim/docker_images.py` — `recipes_digest()` over `docker/` (vendor files, hidden files and caches excluded), passed to the build as `NAO_SIM_RECIPES`; `check_images` raises `ImagesOutdatedError` when an image's `io.nao-sim.recipes` label differs from the checkout's digest.
- `docker/compose.yaml` — `io.nao-sim.recipes: ${NAO_SIM_RECIPES:-}` next to the version label on the three services.
- `src/nao_sim/suite.py` — `hashes.json` in the vendor folder: a file whose size and modification time match its recorded entry for the pinned hash is not hashed again.
- `tests-e2e/support.py` — `Stack.up` runs `check_images` first and builds only when it raises.
- `tests/test_docker_images.py`, `tests/test_suite.py` — functional tests for both.
- Specs (`api.md`, `container.md`, `testing.md`), this plan's row.

## Steps

1. `recipes_digest(docker=DOCKER)`: SHA-256 over the sorted relative paths and contents of the files under `docker/`, skipping `vendor/`, any path part starting with `.` and `__pycache__`/`*.pyc`.
2. `_fetch_build_verify` sets `NAO_SIM_RECIPES` in the build environment; `check_images` compares the label after the version check.
3. `suite._present` consults and `suite._write` updates `<vendor>/hashes.json` (`{relative path: {size, mtime_ns, sha256}}`); a mismatch on size or time means hashing again, a stale or unreadable record is ignored.
4. Live tier: `check_images` passes → no build; `ImagesMissingError`/`ImagesOutdatedError` → `fetch_and_build_images` when the vendor files are there, else skip.
5. Tests, specs, statuses.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`, then `uv run pytest tests-e2e --durations=0` twice: the first run may build, the second must not build or verify and is the new reference time. Then mark this plan `Done`.
