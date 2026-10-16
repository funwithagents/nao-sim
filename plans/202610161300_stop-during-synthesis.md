# A stop during synthesis returns at once

**Status:** Done

Implements [speech.md](../specs/services/speech.md) ("Stop") and [tts-engine.md](../specs/container/tts-engine.md) ("`POST /stop`"). `test_stop_all_during_synthesis` on 2.8 failed twice in a day on CI (PR #7's second run, `main`'s run after PR #8), returning in 3.000 s and 3.011 s against a 3.0 s bound: a `stopAll` while the engine was still synthesizing was not lost, but `say()` only saw it after the engine's reply, which is Piper's synthesis of the 15 s test text, a steady 3 s on a GitHub runner. The spec said "at once". Now it is: `say()` waits for the reply on a thread while watching the stop flag, a stop during synthesis tells the engine to abandon that say and returns without the reply; the engine knows each say by the call's id, so the stop cancels it between items, before the stream, or even before the say has arrived, and plays nothing.

## Scope

- `docker/tts-engine/server.py` — `id` in `/say` and `/stop`; `stop_say`, `cancelled`, `Cancelled`; `render` checks before each item; `stream_to_soundcard(pcm, sr, say_id)` sends nothing for a cancelled say and stops at a cancellation; `/say` answers `stopped` for a cancelled say
- `docker/naoqi/services/speech/naoqi_sim_speech_core.py` — `_engine_call` (the reply on a thread, `ENGINE_POLL_S`, `/stop` with the id and `None` when stopped meanwhile); `_engine_say`/`_engine_stop` carry the id; `_speak` ends interrupted at once on `None` or a `stopped` reply
- `tests/test_speech_core.py` — the fake engine's new signatures; a stop during a 2 s synthesis returns in under 0.4 s with the engine told once, by id; a `stopped` reply ends the call interrupted without audio
- `tests/test_tts_engine.py` — a stop cancels its say between items, before any synthesis, and names one say only; a stopped say is not streamed
- `tests-e2e/test_speech_live.py` — `returned < 1.0`
- The two specs (`Updated` until this plan is `Done`)

## Result (Oct 16, 2026)

- Fast tier: 316 passed, 1 skipped (two runs); ruff, format and pyright clean.
- Live, both images rebuilt (the speech core and the engine changed), `test_speech_live.py`, `test_sound_live.py`, `test_modules_live.py` (the Python 2.7 compile check included) on 2.1 and 2.8: 29 passed, 1 skipped, 4 xfailed. `test_stop_all_during_synthesis` now bounds the return at 1.0 s.
- A first live attempt failed 2.1's verification boot (`_ALAutonomousBlinking` did not answer within the entrypoint's ten polls) while the fast tier ran in parallel on the same machine; idle, the boot passed. Not a code fault: do not load the machine during an image's verification boot.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`, then `uv run pytest tests-e2e/test_speech_live.py tests-e2e/test_sound_live.py` on 2.1 and 2.8 (the images rebuild: the speech core and the engine changed). Then the specs go back to `Implemented` and this plan to `Done`.
