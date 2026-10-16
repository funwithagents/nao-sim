# Two flaky audio tests: a chunk after `stop()`, a need lost before registration

**Status:** Done

Implements [audio-input.md](../specs/host/audio-input.md) ("On the host link", "Nothing is sent after the need ends") and [devices.md](../specs/host/devices.md) ("The host link", "A connection before its handler is kept, with what it said"). Two races the fast tier showed once each on a loaded machine, each a real defect:

1. **A chunk after `stop()`** (CI's macOS runner, PR #7's first run, `test_a_need_before_start_is_served_after_it_and_stop_resets_the_keys`): `stop()` halted the producer and joined it while holding the device's lock; the producer, between its wait and the lock it took to read the connection and the need, blocked on that lock, the join timed out after a second, and once the lock was released the producer sent its block. On a fast machine the producer is asleep in its wait when the halt comes, so the race never shows.
2. **A need lost before registration** (this Mac under the parallel tier, `test_the_need_is_sent_again_after_the_host_comes_back`, and `test_energy_is_reported_only_while_enabled` reading `host.conn` before the host had read the hello): a service connecting before its handler registers had its connection handed over at registration, but every message sent meanwhile, its first `need` included, was dropped. In production the containers boot before step 6 registers the audio input, so a need sent at boot was lost until the next change.

## Scope

- `src/naoqi_sim/audio_input.py` — the handlers publish the connection, the formats and the energy flag as one snapshot (`_need`) under the lock; the producer reads that reference and never takes the lock; after the source read, a set halt drops the block instead of sending it; `connected` also updates
- `src/naoqi_sim/host_link.py` — `_pending`: for a service without a handler, the newest message of each type in arrival order, replayed by `register` after `connected`; cleared when the connection ends or is replaced
- `tests/test_audio_input.py` — `BlockingSource` and a test that stops the device while the producer is inside `read()`: the stop waits for the join timeout and nothing is sent after it
- `tests/test_host_link.py` — messages sent before the handler reach it, the newest of each type, in order
- `tests/test_audio_device_core.py` — the fixture waits for the host to have read the hello (`Host.wait_connected`)
- `specs/host/audio-input.md`, `specs/host/devices.md` — the two guarantees

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest` (three runs), and the live audio tests on both versions (`tests-e2e/test_audio_input_live.py`), since the host link changed.
