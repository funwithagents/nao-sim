# nao-sim (prototype)

A NAO in a box: NAOqi 2.1.4.13 (`naoqi-bin` from the Choregraphe suite) running in a local
Docker image with our Python 2.7 override modules loaded into its process. Unofficial, MIT;
the image is built locally from the user's suite and is never published.

Status: validation spike done on NAOqi 2.1.4.13 and 2.8.7.4, see [spike/RESULTS.md](spike/RESULTS.md).

## Layout

- `docker/Dockerfile.naoqi-2.1`: Ubuntu 14.04 amd64 + 2.1.4.13 suite tarball at `/opt/naoqi`, non-root user, entrypoint.
- `docker/Dockerfile.naoqi-2.8`: Ubuntu 16.04 amd64 + 2.8.7.4 suite, NAO V6 model, `naoqi-bin` behind the suite's gateway on 9559 (compose profile `2.8`).
- `docker/entrypoint.sh`: starts `naoqi-bin`, waits for readiness, stops `$NAO_SIM_RESTART_SERVICES` (2.8), exits `$NAO_SIM_EXIT_MODULES`, loads `$NAO_SIM_MODULES` with `ALLauncher.launchPythonModule`, then restarts services (2.8) or launches `$NAO_SIM_DEFER_MODULES` (2.1).
- `docker/modules/`: Python 2.7 modules loaded inside NAOqi: `nao_sim_tts_core` (tag parsing, engine call, events), `nao_sim_tts_almodule` (2.1, `ALModule`), `nao_sim_tts_qiservice` (2.8, qi service).
- `docker/tts/`: the speech engine container (Piper + eSpeak NG, `POST /say`, streams PCM to the host sound card).
- `src/nao_sim/soundcard.py`: the host sound card (`nao-sim-soundcard`), a dumb PCM player with `--record` and `--silent` for tests.
- `docker/vendor/`: gitignored; put `choregraphe-suite-2.1.4.13-linux64.tar.gz` and/or `choregraphe-suite-2.8.7.4-linux64.tar.gz` here (hashes in `docker/suite-*.sha256`).
- `spike/`: host-side Python 3 probe scripts (need the libqi Python 3 wheel from funwithagents/libqi-python).

## Run

```bash
uv venv && uv pip install -e . && nao-sim-soundcard &                       # host sound card on :9562
docker compose -f docker/compose.yaml up -d --build                           # tts + NAOqi 2.1
docker compose -f docker/compose.yaml --profile 2.8 up -d --build tts naoqi28  # tts + NAOqi 2.8 (same host port)
docker logs -f nao-sim-naoqi        # wait for "[entrypoint] nao-sim ready"
python spike/host_probe.py tcp://127.0.0.1:9559
python spike/drive_speech.py tcp://127.0.0.1:9559   # say, animated speech bookmarks, interruption
```
