---
code:
  - docker/entrypoint-2.1.sh
  - docker/entrypoint-2.8.sh
  - docker/entrypoint-lib.sh
  - docker/modules/nao_sim_tts_almodule.py
  - docker/modules/nao_sim_tts_qiservice.py
tests:
  - tests-e2e/test_speech_live.py
  - tests/test_entrypoint.py
---

# Service replacement

**Status:** Implemented

## Purpose

nao-sim makes the container look like a real NAO by replacing or adding NAOqi services *inside* NAOqi, so any qi client on the host reaches them on 9559 exactly like built-ins and in-process modules (`ALAnimatedSpeech`, `ALDialog`...) call them instead of the originals. This spec is the reusable mechanism: how an override module is loaded, which object model it uses on each version, how a built-in is taken out first, and how an override reaches services that live on the host. The `ALTextToSpeech` replacement ([speech.md](speech.md)) is its first user; the planned `ALAudioDevice`, `ALPeoplePerception`, `ALFaceDetection` and `ALMovementDetection` replacements reuse it.

## Decided

### Loading a module

- Override modules are Python 2.7 files in `docker/modules/`, copied to `/opt/naoqi/modules/` and importable by name.
- The desktop `naoqi-bin` ignores the `[python]` section of `autoload.ini` (main file, user file, with or without `--writable-path`: measured). The entrypoint instead calls `ALLauncher.launchPythonModule(<module>)`, which runs `from <module> import *` in `ALPythonBridge`'s embedded interpreter. On 2.1 that is the `naoqi-bin` process itself (same pid, verified); on 2.8 it is `naoqi-service`.
- A module registers its service at import time, at module level.
- `launchPythonModule` does not report an import failure, so the entrypoint checks afterwards that every replaced name (`REPLACED` in each version's script) answers again, and exits non-zero otherwise rather than printing "ready" with the built-in gone ([container.md](container.md), "Entrypoint"). A module that adds a new name (`NaoSim`, the planned `ALAudioDevice`) is not covered by that check; the `NaoSim` module is, indirectly, since the entrypoint's last step calls it.
- Exact autoload ordering would need a small C++ loader module compiled against the suite's SDK, listed right after `pythonbridge`; kept as an option, not needed so far.

### Object model per version

| | 2.1 | 2.8 |
| --- | --- | --- |
| Registration | `naoqi.ALModule(name)` subclass, instantiated at module level | `qi.Session` connected to `tcp://127.0.0.1:$NAO_SIM_INTERNAL_PORT`, `registerService(name, obj)` |
| Why | Registers to the main broker: served on 9559 with the built-ins' endpoints and listed in the broker's local module table, which in-process callers use. A module's own `qi.Session` would serve on a separate port advertised with the container IP, unreachable from the host on Docker Desktop | The gateway relays every service, so a plain qi service is reachable. Required when callers need signals: a legacy `ALModule` cannot declare `qi.Signal`s |
| Concurrency | Measured OK: `stopAll` gets through while `say` blocks | Decorate the class with `@qi.multiThreaded()`; qi objects are single-threaded by default, so a blocking method would queue every other call |

`ALModule` rules (2.1):

- It auto-binds every method that has a docstring, with the arity from `inspect.getargspec`; defaults count toward that arity. An overload with fewer arguments needs an explicit `self.BIND_PYTHON(name, "<method>", <arity>)`, for example `say(text)` next to `say(text, language)`.
- Method names that collide with the `ALModule` generics (`ping`, `version`, `exit`, `stop`, `wait`, ...) must be avoided.

### Replacing a built-in

A replacement registers under the built-in's name, after the built-in has left both the ServiceDirectory and the broker. In-process modules resolve names through the broker's local module table, not the ServiceDirectory: with only a ServiceDirectory re-registration, `ALAnimatedSpeech` kept calling the old object. Every module that holds a proxy to the built-in must also be (re)started after the replacement is in place.

| Step | 2.1 | 2.8 |
| --- | --- | --- |
| 1. Keep dependents off the old object | Remove them from the autoload copy (`DEPENDENTS` in `entrypoint-2.1.sh`: `animatedspeech dialog`) | `ALServiceManager.stopService(<package service>)` (`DEPENDENTS` in `entrypoint-2.8.sh`: `expressivity.autonomousabilitiesmodules`) |
| 2. Remove the built-in | `<Built-in>.exit()` (`REPLACED`); it leaves the broker and the ServiceDirectory cleanly | Same |
| 3. Load the replacement | `launchPythonModule` (`MODULES`) | Same |
| 4. Bring dependents back | `ALLauncher.launchLocal(<library>)` | `ALServiceManager.startService(<package service>)` |

- Alternative for a built-in nobody needs: drop its C++ library from the autoload copy (`[core]`/`[extra]` entries are `lib<name>.so`). Note that `audioout` provides both `ALTextToSpeech` and `ALAudioPlayer`, so dropping it means replacing both.
- A name that no built-in holds (`ALAudioDevice` on both versions) is registered directly, with no step 1, 2 or 4.
- A replacement must carry whatever its callers connect to at start, not only the documented methods. On 2.8, `ALAnimatedSpeech` connects to `ALTextToSpeech`'s hidden signal `_started` and the process dies without it. The recording proxy and caller survey in [speech.md](speech.md) are the method for finding these.

### Calling services registered on the host

Some overrides must call a service that a host client registered: for example, `ALAudioDevice` calls a subscriber's `processRemote`.

- Go through the broker with `naoqi.ALProxy(<name>)`. NAOqi calls the host back over the socket the host already opened (libqi 2.1 `ClientServerSocket` capability), the mechanism NAOqi uses for any service a connected client registers.
- Never go through a module's own `qi.Session`. That opens a new connection to the host's advertised endpoints, and fails for two reasons: the host auto-listens on loopback only ("No endpoint available"), and the libqi 3 fork's server binds objects only after a service-0 capability message that 2.1 clients never send.
- Measured on 2.1 (C++ `ALMemory.subscribeToEvent` callback and an in-process `ALProxy`: pass; own `qi.Session` and `qicli` from the container: fail). 2.8 is not re-measured.

## Open questions

1. **Host callbacks on 2.8** are not measured. They are expected to work through the gateway with the same socket mechanism; to confirm when `ALAudioDevice` is built.
2. **Restarting a replacement** (re-running the procedure without restarting the container, e.g. while developing a module) is not supported.
