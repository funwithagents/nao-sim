---
code:
  - docker/modules/nao_sim_status_core.py
  - docker/modules/nao_sim_status_almodule.py
  - docker/modules/nao_sim_status_qiservice.py
  - docker/healthcheck.sh
  - docker/entrypoint.sh
  - docker/Dockerfile.naoqi-2.1
  - docker/Dockerfile.naoqi-2.8
  - docker/compose.yaml
tests:
  - tests/test_status_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_status_live.py
---

# NaoSim status service and healthcheck

**Status:** Implemented

## Purpose

The desktop `naoqi-bin` has no `ALSystem` and no version key in ALMemory ([container.md](container.md), "Desktop NAOqi facts"), so a client has no standard way to learn what it is talking to. The `NaoSim` service is nao-sim's identity: its existence says the target is nao-sim, it reports the nao-sim and NAOqi versions, publishes which host devices are attached, and says whether boot is complete. The Docker healthcheck is built on it, and so will `nao-sim up` and `nao-sim status` be.

It is also a contract with the other packages of the toolkit: nao-viewer's pose source identifies a target as `nao-sim` when the `NaoSim` service exists and reads its version from the ALMemory key `NaoSim/Version`; nao-bridge plans `nao.info.target` the same way. The service name and these keys do not change without a coordinated release.

## Decided

### The service

The service is called `NaoSim`. It exists only on nao-sim: no real robot or plain desktop NAOqi has it. Its name is free on both versions, so it is registered directly (no built-in to remove), as the first entry of `NAO_SIM_MODULES` ([service-replacement.md](service-replacement.md)).

| Method | Returns | Meaning |
| --- | --- | --- |
| `getVersion()` | string | The nao-sim version the image was built with (`NAO_SIM_VERSION`, see "Versions") |
| `getNaoqiVersion()` | string | The suite's full NAOqi version: `2.1.4.13` or `2.8.7.4` |
| `isReady()` | bool | `true` once the entrypoint has finished its sequence (see "Readiness") |
| `setReady()` | — | Marks boot complete. Called by the entrypoint as the last step; publishes `NaoSim/Ready` |

- Method names stay clear of the `ALModule` generics (`version`, `ping`, `exit`, `stop`...), since on 2.1 the service is an `ALModule`.
- Object model per version as in [service-replacement.md](service-replacement.md): `nao_sim_status_almodule` (2.1, `naoqi.ALModule` on the broker) and `nao_sim_status_qiservice` (2.8, `qi.Session` service relayed by the gateway). Both are thin shells over `nao_sim_status_core`, Python 2.7 code kept importable under Python 3 so the fast tier tests it on the host.
- `naoqi-bin --version` prints only the two-component version (`2.1`, `2.8`), so the full version comes from the Dockerfile (`NAO_SIM_NAOQI_VERSION`).

### ALMemory keys

The module writes these at load. All values are plain strings except `NaoSim/Ready`.

| Key | Value at boot | Who changes it later |
| --- | --- | --- |
| `NaoSim/Version` | nao-sim version | Nobody |
| `NaoSim/NaoqiVersion` | `2.1.4.13` or `2.8.7.4` | Nobody |
| `NaoSim/Ready` | `0`; `1` after `setReady()`. Raised as an event, so a client can wait on it | The entrypoint, through `setReady()` |
| `NaoSim/Camera/Source` | `none` | The host camera feeder (`webcam`, `render`), when the video spec is built |
| `NaoSim/Audio/Source` | `none` | The host microphone device (`mic`, `wav`), when the `ALAudioDevice` spec is built |
| `NaoSim/Perception/Source` | `none` | The host detection feed, when the perception spec is built |

- `none` means no host device is attached to that service, so it serves nothing (no frames, no audio, no detections). The device specs own the other values and may add keys under the same prefixes (for example the mono policy under `NaoSim/Audio/`); the host writes them as an ordinary qi client, as the overview's "Host services" prescribes.

### Readiness

"Ready" means the whole entrypoint sequence ([container.md](container.md), "Entrypoint") completed: NAOqi's service list settled with every needed service present, the built-ins were replaced, every module loaded, the dependents were restarted or launched, and **every replaced name answers again**. Only then does the entrypoint call `NaoSim.setReady` and print `[entrypoint] nao-sim ready`.

The entrypoint exits non-zero (after terminating `naoqi-bin`) instead of carrying on when:

- NAOqi does not answer after `NAO_SIM_READY_TRIES` polls (default 120, one per second);
- a name in `NAO_SIM_EXIT_MODULES` does not answer within 10 s of loading the modules (a replacement that failed at import, which `launchPythonModule` does not report);
- `NaoSim.setReady` fails (the status module itself did not load).

So a container that is `running` and printed the ready line has its overrides in place, and one whose boot failed shows as `exited`, not as a half-robot. This replaces the earlier behaviour where both failure modes were silent (the former open questions of [container.md](container.md) and [service-replacement.md](service-replacement.md)).

### Healthcheck

`docker/healthcheck.sh` calls `NaoSim.isReady` with `qicli` on the **public** port, `tcp://127.0.0.1:9559`, and succeeds when the answer is `true`. The two suites' `qicli` differ: 2.1 prints `NaoSim.isReady: true`, 2.8 prints `true` followed by its `[W] qitype.signal` warnings on stdout; the script reads the first line and drops any `name: ` prefix. On 2.8 that goes through the suite's gateway, so a health of `healthy` also means the relay works; on 2.1 it is the broker itself.

Both Dockerfiles declare it: `HEALTHCHECK --interval=5s --timeout=5s --start-period=120s --retries=3`. The container is `starting` during boot (about 5 s on 2.1, 15 s on 2.8, plus module loading), `healthy` within one interval of the ready line, and `unhealthy` if NAOqi stops answering. `docker compose ps` and `docker inspect -f '{{.State.Health.Status}}'` show it; `nao-sim up` will wait on it rather than on the log line.

### Versions

- `NAO_SIM_VERSION` is a build argument of both Dockerfiles, kept as an environment variable in the image (default `dev`). `docker/compose.yaml` passes `${NAO_SIM_VERSION:-dev}`; `nao-sim up` will pass the installed package version, and the live tests pass the checkout's. Baked at build rather than read at run time because it describes the override modules inside the image.
- `NAO_SIM_NAOQI_VERSION` is set by each Dockerfile next to the suite it extracts.

## Open questions

1. **Boot timing.** `NaoSim` does not publish how long boot took (`NaoSim/BootSeconds`); the capability probe would record it. Add when the probe exists.
2. **Device sources on disconnect.** Whether the host resets a source key to `none` when its device stops is for each device spec to decide.
3. **`setReady` is public.** Any client can call it. Acceptable on a simulator; a hidden `_setReady` would first need the `ALModule` autobind behaviour for underscore names measured on 2.1.
