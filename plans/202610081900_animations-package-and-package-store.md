# Animations package and package store

**Status:** Done

Implements `specs/container/container.md` ("Vendor files and licensing", "Robot packages in the image", "Package store", the per-Dockerfile ignore files): `nao-sim-fetch-suite` fills `docker/vendor/<version>/` with the suite and the `animations.pkg` extracted from the public robot image, the images install it as a system package at boot, and a named volume per version keeps the package store across `docker compose down`. Leaves out the sound set (the user installs it) and `nao-sim up`.

## Scope

- `src/nao_sim/suite.py` — per-version pins (suite, robot image, package), `<vendor>/<version>/` layout, `.opn` parsing and decompression, extraction through `docker run alpine debugfs`
- `tests/test_suite.py` — the fetch rules for each file, `.opn` parsing and decompression on synthetic images, pins match the Dockerfiles
- `docker/Dockerfile.naoqi-2.1`, `docker/Dockerfile.naoqi-2.8` — suite from `vendor/<version>/`, `animations.pkg` into `/opt/naoqi/share/naoqi/apps/`, package store directory owned by `nao`
- `docker/Dockerfile.naoqi-2.1.dockerignore`, `docker/Dockerfile.naoqi-2.8.dockerignore` — new, keep only the version's own vendor files in the build context
- `docker/suite-2.1.sha256`, `docker/suite-2.8.sha256` — removed (pins move to `suite.py`)
- `docker/compose.yaml` — `packages-2.1` / `packages-2.8` volumes
- `tests-e2e/support.py` — vendor path per version, a way to restart the stack
- `tests-e2e/test_packages_live.py` — new: `animations` installed at boot, a user package survives `down`/`up`
- `tests-e2e/test_speech_live.py` — the animated-speech comment (the gestures now exist)
- `specs/container/container.md`, `specs/_overview.md`, `README.md`, `AGENTS.md` — docs

## Steps

1. `suite.py`: a `VendorFile(url, sha256)` and a `Version(name, suite, image, package_path, package_sha256)` table; `fetch_file()` (keep / refuse / download to `.part`, verify, rename); `opn_payload()` (parse the installer variables, offset and length, compression from the magic); `rootfs_chunks()` (stream-decompress); `docker_cat()` (pipe into `docker run -i --rm alpine:3.20 … debugfs -R "cat <path>"`, the result written to `.part`, verified, renamed); `fetch(version, vendor, cat)` orchestrating, deleting a downloaded `.opn` after use.
2. Fast tests: synthetic `.opn` files (header, installer with the variables, bzip2 and gzip payloads, trailing bytes) for parsing and decompression; the download rules against a local HTTP origin; the extraction path with the Docker step replaced by a stand-in that echoes a known package, checking `.part`/hash/rename and that a downloaded `.opn` is removed but a user's is kept.
3. Dockerfiles, ignore files, compose volumes; move the user's existing vendor files to the per-version folders.
4. Live tests; build both images from scratch and run the live tier.
5. Docs; spec back to `Implemented`, this plan `Done`.

## Verification

Done on Oct 8, 2026: lint, types and the fast tier pass; `nao-sim-fetch-suite` extracted and verified both packages (73 s with the suites already present, the downloaded robot images deleted after use) and a re-run downloads nothing; both images rebuilt (build contexts 436 MB and 1.34 GB, each its own version only); `uv run pytest tests-e2e` passes on 2.1 and 2.8 (14 tests), including `animations` installed at boot and a user package and `animations` surviving `down`/`up`.

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`; a real `nao-sim-fetch-suite` (extraction from both robot images); both images rebuilt; `uv run pytest tests-e2e` on both versions. Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
