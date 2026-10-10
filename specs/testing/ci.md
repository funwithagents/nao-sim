---
code:
  - .github/workflows/ci.yml
  - tests-e2e/support.py
  - tests-e2e/conftest.py
tests:
  - tests-e2e/test_modules_live.py
---

# Continuous integration

**Status:** Updated

## Purpose

Both test tiers ([testing.md](testing.md)) run on GitHub's hosted runners for every pull request and every push to `main`, so the verification gate of [AGENTS.md](../../AGENTS.md) (lint, type check, tests) is a machine's verdict on each change and not only a local command. The live tier runs against real NAOqi stacks that the runner fetches, builds and verifies itself, since the image data are Aldebaran's public downloads. Like [testing.md](testing.md), this is a cross-cutting practice, not a runtime concept: it is implemented by `.github/workflows/ci.yml` and by the live tier's switch from skipping to failing (`tests-e2e/support.py`, `tests-e2e/conftest.py`).

Three jobs side by side: a static gate, the fast tier and a live matrix. The image cache follows nao-viewer's CI, which already builds nao-sim's 2.1 images on its runners.

## Decided

### The runner

- **GitHub-hosted Linux, the free tier.** Every job runs on `ubuntu-24.04` (x86_64), pinned by name rather than `ubuntu-latest`, so Docker, Mesa and the system libraries move only when the pin is bumped on purpose. No self-hosted runner.
- **Linux is the platform** because it runs the NAOqi images natively (amd64, no emulation as on Apple Silicon) and has a display-less GL backend, Mesa's EGL, for the headless viewer's renders. GitHub's macOS runners have no Docker, so they could run the fast tier only. A green run is also the "works on Linux" half of milestone 3's exit ([_overview.md](../_overview.md), "Milestones").
- **One Python**, 3.12, the floor of `requires-python` and the version `.python-version` names; uv installs it.

### The workflow

One file, `.github/workflows/ci.yml`. It triggers on `pull_request`, on `push` to `main` and on `workflow_dispatch`. Concurrency is one run per ref: a newer push cancels the older run still in flight.

| Job | What |
| --- | --- |
| `check` | `uv sync --locked`, then `ruff check .`, `ruff format --check src tests tests-e2e docker/tts`, `pyright` |
| `fast-tier` | The same environment; `uv run pytest -rs` |
| `e2e-sim` | A matrix over the NAOqi versions (`2.1`, `2.8`), `fail-fast: false`, each entry on its own runner: restore or build the version's images, then `uv run pytest tests-e2e -rs` on that version only |

- The three jobs run side by side and none waits on another: a run takes as long as its slowest job, a live entry.
- **`--locked`**: the sync fails when `uv.lock` does not match `pyproject.toml`, so a dependency edit lands with its relock. The sync installs the `dev` group, so the `viewer` extra (nao-viewer, from its pinned Git commit) is there in every job.
- **The format check covers the code directories only**, since `ruff format .` would reflow the Python blocks inside Markdown files. `docker/modules/` is Python 2.7, outside ruff ([project.md](../project.md)).
- **Audio only where it is tested.** `sounddevice` is imported at the first stream of the device sink and when the microphone opens ([audio-output.md](../host/audio-output.md), [audio-input.md](../host/audio-input.md)): the `check` and `fast-tier` jobs fake it and need no sound system. The live entries get a **virtual loopback**, a PulseAudio null sink as the default output and its monitor as the default input (a virtual microphone wired to a virtual loudspeaker), so the live tier's loopback tests run on every push: the `mic` source, the microphone gate with the robot's own speech coming back into the microphone, and the `DevicePlayer` sink ([testing.md](testing.md), "Live tier"). The `MemorySink` stays the live tier's sink for every other test.
- **One version per live entry.** Both versions publish 9559 and one nao-sim runs per machine, so each version gets its own runner. The entry sets `NAO_SIM_E2E_VERSION` to its version: the `nao` fixture then runs that version only, and a missing suite, image or Docker **fails** the entry instead of skipping it. An unknown value fails the session at collection. Without the variable (a local run) the tier keeps its rule of skipping what the machine lacks ([testing.md](testing.md), "Skip, never fail, without the means"); in CI a skip would turn the job green with nothing tested.
- **Each job carries a `timeout-minutes`** well under GitHub's default (10 for `check`, 15 for `fast-tier`, 45 for a live entry, whose cold build is the longest step), so a hung boot fails in minutes.

### The live entries

In order:

1. **Disk.** The 2.8 image is about 6.3 GB, its `docker save` archive as much again, and the suite 1.3 GB on a cold build: the entry first deletes the runner's preinstalled toolchains nao-sim never uses (Android SDK, .NET, GHC, CodeQL), which frees about 25 GB. Both entries do it, so they stay alike.
2. **Sync**: `uv sync --locked`.
3. **The cache key**, computed by nao-sim itself: `naoqi-<version>-<nao-sim version>-<recipes digest>-<hash of src/nao_sim/suite.py>`. The first two parts are what `check_images` compares to the image labels ([api.md](../runtime/api.md), "Images"), so the key changes exactly when a start would find the images outdated; the suite pins' hash covers a new suite or package, which the labels do not see.
4. **Restore** (`actions/cache/restore`): one archive per version, `docker save` of the version's NAOqi image and the `tts` image, together with `docker/image-data/images.json`, the record of the verified image IDs. On a hit, `docker load` and the archive is deleted at once to free its space: the image IDs survive the save and load, so `check_images` accepts the images as verified.
5. **On a miss**: `uv run nao-sim fetch-and-build-images <version>`, which fetches the pinned image data (the suite, the robot image for the `animations` package, and the build files of the native relay: the version's C++ SDK, 334 MB for 2.1 and 1.1 GB for 2.8, plus libqi and boost for 2.8; [container.md](../container/container.md), "Build files"), builds the images and verifies they boot, as on a user's machine; then `docker save` and **save** (`actions/cache/save`) right away, before the tests, so a failing live tier does not rebuild on the next run. The image data are never cached, as in nao-viewer's CI: they are needed only on a miss, and a miss downloads them from Aldebaran's repositories.
6. **System packages**: Mesa's GL and a virtual display (`xvfb`, `xauth`, `libgl1`, `libglx-mesa0`, `libegl1`, `libgl1-mesa-dri`), and audio (`pulseaudio`, `pulseaudio-utils` for `pactl`, `paplay` and `parec`, `libportaudio2`, which `sounddevice` takes from the system on Linux, and `libasound2-plugins`, which routes ALSA's default device, the one PortAudio opens, to PulseAudio).
7. **The audio loopback**: `pulseaudio --start --exit-idle-time=-1`, a null sink `ci` (`pactl load-module module-null-sink sink_name=ci`), set as the default sink with `ci.monitor` as the default source; `pactl info` in the log. The same setup as reachy-mini-bridge's live job.
8. **The live tier**: `uv run pytest tests-e2e -rs` with `NAO_SIM_E2E_VERSION` and `NAO_SIM_E2E_AUDIO=loopback`, under `xvfb-run`, so the sim-window test runs on the 2.1 entry instead of skipping for want of a display, and the loopback tests fail rather than skip if the loopback is missing. Warnings and errors are logged live (`-o log_cli=true --log-cli-level=WARNING`).
9. **On failure**: the end of the NAOqi and `tts` containers' logs, if any are still there (`nao-sim logs` needs a running stack, so the step uses `docker logs` on the containers the test left behind, and prints nothing when the `NaoSim` stopped cleanly).

- **Sizes.** Measured locally: the 2.1 image is 4.5 GB on disk (1.4 GB compressed), the 2.8 image 6.3 GB (2.7 GB), `tts` 0.8 GB (0.27 GB). With zstd, the two archives take about 5 GB of the repository's 10 GB cache budget; an edit under `docker/` adds a new pair, and GitHub evicts the least recently used.
- **Python 2.7 check.** A live test compiles every module in the image's `/opt/naoqi/modules/` with the image's own interpreter (`/opt/naoqi/bin/python2 -m compileall`), so a module the version does not load is still checked; both entries run it, closing [testing.md](testing.md)'s open question 2.
- **The headless viewer**: nao-viewer renders through EGL (`MUJOCO_GL=egl`, which it sets itself for a headless viewer on Linux, with the job's `libegl1` and `libgl1-mesa-dri`), and the live tier runs a headless viewer with the render camera and the placeholder variant, so the camera loop is tested on every push ([viewer.md](../host/viewer.md), "In the live tier and CI"). A viewer that fails to launch fails the entry. CI never accepts the meshes' license.

### Expected skips

The tests that skip by design on a runner; any other skip in a CI log is a fault.

| Job | Test | Why |
| --- | --- | --- |
| `e2e-sim` (2.8) | `test_naosim_live.py::test_the_sim_window` | The window does not depend on the NAOqi version: checked on the 2.1 entry |

### Licensing

The runner downloads Aldebaran's suites and robot images from their public repositories and builds images from them, as a user does on their machine. The images go to the repository's private Actions cache only; nothing is pushed to a registry or attached to a release, and no workflow artifact contains a file of the image data or an image. This is the same practice as nao-viewer's CI, under the rule of [AGENTS.md](../../AGENTS.md): images built from the suite are never pushed.

### Secrets and protection

- **No secret is required**: every job is green with none.
- **The status checks to require on `main`** are `check`, `fast-tier` and both `e2e-sim` entries; requiring them is a repository setting on GitHub, outside the repo.

### Downstream repositories

nao-viewer pins a nao-sim commit for its own live job (`NAO_SIM_REF`) and bumps it on purpose. nao-sim's CI does not test it.

## Measured

On the first runs (PR #1, October 9, 2026):

| | Cold (build) | Cache hit |
| --- | --- | --- |
| `check` | 15 s | 12 s |
| `fast-tier` | 42 s | 43 s |
| `e2e-sim` 2.1 | 6 min 39 s (tests 2 min 16 s) | 5 min 11 s (tests 2 min 12 s) |
| `e2e-sim` 2.8 | 6 min 54 s (tests 1 min 33 s) | 3 min 49 s (tests 1 min 44 s) |

- **The cache.** The archives take 1.5 GB (2.1) and 2.9 GB (2.8), 4.5 GB of the 10 GB budget; an edit under `docker/` adds a new pair while the old one ages out. A hit loads the images and skips the build: the image IDs survive `docker save`/`docker load`, so `check_images` accepts them as verified.
- **Skips.** Only the expected one, on the 2.8 entry; the window test runs and passes under Xvfb on 2.1.

## Open questions

None: the cache budget and the time budget were measured above. Revisit them if an edit under `docker/` becomes frequent enough for the eviction of the old archives to matter.
