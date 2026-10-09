---
code:
  - docker/Dockerfile.naoqi-2.1
  - docker/Dockerfile.naoqi-2.8
  - docker/compose.yaml
  - docker/entrypoint.sh
  - docker/healthcheck.sh
  - docker/Dockerfile.naoqi-2.1.dockerignore
  - docker/Dockerfile.naoqi-2.8.dockerignore
  - src/nao_sim/suite.py
tests:
  - tests-e2e/test_speech_live.py
  - tests/test_suite.py
  - tests/test_entrypoint.py
  - tests-e2e/test_packages_live.py
  - tests-e2e/test_status_live.py
---

# NAOqi container

**Status:** Implemented

## Purpose

The container gives the desktop `naoqi-bin` from the user's Choregraphe suite the old Linux it expects, on every platform, and exposes it on one port as a real robot would: `127.0.0.1:9559`. It is the only way nao-sim runs NAOqi (there is no native mode). How built-in services are replaced inside it is in [service-replacement.md](service-replacement.md); this spec covers the image, the network layout, boot and the entrypoint's configuration interface.

## Decided

### Vendor files and licensing

Each image is built from two Aldebaran files per version, kept in `docker/vendor/<version>/` (gitignored): the Choregraphe suite and the robot's `animations` package. The image is built locally, tagged locally (`nao-sim/naoqi:<version>`) and never pushed: it contains Aldebaran's software.

| Version | Suite (from the repository's `Choregraphe/Linux/Binaries` or root) | Robot image the package comes from | `animations.pkg` |
| --- | --- | --- | --- |
| 2.1.4.13 (NAO V4/V5) | [aldebaran/NAO-V5-ressources](https://github.com/aldebaran/NAO-V5-ressources), `choregraphe-suite-2.1.4.13-linux64.tar.gz` (431 MB), SHA-256 `bad0212956e2223f36736cff33bdc1e008311b8bf9efd81a52dcf05895c8abce` | Same repository, `NAOqi 2.1.4.13/NAOqi Images/opennao-atom-system-image-2.1.4.13_2015-08-27.opn` (377 MB), SHA-256 `5d18427ba6f5199d30cf29941b20ad5fa6a06b8f64a29126953cdfa33dbb9a24`; package at `/usr/share/naoqi/apps/animations.pkg` | version 5.0.9, SHA-256 `a1d46221f5f28b91c8e7564ade4532f390e5911f14210787b3352a84c2b507e1` |
| 2.8.7.4 (NAO V6) | [aldebaran/nao6-binaries](https://github.com/aldebaran/nao6-binaries), branch `master`, `choregraphe-suite-2.8.7.4-linux64.tar.gz` (1.33 GB), SHA-256 `edf95da2ae8ec7573e3a590b6db47a472f9d2733280a4a597841fbf0c1e6c63c` | Same repository, `nao-x86-2.8.7.4_20210820_094013.opn` (732 MB), SHA-256 `d82e5dd221712555f20c430f3ebcbe46825d5179f1bc0e2594629489855e24a4`; package at `/opt/aldebaran/share/naoqi/apps/animations.pkg` | version 7.0.3, SHA-256 `8866ddf4bb45eab79068cfe5746c66f3b8f507356fd93affed204bc834002f2c` |

- All files are Git LFS: they are downloaded from `media.githubusercontent.com/media/aldebaran/<repo>/<branch>/<path>` (the raw URL returns a pointer). The pins (URL, file name, SHA-256, path inside the image) live in `src/nao_sim/suite.py`.
- Use the Binaries tarball, not the 2.1 `.run` setup: it is a static self-extractor that crashes under Rosetta (`bss_size overflow`).
- Neither suite has the `animations` package (the `animations/Stand/Gestures/*` behaviours that `ALAnimatedSpeech` runs): the robot image is its only public source. Both versions' packages are behaviours (`.xar`) and `.ogg` only, no native code, with the same 224 `Stand/Gestures` behaviours. The robot images have no sound set: that stays the user's to install (see "Package store").
- The download fetches Aldebaran's own public files to the user's machine, as the user would by hand; nothing is redistributed.

#### `nao-sim-fetch-suite`

`nao-sim-fetch-suite [2.1] [2.8] [--vendor DIR]` (`src/nao_sim/suite.py`; default: both versions into `docker/vendor/`) makes `<vendor>/<version>/` hold the pinned suite and `animations.pkg`.

- A file already there with the pinned hash is kept, so re-running is cheap (it hashes the files, nothing is downloaded).
- A file there with another hash (a Git LFS pointer, a partial copy) is an error and is left untouched; the user deletes it to fetch again.
- Every download goes to `<file>.part`, is hashed while it streams and takes its final name only if the hash matches; otherwise it is deleted and the command fails (exit 1).
- `animations.pkg`, when missing, is extracted from the version's robot image:
  1. The image (`.opn`) is used from `<vendor>/<version>/` if the user put it there with the pinned hash, otherwise downloaded there and deleted after the extraction (a user's own copy is kept).
  2. Layout of a `.opn`: a 4096-byte `ALDIMAGE` header, an installer shell script whose variables give `MAGIC_SIZE`, `SIZE_BASE`, `INSTALLER_SIZE` and `IMAGE_CMP_SIZE`, then the compressed ext3 root filesystem at byte `MAGIC_SIZE + INSTALLER_SIZE × SIZE_BASE`, `IMAGE_CMP_SIZE × SIZE_BASE` bytes long (bzip2 on 2.1, gzip on 2.8, told apart by their magic bytes). The host decompresses it in Python.
  3. No host tool reads ext3 on macOS, and nao-sim needs Docker anyway: the decompressed filesystem is streamed into `docker run -i --rm alpine:3.20`, which installs `e2fsprogs-extra`, stores it in the container and writes the package to stdout with `debugfs -R "cat <path>"`. The container is removed with its copy; nothing is mounted, no root is needed on the host.
  4. The package goes through the same `.part`, hash check and rename.
- Output is progress lines on stderr.

### Robot packages in the image

- The Dockerfile copies `vendor/<version>/animations.pkg` to `/opt/naoqi/share/naoqi/apps/animations.pkg`. At boot, NAOqi's `PackageManager` installs every `.pkg` in that directory as a *system* package, as a robot does with its factory packages (the 2.8 suite installs its own `core`, `dialog`, `expressivity`, `life` and `semantic` this way). Measured on both versions: `Successfully installed system package` in the log, `PackageManager.hasPackage("animations")` and `ALBehaviorManager.isBehaviorInstalled("animations/Stand/Gestures/Hey_1")` are true once the entrypoint is ready.
- Copying the unzipped package into the package store does not work: `PackageManager` only knows the packages in its registry (`~/.local/share/PackageManager/pm.db`, SQLite, table `packages(uuid, path, installer)`).
- Once built, the image needs neither the suite nor the package. A rebuild (after changing the modules or the entrypoint) still needs both in `docker/vendor/<version>/`: Docker checks every file a `COPY` uses, even for a cached step.

### Package store

`PackageManager` keeps installed packages under `/home/nao/.local/share/PackageManager` (the unzipped `apps/<uuid>/` plus `pm.db`). Packages the user installs (`PackageManager.install` over qi, or Choregraphe), such as the sound set, go there as on a robot.

- Each NAOqi compose service mounts a named volume there (`packages-2.1`, `packages-2.8`), so user-installed packages survive `docker compose down` and `up`, not only a stop and start. One volume per version: packages are version-specific.
- The image creates that directory owned by `nao`, so Docker initialises a new volume with that owner (an empty volume would otherwise be owned by root and `PackageManager` could not write).
- A package built with Python's `zipfile` must give each entry regular-file mode bits (`external_attr = (stat.S_IFREG | 0o644) << 16`, as `zip` on Linux writes): 2.8's `PackageManager` cannot read back an entry without them (`Invalid manifest`), which `ZipFile.writestr(name, data)` produces. 2.1 accepts both.
- `docker compose down -v` deletes the volumes: back to the image's factory packages, reinstalled at the next boot.
- The system packages (`animations`, and the 2.8 suite's own) are reinstalled from the image when missing from the store, so a volume created before an image change still gets them.

### Images

One image per version, `linux/amd64`, suite extracted to `/opt/naoqi`, override modules copied to `/opt/naoqi/modules/`, entrypoint at `/opt/naoqi/bin/nao-sim-entrypoint.sh`, healthcheck at `/opt/naoqi/bin/nao-sim-healthcheck.sh` ([status-service.md](status-service.md)).

- The build context is `docker/`. Each Dockerfile has its own ignore file (`Dockerfile.naoqi-<version>.dockerignore`, read by BuildKit next to the Dockerfile) that leaves out the other version's vendor files, robot images (`*.opn`) and partial downloads (`*.part`), so a build uploads only its own suite and package.

| | 2.1 (`Dockerfile.naoqi-2.1`) | 2.8 (`Dockerfile.naoqi-2.8`) |
| --- | --- | --- |
| Base | Ubuntu 14.04 | Ubuntu 16.04 |
| Extra packages | `libglib2.0-0` | `libglib2.0-0 libsqlite3-0 libdbus-1-3 libpulse0` (without sqlite, `packagemanager` aborts) |
| Robot model | NAO by default | The suite defaults to Pepper (`JULIETTEY20B2C.xml`); `etc/naoqi/ALRobotModel.xml` is switched to `NAOH25V60.xml` ("Nao", 26 joints) |
| Boot to ready | about 5 s | about 15 s |

- `naoqi-bin` refuses to run as root: the image runs as user `nao` (uid 1000), which owns `/opt/naoqi`.
- Environment: `PATH`, `LD_LIBRARY_PATH=/opt/naoqi/lib`, `PYTHONPATH=/opt/naoqi/lib:/opt/naoqi/modules`, `NAO_SIM_NAOQI_VERSION` (the suite's full version) and `NAO_SIM_VERSION` (build argument, default `dev`; see [status-service.md](status-service.md)), plus the per-version entrypoint defaults below.

### Network layout

Port 9559 is the only port, published on the host as `127.0.0.1:9559`.

- **2.1**: `naoqi-bin -b 0.0.0.0 -p 9559`. The broker is the public endpoint; every in-process service is served on it.
- **2.8**: `naoqi-bin` is only a launcher (ServiceDirectory, `ALServiceManager`, `PackageManager`). The services run in child processes (`naoqi-service`, one `qilaunch` per package service), each on its own random port, some on loopback only. The `core` package's `qi-secure-gateway` binds `0.0.0.0:9559` and relays every service, as on a real NAO 6. So `naoqi-bin` listens on `tcp://127.0.0.1:9558` (`--qi-listen-url`), leaving 9559 to the gateway; every service then advertises `tcp://<container>:9559` and `tcp://127.0.0.1:9559`.

### Compose

`docker/compose.yaml` has three services:

- `tts`: the speech engine ([tts-engine.md](tts-engine.md)), native architecture.
- `naoqi` (2.1, default).
- `naoqi28` (2.8, profile `2.8`).

Both NAOqi services publish `127.0.0.1:9559`, so only one runs at a time, and each mounts its package store volume (`packages-2.1`, `packages-2.8`; see "Package store"). They reach the engine at `http://tts:8080` (`NAO_SIM_TTS_URL`) and the host through `host.docker.internal` (`host-gateway` on Linux).

### Entrypoint

`entrypoint.sh` is the same script for both versions, driven by environment variables (the Dockerfiles set the per-version defaults):

| Variable | Meaning | 2.1 default | 2.8 default |
| --- | --- | --- | --- |
| `NAO_SIM_LISTEN_URL` | If set, `naoqi-bin --qi-listen-url <url>`; else `-b 0.0.0.0 -p $NAO_SIM_INTERNAL_PORT` | unset | `tcp://127.0.0.1:9558` |
| `NAO_SIM_INTERNAL_PORT` | Port the entrypoint and modules use to reach NAOqi from inside | 9559 | 9558 |
| `NAO_SIM_READY_SERVICE` | Last service to wait for (besides `ALLauncher`) before acting | `ALAutonomousLife` | `ALPanoramaCompass` |
| `NAO_SIM_DEFER_MODULES` | Autoload entries commented out of a copy of `autoload.ini`, launched with `ALLauncher.launchLocal` at the end | `animatedspeech dialog` | empty |
| `NAO_SIM_RESTART_SERVICES` | `ALServiceManager` services stopped before the replacement and started after | empty | `expressivity.autonomousabilitiesmodules` |
| `NAO_SIM_EXIT_MODULES` | Built-ins whose `exit()` is called | `ALTextToSpeech` | `ALTextToSpeech` |
| `NAO_SIM_MODULES` | Python modules loaded with `ALLauncher.launchPythonModule`, in order | `nao_sim_status_almodule nao_sim_tts_almodule` | `nao_sim_status_qiservice nao_sim_tts_qiservice` |
| `NAO_SIM_READY_TRIES` | Polls (one per second) before giving up on NAOqi | 120 | 120 |
| `NAO_SIM_SETTLE_POLLS` | Consecutive polls the service list must stay unchanged before NAOqi counts as ready | 3 | 3 |

(`NAO_SIM_POLL_INTERVAL`, the seconds between polls, and `NAOQI_HOME` exist so the host-side tests can run the script against fake `naoqi-bin` and `qicli`; the images never change them.)

Sequence:

1. Start `naoqi-bin`.
2. Poll the service list (`qicli info`) until `ALLauncher`, `ALPythonBridge`, every exit module and the ready service are registered **and** the list has not changed for `NAO_SIM_SETTLE_POLLS` polls. If `naoqi-bin` exits, or `NAO_SIM_READY_TRIES` polls fail, exit 1. The settling matters on 2.8: on a slow boot (cold cache, right after an image rebuild) the ready service appears while `naoqi-service` is still loading modules, and exiting a built-in or loading a module into that half-started process killed it (measured: `ALServiceManager` restarted it and `launchPythonModule` was cancelled after 50 s).
3. Stop the restart services.
4. `exit()` the exit modules.
5. Add `/opt/naoqi/modules` to the embedded interpreter's `sys.path` (`ALPythonBridge.eval`).
6. Load the modules.
7. Start the restart services.
8. Launch the deferred modules.
9. Check that every exit module's name answers again (up to 10 s each; `launchPythonModule` does not report an import failure). If one does not, exit 1.
10. Call `NaoSim.setReady` (exit 1 if it fails: the status module is missing), print `[entrypoint] nao-sim ready` and wait on `naoqi-bin`. `SIGTERM`/`SIGINT` are forwarded to it.

Every exit 1 terminates `naoqi-bin` first, so a failed boot shows as an exited container, never as a running one without its overrides. The healthcheck ([status-service.md](status-service.md)) reports `healthy` only after step 10.

### Desktop NAOqi facts the rest of nao-sim relies on

- No `ALSystem` service and no version key in ALMemory; `RobotConfig/Body/Type` is absent (2.1 and 2.8). The version (and the fact that the target is nao-sim) must come from a nao-sim service.
- No `ALAudioDevice` on either version; `ALAudioPlayer` is a stub that spawns `/opt/naoqi/bin/sndfile-play`, which fails in Docker.
- 2.1 has `Device/SubDeviceList/*` keys in ALMemory; the 2.8 virtual robot has none.

### Platforms

| Platform | How it runs | Note |
| --- | --- | --- |
| Linux x86\_64 | Docker Engine | No emulation |
| macOS Intel | Docker Desktop | |
| macOS Apple Silicon | Docker Desktop or OrbStack, amd64 emulation (Rosetta) | Measured on OrbStack: boot times above, no visible lag. The `tts` container is native |
| Windows | Docker Desktop (WSL 2) | |

## Open questions

1. **Docker Desktop.** Everything was measured on OrbStack; Docker Desktop on macOS, Linux and Windows is still to confirm.
2. **Starting the stack.** `nao-sim up` and `down` (build if needed, pick the version, start the host services) are not built; today it is `docker compose` by hand (see [README.md](../README.md)). It should wait on the container's health rather than on the log line.
