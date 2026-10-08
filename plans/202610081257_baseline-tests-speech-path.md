# Baseline tests for the container and speech path

**Status:** Todo

Brings the code built during the validation spike under test so its specs can be promoted to `Implemented`. The specs are [container.md](../specs/container.md), [service-replacement.md](../specs/service-replacement.md), [speech.md](../specs/speech.md), [tts-engine.md](../specs/tts-engine.md) and [soundcard.md](../specs/soundcard.md). The plan also fixes the one known defect in that code, a stop during synthesis being lost (speech.md, open question 1). It does not address the other open questions of those specs: readiness timeout, healthcheck, load-failure checks, gate, host link.

## Scope

- `docker/modules/nao_sim_tts_core.py`: fix the stop race; make the module importable under Python 3 (for tests) while staying Python 2.7 code.
- `pyproject.toml`: pyright `extraPaths` for `docker/modules` and `docker/tts`, so tests importing them type-check.
- `tests/test_soundcard.py`: sound card protocol and semantics, in process, `--silent` with a recording.
- `tests/test_tts_core.py`: tag parsing, the `say()` event sequence, stop (including during synthesis), the fallback clock.
- `tests/test_tts_engine.py`: `render()` marker offsets, pauses and resampling, with a fake synthesizer.
- `tests-e2e/support.py`: `connect(url)` with a retry.
- `tests-e2e/test_speech_live.py`: `say`, `ALAnimatedSpeech` bookmarks and `stopAll` against a running container.
- The five specs, `specs/_index.md`, this plan and `plans/_index.md`: statuses and `tests:` frontmatter.

## Steps

1. **Python 3 importability of the core.**
   - In `nao_sim_tts_core.py`, replace `import urllib2` with `try: import urllib2` / `except ImportError: import urllib.request as urllib2`.
   - Encode the request bodies with `.encode("utf-8")` (a no-op for the ASCII `str` that Python 2's `json.dumps` returns).
   - No other change: still no f-strings or annotations.
2. **Fix the stop race.**
   - In `Speaker.say`, call `self._stop.clear()` right after taking the lock, before the engine call, and remove the later `clear()`.
   - A `stopAll` during synthesis then makes the first `wait` return at once: `say` raises `TextInterrupted`, calls the engine's `/stop` and returns.
3. **pyright.** Add `extraPaths = ["docker/modules", "docker/tts"]` to `[tool.pyright]`. Tests import the modules by name after inserting those directories into `sys.path` in `tests/conftest.py`.
4. **`tests/test_soundcard.py`.** Start `Server(("127.0.0.1", 0), SoundCard(record=tmp_wav, silent=True))` in a thread, as a fixture. Tests:
   - A `play` stream of N samples records exactly N frames at the header's rate, and the connection stays open for about N/rate seconds (real-time pacing).
   - A `stop` connection during a 2 s stream ends playback within 0.2 s, and the recording is shorter than the stream.
   - A second `play` while the first is streaming interrupts the first; the second is recorded in full.
   - An unparsable header leaves the card idle and able to play the next stream.
5. **`tests/test_tts_core.py`.** Use a `Speaker` with a recording `raise_event`/`signal` and a fake `_engine_say` returning chosen `duration`/`marks` (subclass or attribute override); keep durations at 0.05–0.3 s. Tests:
   - `parse`: pauses, marks and mrkpause become items; `\rspd`, `\vct` and `\rst` set the returned rate and pitch and carry over to the next call through `state`; ignored tags drop out; text between tags is stripped.
   - Event sequence: one `say` raises the speech.md sequence in order, bookmarks in offset order, and returns after about `duration`.
   - `stop_all` mid-sentence: `say` returns early, raises `TextInterrupted 1`, skips the remaining bookmarks and calls `_engine_stop`.
   - `stop_all` during synthesis: the fake engine sleeps 0.2 s before replying, `stop_all` is called at 0.1 s, and `say` returns right after the reply with `TextInterrupted`. This test fails before step 2.
   - The engine raises an error: the fallback clock blocks 0.3 s per token and raises the `\mrk` bookmarks at their token positions.
   - `set_parameter` and `get_parameter` round-trip speed and pitchShift.
6. **`tests/test_tts_engine.py`.** Import `server`, monkeypatch `synth_piper`/`synth_espeak` to return tones of known lengths at chosen rates. Tests:
   - Marks sit at the cumulative durations before them.
   - Pauses add exactly `ms` of silence.
   - A part at another rate is resampled to the first part's rate, and the total duration adds up.
   - Empty text items are skipped.
   - No text at all yields 22050 Hz.
7. **`tests-e2e/support.py`.** Add `connect(url, attempts=5)`, which retries `qi.Session().connect` (libqi 3 against 2.1 fails about one time in three).
8. **`tests-e2e/test_speech_live.py`.**
   - Setup: `require_env("NAO_SIM_URL")` and `pytest.importorskip("qi")`. The libqi wheel is installed by hand; it is not a dependency. Start an in-process sound card (`--silent --record`) on 9562 as a module fixture. Subscribe to `ALTextToSpeech/CurrentBookMark` and `Status` from the host.
   - `ALTextToSpeech.whoami()` names the nao-sim replacement, which proves the replacement procedure ran.
   - `say("<reference sentence>")` blocks for at least 80% of the recorded audio length, and for at most the audio length plus 1.5 s.
   - `ALAnimatedSpeech.say("^start(animations/Stand/Gestures/Hey_1) Hello ^wait(...) second part")`: every bookmark the TTS received is raised, and `say` returns without the "not received in time" error. Use a behaviour name that exists or a plain `\mrk`-producing annotation; check what the suite accepts without the `animations` package.
   - `stopAll` 0.5 s into a long sentence makes `say` return within 0.5 s, and the recording is shorter than the full sentence.
   - The test runs unchanged against the 2.1 and the 2.8 container.
9. **Statuses and frontmatter.**
   - Add the new test files to the `tests:` lists: soundcard.md gets `test_soundcard.py`; speech.md gets `test_tts_core.py` and `tests-e2e/test_speech_live.py`; tts-engine.md gets `test_tts_engine.py`; container.md and service-replacement.md get `tests-e2e/test_speech_live.py`.
   - Once Verification passes: mark the five specs `Implemented` (file and index), remove speech.md open question 1, and mark this plan `Done`.

## Verification

- `uv run ruff check .`, `uv run pyright`, `uv run pytest`: all green. The new fast tests take a few seconds in total.
- Bring each stack up:
  - 2.1: `docker compose -f docker/compose.yaml up -d --build`.
  - 2.8: `docker compose -f docker/compose.yaml --profile 2.8 up -d --build tts naoqi28`.

  Wait for `nao-sim ready`, then run `NAO_SIM_URL=tcp://127.0.0.1:9559 uv run pytest tests-e2e` against each. Both must pass. Do not run the standalone `nao-sim-soundcard` at the same time: the test starts its own on 9562.
- Run `python -m py_compile` on `docker/modules/*.py` with the image's Python 2.7 (`docker run --rm --entrypoint python nao-sim/naoqi:2.1.4.13 -m py_compile /opt/naoqi/modules/nao_sim_tts_core.py`, after a rebuild) to confirm the core is still valid Python 2.7.
