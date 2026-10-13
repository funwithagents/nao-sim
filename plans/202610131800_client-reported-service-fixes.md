# Two client-reported faults: a name subscribed again, a language not installed

**Status:** Done

Implements [audio-device.md](../specs/services/audio-device.md) ("Delivery": a name registered again) and [speech.md](../specs/services/speech.md) ("Behaviour": a language that is not installed raises). A client's live tests against naoqi-sim at `c1f4e02` found both, on 2.1 and 2.8: every other session of a client that registers its audio service again under the same name heard nothing (the relay kept a proxy to the destroyed service), and `setLanguage("Klingon")` was accepted. Nothing else in either service changes.

## Scope

- `docker/naoqi/services/audio-device/naoqi_sim_audio_device_core.py`: `subscribe` (also of a name still subscribed) and `unsubscribe` tell the relay to forget the name's proxy, as a dropped subscriber already did; a failed forget is logged
- `docker/naoqi/services/speech/naoqi_sim_speech_core.py`: `LANGUAGES`, the one list; `set_language`, `say` and `start` raise a `RuntimeError` for a language not in it, `start` before its thread
- `docker/naoqi/services/speech/naoqi_sim_speech_almodule.py`, `naoqi_sim_speech_qiservice.py`: `getAvailableLanguages` and `getSupportedLanguages` return `LANGUAGES`
- `tests/test_audio_device_core.py`: the fake relay caches a proxy per name as the real one does, a name registered again making it stale; a name subscribed again after an unsubscribe (three rounds) and after dying without one gets the buffers
- `tests/test_speech_core.py`: an unknown language is refused by `set_language` (language and `languageTTS` unchanged) and by `say`/`start` (nothing spoken)
- `tests-e2e/support.py`: `Listener` takes an optional name
- `tests-e2e/test_audio_input_live.py`: three sessions in a row under one name each hear; a client that died and registered again hears
- `tests-e2e/test_speech_live.py`: `setLanguage("Klingon")` and `say(text, "Klingon")` raise through qi, `getLanguage()` unchanged
- `specs/services/audio-device.md`, `specs/services/speech.md`, `specs/_index.md`, this plan, `plans/_index.md`

## Steps

1. The audio device core forgets the relay's proxy on `unsubscribe` and `subscribe`. The 2.8 shell needed nothing: it delivers through the same C++ relay, and its own session only reaches the relay and asks for a name's service afresh in `_exists`.
2. The speech core's `LANGUAGES` and its check; the shells return it. The C++ front forwards the core's error to its caller on both versions (`ALProxy` raises on 2.1, `qi::AnyObject::call` on 2.8).
3. Fast tests, then the live tests on 2.1 and 2.8.
4. Statuses: this plan `Done`, both specs back to `Implemented`.

## Verification

- Lint, format, types, the fast tier; the new fast tests fail against the old audio device core.
- `uv run pytest tests-e2e/test_audio_input_live.py tests-e2e/test_speech_live.py` on 2.1 and 2.8, locally on macOS: 45 passed, 1 skipped (`languageTTS` is 2.8 only).
