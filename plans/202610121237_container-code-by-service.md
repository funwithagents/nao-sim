# `docker/`: one folder per container, and the code inside NAOqi one folder per service

**Status:** Done

Gives `docker/` one folder per container, each holding everything its image is built from: `docker/naoqi/` (the NAOqi image: Dockerfiles and their ignore files, entrypoints, healthcheck) and `docker/tts-engine/` (was `docker/tts/`), with `compose.yaml` at the top running both. Inside `docker/naoqi/`, the code that runs in NAOqi moves from `docker/modules/` (Python 2.7) and `docker/relay/` (C++) to `services/<service>/`, one folder per service, named like its spec, holding that service's Python core and shells and its C++ (a relay or a front). Files are named after the service's role with one `nao_sim_` prefix; the `ALTextToSpeech` replacement's files say "speech", leaving "tts" to the speech engine container (`docker/tts-engine/`, [tts-engine.md](../specs/container/tts-engine.md)). Nothing a client sees changes: the registered names (`ALTextToSpeech`, `_NaoSimTextToSpeech`, `ALAudioDevice`, `_NaoSimAudioRelay`, `NaoSim`) and the paths inside the image (`/opt/naoqi/modules/`, `/opt/naoqi/lib/nao-sim/`) stay. Left out: the host side, and compose's service names (`tts`, `naoqi21`, `naoqi28`), which are runtime names.

## Scope

| From | To |
| --- | --- |
| `docker/modules/nao_sim_tts_{core,almodule,qiservice}.py` | `docker/naoqi/services/speech/nao_sim_speech_{core,almodule,qiservice}.py` |
| `docker/relay/naosim_tts.cpp` | `docker/naoqi/services/speech/nao_sim_speech_front.cpp` |
| `docker/modules/nao_sim_audiodevice_{core,almodule,qiservice}.py` | `docker/naoqi/services/audio-device/nao_sim_audio_device_{core,almodule,qiservice}.py` |
| `docker/relay/naosim_audiorelay.cpp` | `docker/naoqi/services/audio-device/nao_sim_audio_device_relay.cpp` |
| `docker/modules/nao_sim_status_{core,almodule,qiservice}.py` | `docker/naoqi/services/status-service/` (same names) |
| `docker/Dockerfile.naoqi-*` (and `.dockerignore`), `entrypoint-*.sh`, `entrypoint-lib.sh`, `healthcheck.sh` | `docker/naoqi/` |
| `docker/tts/` | `docker/tts-engine/` |
| `tests/test_tts_core.py`, `tests/test_audiodevice_core.py` | `tests/test_speech_core.py`, `tests/test_audio_device_core.py` |

- The modules' imports of their cores, their log files (`/home/nao/speech_almodule.jsonl`, `speech_qiservice.jsonl`) and the `.so` names (`libnao_sim_speech_front.so`, `libnao_sim_audio_device_relay.so`).
- Both Dockerfiles: the `relay` stage becomes `native` and compiles every `services/*/*.cpp`; the final stage copies `services/*/*.py` flat into `/opt/naoqi/modules/`. `compose.yaml`: build contexts `./naoqi` and `./tts-engine`; the ignore files no longer need to exclude `image-data/` and `tts/`.
- Both entrypoints (`MODULES`, `RELAY`, `FRONTS`), `pyproject.toml` (ruff exclude, pyright paths), `tests/conftest.py` (import paths), `tests/test_entrypoint.py`, `tests/test_docker_images.py`, `tests/test_suite.py`, `tests-e2e/support.py` (log paths, `speech_log`), `tests-e2e/test_install_live.py`; CI's format check (`docker/tts-engine`).
- Specs' frontmatter and text: `container.md`, `service-replacement.md`, `speech.md`, `audio-device.md`, `status-service.md`, `project.md`, `testing.md`, `ci.md`; `AGENTS.md`'s project map; `README.md`. The audio player spec and plan (uncommitted) get the new layout too.

## Steps

1. `git mv` the files as above; fix the imports, log paths and `__all__`/instance names inside them.
2. Dockerfiles, entrypoints, `pyproject.toml`, test paths and names.
3. Specs, map and README; `tests/test_project_map.py` keeps them honest.
4. Lint, types, fast tier; rebuild both images; the live tier on 2.1 and 2.8.
5. This plan `Done` here and in [_index.md](_index.md).

## Verification

- `uv run ruff check .`, `uv run ruff format --check src tests tests-e2e docker/tts-engine` (as CI), `uv run pyright`, `uv run pytest`.
- `uv run pytest tests-e2e` on 2.1 and 2.8 (images rebuilt).
- Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
