---
code:
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
  - docker/naoqi/entrypoint-lib.sh
  - docker/naoqi/services/speech/nao_sim_speech_almodule.py
  - docker/naoqi/services/speech/nao_sim_speech_qiservice.py
  - docker/naoqi/Dockerfile.naoqi-2.1
  - docker/naoqi/Dockerfile.naoqi-2.8
  - docker/naoqi/services/audio-device/nao_sim_audio_device_relay.cpp
  - docker/naoqi/services/speech/nao_sim_speech_front.cpp
tests:
  - tests-e2e/test_speech_live.py
  - tests/test_entrypoint.py
---

# Service replacement

**Status:** Implemented

## Purpose

nao-sim makes the container look like a real NAO by replacing or adding NAOqi services *inside* NAOqi, so any qi client on the host reaches them on 9559 exactly like built-ins and in-process modules (`ALAnimatedSpeech`, `ALDialog`...) call them instead of the originals. This spec is the reusable mechanism: how an override module is loaded, which object model it uses on each version, how a built-in is taken out first, how an override reaches services that live on the host, and the two native pieces for what Python 2.7 cannot do: the relay to send a binary, and a C++ front for `post`/`wait`/`stop(id)`. The `ALTextToSpeech` replacement ([speech.md](../services/speech.md)) is its first user; the `ALAudioDevice` replacement ([audio-device.md](../services/audio-device.md)) and the planned `ALAudioPlayer` replacement reuse it.

## Decided

### Loading a module

- Override modules are Python 2.7 files, kept with their service in `docker/naoqi/services/<service>/` and copied flat to `/opt/naoqi/modules/`, importable by name (hence their unique `nao_sim_<service>_` names).
- The desktop `naoqi-bin` ignores the `[python]` section of `autoload.ini` (main file, user file, with or without `--writable-path`: measured). The entrypoint instead calls `ALLauncher.launchPythonModule(<module>)`, which runs `from <module> import *` in `ALPythonBridge`'s embedded interpreter. On 2.1 that is the `naoqi-bin` process itself (same pid, verified); on 2.8 it is `naoqi-service`.
- A module registers its service at import time, at module level.
- `launchPythonModule` does not report an import failure, so the entrypoint checks afterwards that every replaced name (`REPLACED` in each version's script) and every added name (`ADDED`: `ALAudioDevice`, `_NaoSimAudioRelay`) answers, and exits non-zero otherwise rather than printing "ready" with a service missing ([container.md](container.md), "Entrypoint"). The `NaoSim` module is checked too, since the entrypoint's last step calls it.
- Exact autoload ordering would need a small C++ loader module compiled against the suite's SDK, listed right after `pythonbridge`; kept as an option, not needed so far.

### Object model per version

| | 2.1 | 2.8 |
| --- | --- | --- |
| Registration | `naoqi.ALModule(name)` subclass, instantiated at module level | `qi.Session` connected to `tcp://127.0.0.1:$NAO_SIM_INTERNAL_PORT`, `registerService(name, obj)` |
| Why | Registers to the main broker: served on 9559 with the built-ins' endpoints and listed in the broker's local module table, which in-process callers use. A module's own `qi.Session` would serve on a separate port advertised with the container IP, unreachable from the host on Docker Desktop | The gateway relays every service, so a plain qi service is reachable. Required when callers need signals: a legacy `ALModule` cannot declare `qi.Signal`s |
| Concurrency | Measured OK: `stopAll` gets through while `say` blocks | Decorate the class with `@qi.multiThreaded()`; qi objects are single-threaded by default, so a blocking method would queue every other call |
| `ALProxy.post` | A task id; `wait`/`isRunning` served by the generics | Runs the call synchronously and returns `-1`; `wait`, `stop`, `isRunning` are "Can't find method" (measured on both versions for a qi service) |

`ALModule` rules (2.1):

- It auto-binds every method that has a docstring, with the arity from `inspect.getargspec`; defaults count toward that arity. An overload with fewer arguments needs an explicit `self.BIND_PYTHON(name, "<method>", <arity>)`, for example `say(text)` next to `say(text, language)`.
- Method names that collide with the `ALModule` generics (`ping`, `version`, `exit`, `stop`, `wait`, ...) must be avoided. A Python `stop` is never called, even bound explicitly with `BIND_PYTHON`: the generic wins (measured Oct 12, 2026).
- The generics `pCall` (what `ALProxy.post` calls), `isRunning(id)` and `wait(id, timeout)` work on a Python `ALModule`, on 2.1 and in 2.8's `naoqi-service`; the generic `stop(id)` does nothing to it ("Task ids, `wait` and `stop(id)`").

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
- A replacement must carry whatever its callers connect to at start, not only the documented methods. On 2.8, `ALAnimatedSpeech` connects to `ALTextToSpeech`'s hidden signal `_started` and the process dies without it. The recording proxy and caller survey in [speech.md](../services/speech.md) are the method for finding these.

### Calling services registered on the host

Some overrides must call a service that a host client registered: for example, `ALAudioDevice` calls a subscriber's `processRemote`.

- Go through the broker with `naoqi.ALProxy(<name>)`. NAOqi calls the host back over the socket the host already opened (libqi 2.1 `ClientServerSocket` capability), the mechanism NAOqi uses for any service a connected client registers.
- Never go through a module's own `qi.Session`. That opens a new connection to the host's advertised endpoints, and fails for two reasons: the host auto-listens on loopback only ("No endpoint available"), and the libqi 3 fork's server binds objects only after a service-0 capability message that 2.1 clients never send.
- On 2.8, a module's own `qi.Session` (on `NAO_SIM_INTERNAL_PORT`) reaches a host-registered service through the gateway, as `naoqi.ALProxy` does.
- Measured on 2.1 (C++ `ALMemory.subscribeToEvent` callback and an in-process `ALProxy`: pass; own `qi.Session` and `qicli` from the container: fail) and, on Oct 10, 2026, on both versions with a host `processRemote` (2.1 through the broker, 2.8 through a module's own session: pass; `spike/RESULTS.md`).

### Binary arguments: the native relay

Python 2.7 inside NAOqi cannot send a binary value to another service, on either version (measured Oct 10, 2026, `spike/RESULTS.md`): py2 `qi` sends `str` and `bytearray` as a qi string, `naoqi.ALProxy` turns a `bytearray` into `None`, and `buffer`/`memoryview` are refused. A libqi 3 client then receives a `str` (mangled when the bytes are not UTF-8) where a NAO's C++ module sends an `ALValue` binary, which it receives as a `bytearray`. Where the bytes matter (a subscriber's `processRemote`), an override goes through a native relay:

- **A small C++ NAOqi module**, an `ALModule` built from one source for both versions (`docker/naoqi/services/audio-device/nao_sim_audio_device_relay.cpp`), named with a leading underscore so it stays out of NAOqi's service listings as NAO's own internal modules do (`_NaoSimAudioRelay`). Its methods take the bytes as a string, which Python 2.7 sends intact, and make the call with an `ALValue` binary through an `ALProxy`, exactly as the C++ module of a NAO does. It holds no logic: the Python 2.7 module decides what is sent, to whom and when.
- **Loaded** by the entrypoint with `ALLauncher.launchLocal(<path of the .so>)` before the Python modules, into the process that hosts them (`naoqi-bin` on 2.1, `naoqi-service` on 2.8); a launch that registers nothing fails the boot.
- **Built in the image**, in a builder stage of each version's Dockerfile, never on the host and never committed ([container.md](container.md), "The native build"). One recipe for both versions: the headers of the version's own C++ SDK (the same release as its suite), linked against the suite's own libraries, with the suite's compiler and C++ ABI.
- Each call costs under 1.5 ms (measured with 64 KB buffers).

### Task ids, `wait` and `stop(id)`: a C++ front

Choregraphe's boxes start a call with `id = proxy.post.<method>(...)`, wait with `proxy.wait(id, 0)`, and stop it with `ALProxy(name, True).stop(id)` from a second proxy (the Play Sound and Say boxes). `wait` and `stop` are `ALModule` generics; a C++ module honours `stop(id)` by checking `isStopRequired(getMethodID())` while it runs. Python cannot (measured Oct 12, 2026, `spike/RESULTS.md`):

| | Python `ALModule` | Python qi service | C++ `ALModule` |
| --- | --- | --- | --- |
| `post` | Task id | Synchronous, `-1` | Task id |
| `wait(id, 0)` | Blocks until the call ends | "Can't find method" | Blocks until the call ends, or until stopped |
| `stop(id)` | Accepted, no effect | "Can't find method" | `isStopRequired(id)` turns true in that call only |
| `getMethodID()` in the call | `-1` (not given to Python; through `ctypes`, `-1`) | — | The id `post` returned; `-1` for a blocking call |

Same on 2.1 and 2.8. So a replacement whose callers stop by task id has a **C++ front**:

- **The service is a C++ `ALModule`** registered under the built-in's name, built and loaded as the relay is (one source for both versions, compiled in the native build stage, `ALLauncher.launchLocal` at boot, step 3 of "Replacing a built-in").
- **It holds no logic.** The logic lives in a Python 2.7 core module, a hidden service named with a leading underscore (`_NaoSim<Name>`, `ALModule` on 2.1, qi service on 2.8 as above), so the fast tier tests it on the host as the other cores.
- **A long call** (one that plays, speaks or waits) takes its id with `getMethodID()` (or asks the core for one when it is `-1`, a blocking call), starts the work in the core with that id, and polls every 20 ms: `isStopRequired(id)` makes it call the core's stop for that id; the core reporting the work done makes it return. A core-side stop (`stopAll`) ends the polls.
- **Every other method** forwards to the core and returns its answer.
- **The front reaches its core through `ALProxy` on 2.1 and a `qi::AnyObject` on 2.8**, each version's own API (`getParentBroker()->session()->service(core)` on 2.8), with typed calls. They are safe because each image compiles against its suite's own SDK ([container.md](container.md), "Build files: the C++ SDK"): built against mismatched libqi headers, typed calls sent "Invalid" values and crashed `naoqi-service`.
- **The qi box pattern works on it too.** 2.8's boxes call `pCall(method, ...)`, `wait(id)` and `stop(id)` as qi methods on a service object, rather than `ALProxy.post`; a C++ `ALModule` serves them (measured on 2.8). A Python qi service could define those methods itself, but `ALProxy.post` (2.1-style scripts, 2.8's deprecated boxes, `ALAnimatedSpeech`'s C++ proxy) would still run synchronously against it, so the front stays the one mechanism on both versions.
- **On 2.8** the C++ front is an `ALModule` in `naoqi-service` like the relay; the gateway relays it like any service.
- **Stopped by a cancel.** A qi caller may stop a call by cancelling its future instead of `stop(id)`: `ALAnimatedSpeech` 2.8 does so with `ALTextToSpeech._sayWithLocale` (`qicli trace` shows no other call on the service when it is stopped). A long call such a caller makes answers with a `qi::Future` from a `qi::Promise` whose cancel callback stops the work in the core, completed by a thread that follows it (cancelled or done).
- **Signals** a front's callers need are the front's: advertised in its constructor with `getBuilder().advertiseSignal(name, &member)` (an `ALModuleCore` is a `qi::DynamicObject`), fired as member signals when the core asks through a hidden method; a string signal reaches clients in other processes (measured on 2.8). While the build used mismatched headers, firing through `asObject().post(...)` and connecting from NAOqi's embedded Python crashed `naoqi-service` and a `qi::uint64_t` signal delivered nothing; not measured again since. A front fires only the signals its callers need, as members.
- **Users:** the `ALTextToSpeech` replacement ([speech.md](../services/speech.md), "Architecture"), then the `ALAudioPlayer` replacement ([audio-player.md](../services/audio-player.md)).

## Open questions

1. **Restarting a replacement** (re-running the procedure without restarting the container, e.g. while developing a module) is not supported.
