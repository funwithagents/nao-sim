# nao-sim (prototype)

A NAO in a box: NAOqi 2.1.4.13 (`naoqi-bin` from the Choregraphe suite) running in a local
Docker image with our Python 2.7 override modules loaded into its process. Unofficial, MIT;
the image is built locally from the user's suite and is never published.

Status: validation spike done on NAOqi 2.1.4.13 and 2.8.7.4, see [spike/RESULTS.md](spike/RESULTS.md).

## Layout

- `docker/Dockerfile.naoqi-2.1`: Ubuntu 14.04 amd64 + 2.1.4.13 suite tarball at `/opt/naoqi`, non-root user, entrypoint.
- `docker/Dockerfile.naoqi-2.8`: Ubuntu 16.04 amd64 + 2.8.7.4 suite, NAO V6 model, `naoqi-bin` behind the suite's gateway on 9559 (compose profile `2.8`; 2.1 is profile `2.1`).
- `docker/entrypoint-2.1.sh`, `docker/entrypoint-2.8.sh`: each version's boot procedure, top to bottom: start `naoqi-bin`, wait for a settled service list, keep the modules depending on `ALTextToSpeech` off it (2.1: left out of autoload; 2.8: their package service stopped), exit the built-in, load the native relay with `ALLauncher.launchLocal` and our modules with `ALLauncher.launchPythonModule`, bring the dependents back, check the replacements and the added services answer and mark `NaoSim` ready. Any failure exits non-zero. `docker/entrypoint-lib.sh` holds the steps both share.
- `docker/healthcheck.sh`: the Docker healthcheck, `NaoSim.isReady` on 9559.
- `docker/modules/`: Python 2.7 modules loaded inside NAOqi: `nao_sim_status_*` (the `NaoSim` service: versions, device sources, readiness, as a service and `NaoSim/*` ALMemory keys), `nao_sim_tts_core` (tag parsing, engine call, events), `nao_sim_tts_almodule` (2.1, `ALModule`), `nao_sim_tts_qiservice` (2.8, qi service), `nao_sim_audiodevice_*` (the `ALAudioDevice` the desktop suites lack: subscribers, formats, the host link client).
- `docker/relay/`: `_NaoSimAudioRelay`, a small C++ NAOqi module that hands each microphone buffer to a subscriber's `processRemote` as a binary, as a NAO's C++ `ALAudioDevice` does (Python 2.7 inside NAOqi cannot send one). Each image compiles it in a builder stage against the version's public C++ SDK headers (2.8: libqi from [funwithagents/libqi](https://github.com/funwithagents/libqi) and boost 1.64 too) and keeps only the `.so`.
- `docker/tts/`: the speech engine container (Piper + eSpeak NG, `POST /say`, streams PCM to the host audio output).
- `src/nao_sim/sim.py`, `config.py`, `stack.py`, `viewer.py`, `cli.py`: the `NaoSim` object, its `NaoSimConfig` (JSON, examples in `examples/configs/`), the containers, the sim window (nao-viewer, the `viewer` extra) and the `nao-sim` command.
- `src/nao_sim/audio_output.py`: the host audio output a `NaoSim` runs, a dumb PCM player whose audio goes to a sink: the output device, nothing (`silent`), a WAV file (`record`) or memory (tests).
- `src/nao_sim/audio_input.py`, `host_link.py`: the robot's microphones, served to `ALAudioDevice` over the host link (port 9563): the host microphone (`audio_input.source = "mic"`, with the gate that keeps the robot from hearing itself) or the fake source (`"fake"`: silence plus what code plays with `sim.fake_audio.play("hello.wav")`, for tests).
- `src/nao_sim/files.py`: where the recipes (`docker/`, shipped in the wheel as package data) and the image data are, in a checkout or installed.
- `src/nao_sim/docker_images.py` and `src/nao_sim/suite.py`: `nao-sim fetch-and-build-images`, which fills the image data folder (`docker/image-data/<version>/` in a checkout) with the pinned Choregraphe suite, the `animations` package extracted from the public robot image and the relay's build files (the version's C++ SDK, 334 MB for 2.1 and 1.1 GB for 2.8; libqi and boost for 2.8), all public and hash-checked; it keeps what is already there, builds the images with the nao-sim version as label, and boots them once to verify them (`docker/image-data/images.json`).
- `docker/image-data/`: gitignored; `2.1/` and `2.8/` each hold the suite tarball, `animations.pkg` and the relay's build files; `images.json` lists the verified images.
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
uv run nao-sim run --config examples/configs/mic.json       # the robot hears through your microphone
uv run nao-sim status                   # from another terminal: the containers and the robot's state
uv run nao-sim logs --follow            # the containers' logs
uv run nao-sim cleanup                  # after a run that died without stopping
```

Then connect any qi client to `tcp://127.0.0.1:9559`, as to a NAO. The `NaoSim` service tells a client it is on nao-sim (`getVersion`, `getNaoqiVersion`, `isReady`; `NaoSim/*` keys in ALMemory): it reports the nao-sim version the images were built with. The compose project is `nao-sim`, so the package store volumes are `nao-sim_packages-2.1` and `nao-sim_packages-2.8`.

## Use from another project

nao-sim is not on PyPI: a project depends on it from GitHub, with uv, pinned to a commit or tag.
In the project's `pyproject.toml`:

```toml
[project]
requires-python = ">=3.12,<3.14"            # the libqi wheels' range
dependencies = ["nao-sim[viewer]"]          # or "nao-sim": no window, no render camera

[tool.uv.sources]
nao-sim = { git = "https://github.com/funwithagents/nao-sim", rev = "<commit or tag>" }

[tool.uv]
environments = [                             # the platforms the libqi wheels exist for
    "sys_platform == 'darwin' and platform_machine == 'arm64'",
    "sys_platform == 'linux' and platform_machine == 'x86_64'",
]
```

uv takes `qi` and nao-viewer from nao-sim's own sources, so the project declares neither (and
should not pin nao-viewer at another commit). Then, once per machine:

```bash
uv sync
uv run nao-sim fetch-and-build-images   # the images; the suites go to the user data directory
uv run nao-viewer fetch-meshes          # optional: Aldebaran's meshes in the window (license prompt)
uv run nao-sim run                      # or a NaoSim in the project's code
```

An installed nao-sim reads its recipes from its package and keeps the image data (1.8 GB for
both versions), `hashes.json` and `images.json` in the user data directory
(`~/Library/Application Support/nao-sim/image-data` on macOS, `~/.local/share/nao-sim/image-data` on
Linux). `NAO_SIM_IMAGE_DATA=<folder>` points it, or a checkout, at another image data folder, so a
checkout and the projects depending on nao-sim can share one copy. nao-viewer's meshes are shared
by every environment on the machine already. pip is not supported: it ignores uv's sources and
finds no `qi` 3.1.6 on PyPI.

## Test

```bash
uv run pytest             # fast tier: no Docker, no suite
uv run pytest tests-e2e   # live tier: builds the images if needed, runs 2.1 and 2.8 with NaoSim
```

Stop any running nao-sim before the live tier: it needs ports 9559 and 9562.
