# Implementation plans

Implementation plans for nao-sim — each plan turns a settled part of a spec (see [specs/_index.md](../specs/_index.md)) into concrete, buildable steps. Plans are ordered by their date-time filename prefix (`YYYYMMDDHHmm_`).

## Plans

<!-- One row per plan, chronological by filename prefix. Keep the Status column in sync with each plan's `**Status:**` line. -->

| Plan | Description | Status |
|---|---|---|
| [202610081257_baseline-tests-speech-path.md](202610081257_baseline-tests-speech-path.md) | Tests for the spike-built container and speech path (fast tier + live tier on 2.1 and 2.8), stop-during-synthesis fix, Python 3.12 and libqi dependency, self-managed live stacks; promotes seven specs to Implemented | Done |
| [202610081600_suite-download.md](202610081600_suite-download.md) | `nao-sim-fetch-suite`: downloads the pinned Choregraphe suites from Aldebaran's GitHub repositories into `docker/vendor/`, hash-verified, skipping those already there | Done |
| [202610081900_animations-package-and-package-store.md](202610081900_animations-package-and-package-store.md) | `animations.pkg` extracted from the public robot images by `nao-sim-fetch-suite` into `docker/vendor/<version>/`, installed as a system package at boot; package store volume per version; per-Dockerfile ignore files | Done |
| [202610091000_status-service-and-healthcheck.md](202610091000_status-service-and-healthcheck.md) | `NaoSim` status service on 2.1 and 2.8 with its ALMemory keys, entrypoint that verifies the replacements and fails loudly, Docker healthcheck on `NaoSim.isReady`, version build argument | Done |
| [202610091500_fetch-and-build-images.md](202610091500_fetch-and-build-images.md) | `nao-sim fetch-and-build-images`: fetch the vendor files, build the images with an `io.nao-sim.version` label, verify they boot and record them; `check_images` for starts; the `nao-sim` command, `NaoSimError` hierarchy; compose project `nao-sim`; live tier builds through it | Done |
| [202610091830_faster-live-tier.md](202610091830_faster-live-tier.md) | Live tier builds only when `check_images` fails (new `io.nao-sim.recipes` label: an edit under `docker/` makes images outdated); vendor files not re-hashed when unchanged (`hashes.json`) | Done |

## Status legend

- **Todo** — written, not yet started
- **In progress** — actively being implemented
- **Done** — implemented, verified (lint/type-check/tests pass), and merged
