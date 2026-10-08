# Baseline tests for the container and speech path

**Status:** Done

Brings the code built during the validation spike under test so its specs can be promoted to `Implemented`. The specs are [container.md](../specs/container.md), [service-replacement.md](../specs/service-replacement.md), [speech.md](../specs/speech.md), [tts-engine.md](../specs/tts-engine.md) and [soundcard.md](../specs/soundcard.md). Along the way it:

- fixes the one known defect in that code, a stop during synthesis being lost (speech.md, open question 1);
- moves the host code to Python 3.12 and makes libqi (`qi`) a runtime dependency, as in nao-viewer ([project.md](../specs/project.md) goes `Updated` → `Implemented`);
- makes the live tier start and stop the containers itself, with no target URL ([testing.md](../specs/testing.md) goes `Updated` → `Implemented`).

It does not address the other open questions of those specs: readiness timeout, healthcheck, load-failure checks, gate, host link.

## Scope

- `docker/modules/nao_sim_tts_core.py`: fix the stop race; make the module importable under Python 3 (for tests) while staying Python 2.7 code.
- `pyproject.toml`: `requires-python = ">=3.12,<3.14"`, `qi==3.1.6` from the fork's GitHub release wheels, `[tool.uv] environments` (macOS arm64, Linux x86_64), ruff and pyright targets 3.12, pyright `extraPaths` for `docker/modules` and `docker/tts`.
- `src/nao_sim/soundcard.py`: a public `close()` (used by `main` and the tests) instead of reaching into `_wav`.
- `tests/test_soundcard.py`: sound card protocol and semantics, in process, `--silent` with a recording.
- `tests/test_tts_core.py`: tag parsing, the `say()` event sequence, stop (including during synthesis), the fallback clock.
- `tests/test_tts_engine.py`: `render()` marker offsets, pauses and resampling, with a fake synthesizer.
- `tests-e2e/support.py`: `connect(url)` with a retry, and the stack helpers (`docker compose` up, wait for ready, down); `require_env` goes.
- `tests-e2e/conftest.py`: the sound card and the per-version stack fixtures.
- `tests-e2e/test_speech_live.py`: `say`, `ALAnimatedSpeech` bookmarks and `stopAll` against each version's container.
- Docs: testing.md, project.md, AGENTS.md and README.md for the above; every mention of running against a real NAO or of nao-bridge is removed from the tracked files (nao-sim behaves like a NAO in its API; which clients use it is not its concern).
- The seven specs, `specs/_index.md`, this plan and `plans/_index.md`: statuses and `tests:` frontmatter.

## Steps

1. **Python 3 importability of the core.**
   - In `nao_sim_tts_core.py`, replace `import urllib2` with `try: import urllib2` / `except ImportError: import urllib.request as urllib2`.
   - Encode the request bodies with `.encode("utf-8")` (a no-op for the ASCII `str` that Python 2's `json.dumps` returns).
   - No other change: still no f-strings or annotations.
2. **Fix the stop race.**
   - In `Speaker.say`, call `self._stop.clear()` right after taking the lock, before the engine call, and remove the later `clear()`.
   - A `stopAll` during synthesis then makes the first `wait` return at once: `say` raises `TextInterrupted`, calls the engine's `/stop` and returns.
3. **Python 3.12 and libqi.**
   - `requires-python = ">=3.12,<3.14"` (capped by the libqi wheels, cp312 and cp313); ruff `target-version = "py312"`, pyright `pythonVersion = "3.12"`.
   - `qi==3.1.6` in `dependencies`. `[tool.uv.sources]` points it at the four wheels of the `funwithagents/libqi-python` v3.1.6 release (cp312/cp313 × macOS 15 arm64/manylinux 2.34 x86_64), with markers, exactly as nao-viewer does. The direct URLs also keep uv from picking Aldebaran's `qi` 3.1.5 on PyPI.
   - `[tool.uv] environments` limits the lock to macOS arm64 and Linux x86_64, the platforms with wheels. Other platforms fail at install instead of getting a half-working nao-sim.
   - pyright `extraPaths = ["docker/modules", "docker/tts"]`; tests import those modules by name after `tests/conftest.py` inserts the directories into `sys.path`.
4. **`tests/test_soundcard.py`.** A fixture starts `Server(("127.0.0.1", 0), SoundCard(record=tmp_wav, silent=True))` in a thread. Tests:
   - A `play` stream of N samples records exactly N frames at the header's rate, and the connection stays open for about N/rate seconds (real-time pacing).
   - A `stop` connection during a 2 s stream ends playback within 0.2 s, and the recording is shorter than the stream.
   - A second `play` while the first is streaming interrupts the first (`interrupted` event); the second is played in full.
   - An unparsable header leaves the card idle and able to play the next stream.
5. **`tests/test_tts_core.py`.** Use a `Speaker` with a recording `raise_event`/`signal` and a fake engine (subclass overriding `_engine_say`/`_engine_stop`) returning chosen `duration`/`marks`; keep durations at 0.05–0.3 s. Tests:
   - `parse`: pauses, marks and mrkpause become items; `\rspd`, `\vct` and `\rst` set the returned rate and pitch and carry over to the next call through `state`; ignored tags drop out; text between tags is stripped.
   - Event sequence: one `say` raises the speech.md sequence in order, bookmarks in offset order, and returns after about `duration`.
   - `stop_all` mid-sentence: `say` returns early, raises `TextInterrupted 1`, skips the remaining bookmarks and calls `_engine_stop`.
   - `stop_all` during synthesis: the fake engine sleeps 0.2 s before replying, `stop_all` is called at 0.1 s, and `say` returns right after the reply with `TextInterrupted`. This test fails before step 2.
   - The engine raises an error: the fallback clock blocks per token and raises the `\mrk` bookmarks at their token positions.
   - `set_parameter` and `get_parameter` round-trip speed and pitchShift.
6. **`tests/test_tts_engine.py`.** Import `server`, monkeypatch `synth_piper`/`synth_espeak` to return tones of known lengths at chosen rates. Tests:
   - Marks sit at the cumulative durations before them.
   - Pauses add exactly `ms` of silence.
   - A part at another rate is resampled to the first part's rate, and the total duration adds up.
   - Empty text items are skipped.
   - No text at all yields 22050 Hz.
7. **Live tier support (`tests-e2e/support.py`, `tests-e2e/conftest.py`).**
   - `connect(url, attempts=5)` retries `qi.Session().connect` (libqi 3 against 2.1 fails about one time in three).
   - A session-scoped sound card listens on `0.0.0.0:9562`, where the `tts` container streams. It is the real `nao-sim-soundcard --silent`, run as a subprocess; the tests read its JSON events, whose `played_s` is the audio actually played.
   - A session-scoped `nao` fixture parametrized over `2.1` and `2.8`. For each version it:
     - skips when Docker is not available, or when neither that version's suite tarball (`docker/vendor/`) nor its image exists;
     - fails with a clear message when 127.0.0.1:9559 is already taken (another stack is running);
     - runs `docker compose -f docker/compose.yaml [--profile 2.8] up -d [--build] tts <service>` (`--build` only when the tarball is there);
     - waits for `[entrypoint] nao-sim ready` in the container log, then connects and checks that `ALTextToSpeech.whoami()` names the nao-sim replacement;
     - runs `docker compose ... down` on teardown.
   - Versions run one after the other (both publish 9559); pytest tears down one version's stack before starting the next.
8. **`tests-e2e/test_speech_live.py`.**
   - `ALTextToSpeech.whoami()` names the nao-sim replacement for the version, which proves the replacement procedure ran.
   - `say("<reference sentence>")` blocks for at least 80% of the played audio length, and for at most the audio length plus 1.5 s.
   - `ALAnimatedSpeech.say("^start(animations/Stand/Gestures/Hey_1) ... ^wait(...) ...")`: every `\mrk`/`\mrkpause` id in the text the replacement received (read from its JSON log in the container) is raised as `CurrentBookMark`, and `say` returns. The behaviour itself is absent (no `animations` package), as in the spike.
   - `stopAll` 0.5 s into a long sentence makes `say` return within 0.5 s, and the sound card played less than the sentence's engine duration.
   - `stopAll` right after an async `say` (during synthesis) makes `say` return within 1 s with almost no audio played.
9. **Docs, statuses and frontmatter.**
   - testing.md: two tiers with the live tier driving its own stack; no target URL, no real-robot target. project.md: Python 3.12, `qi` from the fork's wheels, supported platforms. AGENTS.md: the e2e paragraph and the project map row. README.md: `uv sync`, Python 3.12, live tests.
   - Add the new test files to the `tests:` lists: soundcard.md gets `test_soundcard.py`; speech.md gets `test_tts_core.py` and `tests-e2e/test_speech_live.py`; tts-engine.md gets `test_tts_engine.py`; container.md and service-replacement.md get `tests-e2e/test_speech_live.py`.
   - Once Verification passes: mark the five Stable specs `Implemented` and testing.md and project.md back to `Implemented` (file and index), remove speech.md open question 1, and mark this plan `Done`.

## Verification

- `uv run ruff check .`, `uv run pyright`, `uv run pytest`: all green. The new fast tests take a few seconds in total.
- `uv run pytest tests-e2e` with no stack running: the 2.1 and 2.8 stacks are brought up, tested and taken down in turn, and every test passes on both. Do not run the standalone `nao-sim-soundcard` at the same time: the tests start their own on 9562.
- `compile()` of `docker/modules/*.py` with the image's Python 2.7 (`docker run --rm --entrypoint /opt/naoqi/bin/python2 -v $PWD/docker/modules:/m:ro nao-sim/naoqi:2.1.4.13 <script>`; there is no `python` on the image's `PATH`) confirms the modules are still valid Python 2.7.

## Outcome

- Fast tier: 24 tests, about 5 s. Live tier: 10 tests (5 per version), about 2.5 min including the image builds on OrbStack.
- The two stop-during-synthesis tests (fast and live) fail with the old flag clearing and pass with the fix.
- Python 2.7.8 (the 2.1 image) compiles all three modules and imports the core.
