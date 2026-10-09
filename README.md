# nao-sim (prototype)

A NAO in a box: NAOqi 2.1.4.13 (`naoqi-bin` from the Choregraphe suite) running in a local
Docker image with our Python 2.7 override modules loaded into its process. Unofficial, MIT;
the image is built locally from the user's suite and is never published.

Status: validation spike done on NAOqi 2.1.4.13 and 2.8.7.4, see [spike/RESULTS.md](spike/RESULTS.md).

## Layout

- `docker/Dockerfile.naoqi-2.1`: Ubuntu 14.04 amd64 + 2.1.4.13 suite tarball at `/opt/naoqi`, non-root user, entrypoint.
- `docker/Dockerfile.naoqi-2.8`: Ubuntu 16.04 amd64 + 2.8.7.4 suite, NAO V6 model, `naoqi-bin` behind the suite's gateway on 9559 (compose profile `2.8`).
- `docker/entrypoint.sh`: starts `naoqi-bin`, waits for readiness, stops `$NAO_SIM_RESTART_SERVICES` (2.8), exits `$NAO_SIM_EXIT_MODULES`, loads `$NAO_SIM_MODULES` with `ALLauncher.launchPythonModule`, restarts services (2.8) or launches `$NAO_SIM_DEFER_MODULES` (2.1), checks the replaced services answer and marks `NaoSim` ready. Any failure exits non-zero.
- `docker/healthcheck.sh`: the Docker healthcheck, `NaoSim.isReady` on 9559.
- `docker/modules/`: Python 2.7 modules loaded inside NAOqi: `nao_sim_status_*` (the `NaoSim` service: versions, device sources, readiness, as a service and `NaoSim/*` ALMemory keys), `nao_sim_tts_core` (tag parsing, engine call, events), `nao_sim_tts_almodule` (2.1, `ALModule`), `nao_sim_tts_qiservice` (2.8, qi service).
- `docker/tts/`: the speech engine container (Piper + eSpeak NG, `POST /say`, streams PCM to the host sound card).
- `src/nao_sim/soundcard.py`: the host sound card (`nao-sim-soundcard`), a dumb PCM player with `--record` and `--silent` for tests.
- `src/nao_sim/suite.py`: `nao-sim-fetch-suite`, fills `docker/vendor/<version>/` with the pinned Choregraphe suite and the `animations` package extracted from the public robot image (needs Docker), all from Aldebaran's GitHub repositories and hash-checked; keeps what is already there.
- `docker/vendor/`: gitignored; `2.1/` and `2.8/` each hold the suite tarball and `animations.pkg`.
- `docker/compose.yaml`: also a package store volume per version, so packages installed over qi or Choregraphe (the sound set) survive `docker compose down`; `down -v` resets them.
- `tests/`, `tests-e2e/`: the fast tier and the live tier, which starts the containers itself.

## Run

Python 3.12 or 3.13 on macOS (arm64) or Linux (x86_64): the libqi wheels (`qi`, from
[funwithagents/libqi-python](https://github.com/funwithagents/libqi-python)) exist for those only.

```bash
uv sync --dev
uv run nao-sim-fetch-suite          # suites + animations package into docker/vendor/<version>/ (or: 2.1 / 2.8)
uv run nao-sim-soundcard &                                                    # host sound card on :9562
docker compose -f docker/compose.yaml up -d --build                           # tts + NAOqi 2.1
docker compose -f docker/compose.yaml --profile 2.8 up -d --build tts naoqi28  # tts + NAOqi 2.8 (same host port)
docker compose -f docker/compose.yaml ps  # wait for the NAOqi container to be "healthy"
```

Then connect any qi client to `tcp://127.0.0.1:9559`, as to a NAO. The `NaoSim` service tells a client it is on nao-sim (`getVersion`, `getNaoqiVersion`, `isReady`; `NaoSim/*` keys in ALMemory). `NAO_SIM_VERSION=<version>` before `compose up --build` sets the version it reports (default `dev`).

## Test

```bash
uv run pytest             # fast tier: no Docker, no suite
uv run pytest tests-e2e   # live tier: builds, starts and stops the 2.1 and 2.8 stacks itself
```

Stop any stack or sound card started by hand before the live tier: it needs ports 9559 and 9562.
