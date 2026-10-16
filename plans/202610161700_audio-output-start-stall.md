# Audio output tests time from the stream's start

**Status:** Done

Implements [testing.md](../specs/testing/testing.md) ("Real time on a slow machine"). Two audio output tests failed together once on GitHub's Windows runner (PR #10's rebased run): the runner stalled about 0.3 s as a stream started. `test_set_changes_volume_and_pan_from_the_next_tick` sent its `set` 0.3 s after starting the play and assumed the audio's first 0.1 s was mixed by then, so its "before" sample already had the new volume; `test_late_wake_ups_do_not_drift_the_mix` timed the play from the client's connection, so the stall read as 0.31 s of extra duration, though its own tick-schedule checks passed. Test-only: the mixer behaved as specified.

## Scope

- `tests/test_audio_output.py` — the set test sends its `set` 0.2 s after a listener first hears the stream's audio; the drift test times the play from its first tick to the end of the client's call
- `specs/testing/testing.md` — real-time tests time from the stream's own start

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest` (three runs).
