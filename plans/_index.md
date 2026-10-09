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
| [202610091200_fetch-and-build-images.md](202610091200_fetch-and-build-images.md) | `nao-sim fetch-and-build-images`: fetch the vendor files, build the images with an `io.nao-sim.version` label, verify they boot and record them; `check_images` for starts; the `nao-sim` command, `NaoSimError` hierarchy; compose project `nao-sim`; live tier builds through it | Done |
| [202610091240_faster-live-tier.md](202610091240_faster-live-tier.md) | Live tier builds only when `check_images` fails (new `io.nao-sim.recipes` label: an edit under `docker/` makes images outdated); vendor files not re-hashed when unchanged (`hashes.json`) | Done |
| [202610091320_tts-stops-on-sigterm.md](202610091320_tts-stops-on-sigterm.md) | The `tts` server handles `SIGTERM` as PID 1, so a stack stops in under a second instead of being killed after Docker's 10 s grace period | Done |
| [202610091350_split-entrypoint.md](202610091350_split-entrypoint.md) | One entrypoint per NAOqi version (`entrypoint-2.1.sh`, `entrypoint-2.8.sh`) over a shared `entrypoint-lib.sh`; the version's facts are constants in its script, not image environment variables | Done |
| [202610091600_drop-perception-source-key.md](202610091600_drop-perception-source-key.md) | The `NaoSim` status module stops writing `NaoSim/Perception/Source` (perception runs in the clients); fast and live status tests updated; `status-service.md` back to `Implemented` | Done |
| [202610091610_autonomous-abilities-on-2-1.md](202610091610_autonomous-abilities-on-2-1.md) | 2.1 entrypoint launches the built-ins a NAO autoloads (`expressiveness`, `basicawareness`, `autonomousblinking`, `autonomousmoves`) and then `autonomouslife`, in a NAO's order, failing the boot if one registers nothing; `container.md` back to `Implemented` | Done |
| [202610091719_audio-sinks.md](202610091719_audio-sinks.md) | The speaker becomes the audio output (`audio_output.py`, `AudioOutput`): `AudioSink` seam with `DevicePlayer`, `NullSink`, `WavSink`, `MemorySink`; pacing for every sink, newest-wins call discipline, `playing_until`; `audio-output.md` back to `Implemented` | Done |
| [202610091734_naosim-run.md](202610091734_naosim-run.md) | `NaoSimConfig`, the `NaoSim` object with the sim window, `read_status`/`cleanup`, `nao-sim run`/`cleanup`/`status`/`logs`; the audio output becomes internal (no command); live tier through `NaoSim` with a `MemorySink` | Done |
| [202610091947_ci-workflow.md](202610091947_ci-workflow.md) | `.github/workflows/ci.yml` (`check`, `fast-tier`, `e2e-sim` over 2.1 and 2.8 with a cached `docker save` of the images), `NAO_SIM_E2E_VERSION` making a version required in the live tier, the Python 2.7 compile check as a live test | Done |
| [202610092106_git-dependency.md](202610092106_git-dependency.md) | nao-sim as a uv git dependency: recipes as package data in the wheel (vendor excluded), `files.py` locating recipes and the vendor folder (`NAO_SIM_VENDOR`, user data directory), the vendor folder as a named build context, a live test installing nao-sim in a scratch project; README for depending projects | Done |
| [202610092201_image-data-rename.md](202610092201_image-data-rename.md) | The vendor folder becomes the image data everywhere: `NAO_SIM_IMAGE_DATA`, `--image-data`, `docker/image-data/`, `<user data>/nao-sim/image-data/`, the `image-data` build context, `PinnedFile` | Done |
| [202610092343_video-input-render.md](202610092343_video-input-render.md) | The render camera: `video_input.py` injecting VGA `CameraTop` frames from nao-viewer at `video_input.fps` (new config field), world started before the host devices, headless viewer with the render source in the live tier and a camera-loop live test on 2.1 and 2.8; webcam and bottom camera left out | Done |

## Status legend

- **Todo** — written, not yet started
- **In progress** — actively being implemented
- **Done** — implemented, verified (lint/type-check/tests pass), and merged
