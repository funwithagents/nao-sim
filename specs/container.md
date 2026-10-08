---
code:
  - docker/Dockerfile.naoqi-2.1
  - docker/Dockerfile.naoqi-2.8
  - docker/compose.yaml
  - docker/entrypoint.sh
  - docker/suite-2.1.sha256
  - docker/suite-2.8.sha256
tests:
---

# NAOqi container

**Status:** Stable

## Purpose

The container gives the desktop `naoqi-bin` from the user's Choregraphe suite the old Linux it expects, on every platform, and exposes it on one port as a real robot would: `127.0.0.1:9559`. It is the only way nao-sim runs NAOqi (there is no native mode). How built-in services are replaced inside it is in [service-replacement.md](service-replacement.md); this spec covers the image, the network layout, boot and the entrypoint's configuration interface.

## Decided

### Suites and licensing

- The user supplies the suite tarball in `docker/vendor/` (gitignored). The image is built locally, tagged locally (`nao-sim/naoqi:<version>`) and never pushed: it contains Aldebaran's software.
- Pinned sources and hashes:

| Version | Source | File | SHA-256 |
| --- | --- | --- | --- |
| 2.1.4.13 (NAO V4/V5) | [aldebaran/NAO-V5-ressources](https://github.com/aldebaran/NAO-V5-ressources/tree/main/Choregraphe/Linux/Binaries), Git LFS (download from `media.githubusercontent.com`; the raw URL returns a pointer) | `choregraphe-suite-2.1.4.13-linux64.tar.gz` (431 MB) | `bad0212956e2223f36736cff33bdc1e008311b8bf9efd81a52dcf05895c8abce` (`docker/suite-2.1.sha256`) |
| 2.8.7.4 (NAO V6) | [aldebaran/nao6-binaries](https://github.com/aldebaran/nao6-binaries), branch `master`, Git LFS | `choregraphe-suite-2.8.7.4-linux64.tar.gz` (1.33 GB) | `edf95da2ae8ec7573e3a590b6db47a472f9d2733280a4a597841fbf0c1e6c63c` (`docker/suite-2.8.sha256`) |

- Use the Binaries tarball, not the 2.1 `.run` setup: it is a static self-extractor that crashes under Rosetta (`bss_size overflow`).

### Images

One image per version, `linux/amd64`, suite extracted to `/opt/naoqi`, override modules copied to `/opt/naoqi/modules/`, entrypoint at `/opt/naoqi/bin/nao-sim-entrypoint.sh`.

| | 2.1 (`Dockerfile.naoqi-2.1`) | 2.8 (`Dockerfile.naoqi-2.8`) |
| --- | --- | --- |
| Base | Ubuntu 14.04 | Ubuntu 16.04 |
| Extra packages | `libglib2.0-0` | `libglib2.0-0 libsqlite3-0 libdbus-1-3 libpulse0` (without sqlite, `packagemanager` aborts) |
| Robot model | NAO by default | The suite defaults to Pepper (`JULIETTEY20B2C.xml`); `etc/naoqi/ALRobotModel.xml` is switched to `NAOH25V60.xml` ("Nao", 26 joints) |
| Boot to ready | about 5 s | about 15 s |

- `naoqi-bin` refuses to run as root: the image runs as user `nao` (uid 1000), which owns `/opt/naoqi`.
- Environment: `PATH`, `LD_LIBRARY_PATH=/opt/naoqi/lib`, `PYTHONPATH=/opt/naoqi/lib:/opt/naoqi/modules`, plus the per-version entrypoint defaults below.

### Network layout

Port 9559 is the only port, published on the host as `127.0.0.1:9559`.

- **2.1**: `naoqi-bin -b 0.0.0.0 -p 9559`. The broker is the public endpoint; every in-process service is served on it.
- **2.8**: `naoqi-bin` is only a launcher (ServiceDirectory, `ALServiceManager`, `PackageManager`). The services run in child processes (`naoqi-service`, one `qilaunch` per package service), each on its own random port, some on loopback only. The `core` package's `qi-secure-gateway` binds `0.0.0.0:9559` and relays every service, as on a real NAO 6. So `naoqi-bin` listens on `tcp://127.0.0.1:9558` (`--qi-listen-url`), leaving 9559 to the gateway; every service then advertises `tcp://<container>:9559` and `tcp://127.0.0.1:9559`.

### Compose

`docker/compose.yaml` has three services:

- `tts`: the speech engine ([tts-engine.md](tts-engine.md)), native architecture.
- `naoqi` (2.1, default).
- `naoqi28` (2.8, profile `2.8`).

Both NAOqi services publish `127.0.0.1:9559`, so only one runs at a time. They reach the engine at `http://tts:8080` (`NAO_SIM_TTS_URL`) and the host through `host.docker.internal` (`host-gateway` on Linux).

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
| `NAO_SIM_MODULES` | Python modules loaded with `ALLauncher.launchPythonModule` | `nao_sim_tts_almodule` | `nao_sim_tts_qiservice` |

Sequence:

1. Start `naoqi-bin`.
2. Poll with `qicli` (1 s period, up to 120 tries) until `ALLauncher` and the ready service answer.
3. Stop the restart services.
4. `exit()` the exit modules.
5. Add `/opt/naoqi/modules` to the embedded interpreter's `sys.path` (`ALPythonBridge.eval`).
6. Load the modules.
7. Start the restart services.
8. Launch the deferred modules.
9. Print `[entrypoint] nao-sim ready` and wait on `naoqi-bin`. `SIGTERM`/`SIGINT` are forwarded to it.

### Desktop NAOqi facts the rest of nao-sim relies on

- No `ALSystem` service and no version key in ALMemory; `RobotConfig/Body/Type` is absent (2.1 and 2.8). Version and target must come from a nao-sim service.
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

1. **Readiness timeout.** After 120 failed polls the entrypoint carries on as if NAOqi were ready instead of failing. It should exit non-zero, so the container shows as failed.
2. **Healthcheck.** There is no Docker healthcheck. It needs the planned `NaoSim` status service (no `ALSystem` on the desktop `naoqi-bin`); see [_overview.md](_overview.md), "nao-sim".
3. **Build context size.** The build context is `docker/`, so every build uploads both suite tarballs in `vendor/` (about 1.7 GB). A per-Dockerfile `.dockerignore` (`Dockerfile.naoqi-2.1.dockerignore`) that keeps only the version's own tarball fixes it.
4. **Docker Desktop.** Everything was measured on OrbStack; Docker Desktop on macOS, Linux and Windows is still to confirm.
5. **Starting the stack.** `nao-sim up` and `down` (build if needed, pick the version, start the host services) are not built; today it is `docker compose` by hand (see [README.md](../README.md)).
