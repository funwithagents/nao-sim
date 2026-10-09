# nao-sim (prototype)

A NAO in a box: NAOqi 2.1.4.13 (`naoqi-bin` from the Choregraphe suite) running in a local
Docker image with our Python 2.7 override modules loaded into its process. Unofficial, MIT;
the image is built locally from the user's suite and is never published.

Status: validation spike done on NAOqi 2.1.4.13 and 2.8.7.4, see [spike/RESULTS.md](spike/RESULTS.md).

## Layout

- `docker/Dockerfile.naoqi-2.1`: Ubuntu 14.04 amd64 + 2.1.4.13 suite tarball at `/opt/naoqi`, non-root user, entrypoint.
- `docker/Dockerfile.naoqi-2.8`: Ubuntu 16.04 amd64 + 2.8.7.4 suite, NAO V6 model, `naoqi-bin` behind the suite's gateway on 9559 (compose profile `2.8`; 2.1 is profile `2.1`).
- `docker/entrypoint-2.1.sh`, `docker/entrypoint-2.8.sh`: each version's boot procedure, top to bottom: start `naoqi-bin`, wait for a settled service list, keep the modules depending on `ALTextToSpeech` off it (2.1: left out of autoload; 2.8: their package service stopped), exit the built-in, load our modules with `ALLauncher.launchPythonModule`, bring the dependents back, check the replacements answer and mark `NaoSim` ready. Any failure exits non-zero. `docker/entrypoint-lib.sh` holds the steps both share.
- `docker/healthcheck.sh`: the Docker healthcheck, `NaoSim.isReady` on 9559.
- `docker/modules/`: Python 2.7 modules loaded inside NAOqi: `nao_sim_status_*` (the `NaoSim` service: versions, device sources, readiness, as a service and `NaoSim/*` ALMemory keys), `nao_sim_tts_core` (tag parsing, engine call, events), `nao_sim_tts_almodule` (2.1, `ALModule`), `nao_sim_tts_qiservice` (2.8, qi service).
- `docker/tts/`: the speech engine container (Piper + eSpeak NG, `POST /say`, streams PCM to the host audio output).
- `src/nao_sim/sim.py`, `config.py`, `stack.py`, `viewer.py`, `cli.py`: the `NaoSim` object, its `NaoSimConfig` (JSON, examples in `examples/configs/`), the containers, the sim window (nao-viewer, the `viewer` extra) and the `nao-sim` command.
- `src/nao_sim/audio_output.py`: the host audio output a `NaoSim` runs, a dumb PCM player whose audio goes to a sink: the output device, nothing (`silent`), a WAV file (`record`) or memory (tests).
- `src/nao_sim/docker_images.py` and `src/nao_sim/suite.py`: `nao-sim fetch-and-build-images`, which fills `docker/vendor/<version>/` with the pinned Choregraphe suite and the `animations` package extracted from the public robot image (all from Aldebaran's GitHub repositories and hash-checked; keeps what is already there), builds the images with the nao-sim version as label, and boots them once to verify them (`docker/vendor/images.json`).
- `docker/vendor/`: gitignored; `2.1/` and `2.8/` each hold the suite tarball and `animations.pkg`; `images.json` lists the verified images.
- `docker/compose.yaml`: also a package store volume per version, so packages installed over qi or Choregraphe (the sound set) survive `docker compose down`; `down -v` resets them.
- `tests/`, `tests-e2e/`: the fast tier and the live tier, which starts the containers itself.

## Run

Python 3.12 or 3.13 on macOS (arm64) or Linux (x86_64): the libqi wheels (`qi`, from
[funwithagents/libqi-python](https://github.com/funwithagents/libqi-python)) exist for those only.

```bash
uv sync --dev
uv run nao-sim fetch-and-build-images   # fetch, build and verify the 2.1 and 2.8 images (or: 2.1 / 2.8); rerun after changing docker/
uv run nao-sim run                      # NAOqi 2.1 with the sim window, speech on the loudspeaker; Ctrl-C stops it
uv run nao-sim run --config examples/configs/2.8.json       # or NAOqi 2.8; headless.json: no window, silent
uv run nao-sim status                   # from another terminal: the containers and the robot's state
uv run nao-sim logs --follow            # the containers' logs
uv run nao-sim cleanup                  # after a run that died without stopping
```

Then connect any qi client to `tcp://127.0.0.1:9559`, as to a NAO. The `NaoSim` service tells a client it is on nao-sim (`getVersion`, `getNaoqiVersion`, `isReady`; `NaoSim/*` keys in ALMemory): it reports the nao-sim version the images were built with. The compose project is `nao-sim`, so the package store volumes are `nao-sim_packages-2.1` and `nao-sim_packages-2.8`.

## Test

```bash
uv run pytest             # fast tier: no Docker, no suite
uv run pytest tests-e2e   # live tier: builds the images if needed, runs 2.1 and 2.8 with NaoSim
```

Stop any running nao-sim before the live tier: it needs ports 9559 and 9562.
