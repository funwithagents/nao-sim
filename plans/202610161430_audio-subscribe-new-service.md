# `ALAudioDevice.subscribe` accepts a service registered an instant before

**Status:** Done

Implements [audio-device.md](../specs/services/audio-device.md) (`subscribe(name)`). `test_the_default_format_is_48k_with_four_channels[2.1]` failed on CI (PR #9's third run) with `ALAudioDevice.subscribe: no module or service named 'NaoqiSimE2EListener3'`: the live tier's listener registers its qi service and subscribes at once, as a client does, and on 2.1 the core's existence check, an `ALProxy(name)` through the broker, does not reach a service registered an instant before. The core now gives the name `EXISTS_WAIT_S` (1 s) to appear, polling every 50 ms, before refusing it.

## Scope

- `docker/naoqi/services/audio-device/naoqi_sim_audio_device_core.py` — `_wait_exists`, `EXISTS_WAIT_S`, `EXISTS_POLL_S`; `subscribe` uses it
- `tests/test_audio_device_core.py` — a service visible 0.3 s after the subscribe is subscribed and its need sent; a missing name still raises, after its wait
- `specs/services/audio-device.md` — the wait, in `subscribe(name)`

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`, and `tests-e2e/test_audio_input_live.py` and `test_modules_live.py` (the Python 2.7 check) on 2.1 and 2.8, the images rebuilt.
