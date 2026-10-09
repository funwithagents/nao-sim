---
code:
tests:
---

# Continuous integration

**Status:** Draft

## Purpose

Both test tiers ([testing.md](testing.md)) run on GitHub's hosted runners for every pull request and every push to `main`, so the verification gate of [AGENTS.md](../../AGENTS.md) (lint, type check, tests) is a machine's verdict on each change and not only a local command. The live tier runs against real NAOqi stacks that the runner fetches, builds and verifies itself, since the vendor files are Aldebaran's public downloads. Like [testing.md](testing.md), this is a cross-cutting practice, not a runtime concept: the one file that implements it is `.github/workflows/ci.yml`.

The jobs follow reachy-mini-bridge's CI (its `specs/testing/ci.md`) on purpose: a static gate, the fast tier and a live matrix, side by side.

## Decided

### The runner

- **GitHub-hosted Linux, the free tier.** Every job runs on `ubuntu-24.04` (x86_64), pinned by name rather than `ubuntu-latest`, so Docker, Mesa and the system libraries move only when the pin is bumped on purpose. No self-hosted runner.
- **Linux is the platform** because it runs the NAOqi images natively (amd64, no emulation as on Apple Silicon) and has a display-less GL backend, Mesa's EGL, for the headless viewer's renders. GitHub's macOS runners have no Docker, so they could run the fast tier only.
- **One Python**, 3.12, the floor of `requires-python` and the version `.python-version` names; uv installs it.

### The workflow

One file, `.github/workflows/ci.yml`. It triggers on `pull_request`, on `push` to `main` and on `workflow_dispatch`. Concurrency is one run per ref: a newer push cancels the older run still in flight.

| Job | What |
| --- | --- |
| `check` | `uv sync --locked`, then `ruff check .`, `ruff format --check src tests tests-e2e docker/tts`, `pyright` |
| `fast-tier` | The same environment; `uv run pytest` |
| `e2e-sim` | A matrix over the NAOqi versions (`2.1`, `2.8`), `fail-fast: false`, each entry on its own runner: build the version's images, then `uv run pytest tests-e2e -rs` on that version only |

- The three jobs run side by side and none waits on another: a run takes as long as its slowest job, a live entry.
- **`--locked`**: the sync fails when `uv.lock` does not match `pyproject.toml`, so a dependency edit lands with its relock.
- **The format check covers the code directories only**, since `ruff format .` would reflow the Python blocks inside Markdown files. `docker/modules/` is Python 2.7, outside ruff ([project.md](../project.md)).
- **One version per live entry.** Both versions publish 9559 and one nao-sim runs per machine, so each version gets its own runner. The entry sets `NAO_SIM_E2E_VERSION` to its version: the `nao` fixture then runs that version only, and a missing suite, image or Docker **fails** the entry instead of skipping it. Without the variable (a local run) the tier keeps its rule of skipping what the machine lacks ([testing.md](testing.md), "Skip, never fail, without the means"); in CI a skip would turn the job green with nothing tested.
- **Each job carries a `timeout-minutes`** well under GitHub's default, so a hung boot fails in minutes.

### The live entries

- **Images.** The entry runs `uv run nao-sim fetch-and-build-images <version>`, which fetches the pinned vendor files, builds the images and verifies they boot ([api.md](../runtime/api.md), "Images"); the live tier then finds them current through `check_images`.
- **Caches** (`actions/cache`): the vendor files, keyed on their pinned hashes, and the built images (`docker save`/`docker load`), keyed on the `io.nao-sim.recipes` digest of `docker/` and the nao-sim version, so an edit under `docker/` rebuilds. The 2.1 images take about 2.5 minutes cold and 2 with the cache (measured by nao-viewer's CI); the 2.8 images are about 2.4 GB against the repository's 10 GB cache budget.
- **Audio.** No sound device is needed: the live tier plays speech into a silent audio output today and a `MemorySink` once it runs through `NaoSim` ([audio-output.md](../host/audio-output.md)). `libportaudio2` is installed for the `sounddevice` import of the `play` sink.
- **The viewer**, as soon as [viewer.md](../host/viewer.md) is built: the entry installs the `viewer` extra and Mesa's EGL libraries (`libegl1`, `libgl1-mesa-dri`), sets `MUJOCO_GL=egl`, and the live tier runs a headless viewer with the render camera and the placeholder variant, so the camera loop is tested on every push ([viewer.md](../host/viewer.md), "In the live tier and CI"). A viewer that fails to launch fails the entry. CI never accepts the meshes' license.
- **Python 2.7 check.** Before the tests, the entry compiles `docker/modules/*.py` with the image's own interpreter (`docker run --rm <image> /opt/naoqi/bin/python2 -m py_compile ...`), closing [testing.md](testing.md)'s open question 2.

### Licensing

The runner downloads Aldebaran's suites and robot images from their public repositories and builds images from them, as a user does on their machine. The images go to the repository's private Actions cache only; nothing is pushed to a registry or attached to a release, and no workflow artifact contains a vendor file or an image. This is the same practice as nao-viewer's CI, under the rule of [AGENTS.md](../../AGENTS.md): images built from the suite are never pushed.

### Secrets and protection

- **No secret is required**: every job is green with none.
- **The status checks to require on `main`** are `check`, `fast-tier` and both `e2e-sim` entries; requiring them is a repository setting on GitHub, outside the repo.

### Downstream repositories

nao-viewer and nao-bridge pin a nao-sim commit for their own live jobs and bump it on purpose (nao-viewer's `NAO_SIM_REF` today). nao-sim's CI does not test them.

## Open questions

1. **The 2.8 cache.** Whether the 2.8 images fit the cache budget next to 2.1's, or whether the 2.8 entry builds cold on every run (to measure on the first runs).
2. **Expected skips.** The table of the tests that skip by design on a runner (with reasons), as reachy-mini-bridge's spec keeps; written with the workflow, once its first runs show them.
3. **Time budget.** Measured on the first runs; the live entries are expected to dominate (image load, boot, speech in real time).
4. **The legal question on the suite download** (the toolkit document's open question): if Aldebaran's terms require a typed acceptance, CI needs a non-interactive equivalent.
