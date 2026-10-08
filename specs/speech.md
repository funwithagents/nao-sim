---
code:
  - docker/modules/nao_sim_tts_core.py
  - docker/modules/nao_sim_tts_almodule.py
  - docker/modules/nao_sim_tts_qiservice.py
tests:
---

# Speech: ALTextToSpeech replacement

**Status:** Stable

## Purpose

On nao-sim, `ALTextToSpeech.say()` speaks with a real voice and keeps NAOqi's contract: it blocks for the real audio and raises the events and bookmarks that `ALAnimatedSpeech`, Choregraphe boxes and existing scripts rely on.

The desktop virtual robot's built-in TTS is a simulator, so it is replaced inside NAOqi ([service-replacement.md](service-replacement.md)) rather than listened to. The replacement:
- parses NAOqi's tags;
- asks the engine ([tts-engine.md](tts-engine.md)) to speak; the engine streams to the host sound card ([soundcard.md](soundcard.md));
- raises the events on its own clock, from the timings the engine returns.

Only one request and one reply cross from the NAOqi container per sentence, and no events travel back. On a real robot nothing changes: the robot speaks.

## Decided

### Why replace rather than listen (measured on 2.1.4.13)

- The desktop `naoqi-bin` has no speech engine plugin. `ALTextToSpeech` runs in a simulated mode: `say()` blocks 0.204 s per whitespace-separated token, whatever `setParameter("speed", N)` says (tested 50, 100, 200), and tags count as tokens (`\pau=2000\` costs 0.2 s).
- It raises the full event sequence on that clock, but the clock cannot be calibrated to a real voice. It is off by about a factor of two on normal speech (0.4 s per word), so a host listening to its events would speak out of sync:
  - `say()` returns early;
  - consecutive sentences overlap;
  - gestures land on simulated bookmarks.
- Event listening stays a documented fallback only for a version where replacement is impossible ([_overview.md](_overview.md), "Fallback: listening to TTS events"). No such version is known.

### The contract (measured on 2.1.4.13 and 2.8.7.4)

- **Methods of the built-in** (2.1 MetaObject): `say(str)`, `say(str, str)`, `sayToFile`, `sayToFileAndPlay`, `stopAll`, `setLanguage`, `getLanguage`, `getLanguageEncoding`, `getAvailableLanguages`, `getSupportedLanguages`, `resetSpeed`, `setParameter`, `getParameter`, `setVoice`, `getVoice`, `getAvailableVoices`, `setVolume`, `getVolume`, `locale`, `loadVoicePreference`, `setLanguageDefaultVoice`, `enableNotifications`, `disableNotifications`, plus the `ALModule` generics, and the signal `synchroTTS(timeval)`.
- **Events**: `ALTextToSpeech/TextStarted`, `TextDone`, `TextInterrupted`, `CurrentSentence`, `CurrentWord`, `PositionOfCurrentWord`, `CurrentBookMark`, `Status`. At idle only `ALAnimatedSpeech` subscribes, to `CurrentBookMark` and `Status`; `ALDialog` subscribes only while a topic runs.
- **`ALAnimatedSpeech` 2.1** calls `enableNotifications()` once at load. Then, per `say`, it calls `getLanguage()` and the one-argument `say(text)` with annotated text: `\pau=500\ \mrk=1\ text \mrkpause=2\`. It adds `\pau=500\` in every mode, including contextual and disabled.
  - It waits for `CurrentBookMark N` for every `\mrk=N\` **and** every `\mrkpause=N\`; otherwise it fails with "instruction N has not been received in time".
  - It also waits for `Status [id, "done"]`.
- **`ALAnimatedSpeech` 2.8** never calls `say`. It calls the hidden `_sayWithLocale(text, locale, uuid)`, where `locale` is a struct `{language, region}` and `uuid` is per call.
  - The text carries `\mrk=N\` only (no `\pau=500\`). In contextual mode it also contains the module's own auto-inserted `\mrk=N\` tags.
  - At start it connects to the hidden signal `_started`, and dies without it.
  - Bookmark and `Status` expectations are as on 2.1.
- **Choregraphe box library** (all 160 boxes of the 2.1 suite scanned):
  - Say box: `say` and `stop`.
  - Animated Say: goes through `ALAnimatedSpeech`.
  - About a dozen boxes: `getLanguage`.
  - Language boxes: `setLanguage`.
  - Nothing else.
- `ALDialog` is not a v1 target.

### Behaviour

- **Event sequence** for one `say`, matching the built-in's:
  1. `Status [id, "enqueued"]`, `TextStarted 1`, `TextDone 0`.
  2. After the engine replies: `Status [id, "started"]`, `CurrentSentence text`, and the `_started` signal (2.8).
  3. `CurrentBookMark N` at each marker offset.
  4. At the end: `TextInterrupted 1` (only if stopped), `Status [id, "done"]`, `CurrentSentence ""`, `TextDone 1`, `CurrentBookMark 0`, `TextStarted 0`.
- **Blocking**: `say()` returns when the engine's `duration` has elapsed from the reply, or on `stopAll`. Calls are serialized by a lock: a second `say` waits until the first is done.
- **Stop**: `stopAll()` ends the current `say` at once. Bookmarks not yet reached are not raised. The engine's `/stop` cuts the audio (measured within about 0.1 s).
- **Tags** (`nao_sim_tts_core.parse`):
  - `\pau=N\` becomes a pause item; `\mrk=N\` and `\mrkpause=N\` become mark items.
  - `\rspd=N\` and `\vct=N\` set rate and pitch; `\rst\` resets both to 100.
  - `\vol`, `\emph`, `\bound`, `\readmode`, `\tn` are ignored.
  - Rate and pitch apply to the whole call (the value in force at the end of the text) and carry over to later calls, like NAOqi's.
- **Parameters**:
  - `setParameter("speed"|"defaultVoiceSpeed", N)` sets the rate (percent).
  - `setParameter("pitchShift", x)` sets the pitch (x times 100 when x < 10).
  - `resetSpeed` sets the rate back to 100.
- **Language**: English and French. `say(text, language)` switches language for that call only (2.1: explicit second binding; 2.8: varargs). `setLanguage` also emits `languageTTS` (2.8).
- **Fallback clock**: if the engine is unreachable, `say()` still blocks for 0.3 s per token and raises bookmarks on that clock, so behaviours keep running without sound.
- **Stubs**: `setVoice`, `loadVoicePreference`, `setLanguageDefaultVoice`, `enableNotifications`, `disableNotifications` and `sayToFile` are accepted and logged, with no effect. `getVoice` returns `"naosim"`; `locale` returns `"en_US"`. 2.8 also has `_pause`, `_resume` and `reset`.
- **Diagnostics**: `whoami()` names the implementation. Calls are logged as JSON lines to `/home/nao/tts_almodule.jsonl` (2.1) or `/home/nao/tts_qiservice.jsonl` (2.8).
- **Measured end to end**:
  - 2.1: `say` blocked 4.74 s for 3.91 s of audio on the first call; `ALAnimatedSpeech` bookmarks arrived about 0.17 s after the engine's offsets (reply latency).
  - 2.8: `say` blocked 4.01 s for 3.69 s of audio.

## Open questions

1. **Stop during synthesis is lost** (defect). `Speaker.say` clears its stop flag after the engine replies, so a `stopAll` that arrives while the engine is still synthesizing (0.1–0.7 s) is dropped and the sentence plays in full. The fix is to clear the flag when `say()` starts. Scheduled in the baseline plan.
2. **Missing methods.** `getLanguageEncoding` and `sayToFileAndPlay` are not implemented, and the box library's `stop` is not a method of either replacement: 2.1 maps `stop` to the `ALModule` generic. Check what the Say box's `stop` does against the replacement.
3. **Microphone gate** (mute the microphone while playing, plus a 300 ms tail) and **subtitles** in the sim window are not built. Both depend on the host link.
4. **Duration tolerance** against real-robot `say()` (proposed ±20% per sentence) is not agreed, and the reference durations from a real robot have not been measured.
5. **Word events**: `CurrentWord` and `PositionOfCurrentWord` are not raised in v1 (see [tts-engine.md](tts-engine.md)).
