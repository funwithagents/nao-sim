---
code:
  - src/nao_sim/soundcard.py
  - docker/modules/nao_sim_tts_core.py
  - docker/modules/nao_sim_tts_almodule.py
  - docker/modules/nao_sim_tts_qiservice.py
  - docker/tts/server.py
  - docker/tts/Dockerfile
tests:
---

# Speech

**Status:** Draft

## Purpose

On nao-sim, `ALTextToSpeech.say()` speaks with a real voice through the host and keeps NAOqi's contract: it blocks for the real audio and raises the events and bookmarks that `ALAnimatedSpeech`, Choregraphe boxes and existing scripts rely on. The desktop virtual robot's built-in TTS is a simulator (0.204 s per token, no sound), so it is replaced inside NAOqi, not listened to. Full rationale, measurements and the built-in contract are in [_overview.md](_overview.md), section "Speech".

## Decided

Built and verified by hand on NAOqi 2.1.4.13 and 2.8.7.4 during the validation spike. There are no automated tests yet.

- **Three components**, each knowing as little as possible:
  - `ALTextToSpeech` replacement (Python 2.7, inside NAOqi), with shared logic in `nao_sim_tts_core`. It parses NAOqi tags (`\pau`, `\mrk`, `\mrkpause`, `\rspd`, `\vct`, `\rst`), asks the engine to speak, raises the ALMemory events on the engine's clock, and returns when the audio ends or on `stopAll`. On 2.1 it is an `ALModule` registered through the broker (`nao_sim_tts_almodule`). On 2.8 it is a `qi.multiThreaded` `qi.Session` service (`nao_sim_tts_qiservice`) carrying the hidden `_started`, `synchroTTS` and `languageTTS` signals and `_sayWithLocale`.
  - `tts` container (Python 3, native architecture): `POST /say` `{language, rate, pitch, engine?, items: [{type: text|mark|pause, ...}]}` returns `{duration, marks: {id: offset}, rate, engine}` and streams the PCM to the sound card. Also provides `POST /stop` and `GET /health`. The engine is Piper (English `en_US-lessac-medium`, French `fr_FR-siwis-medium`, pre-loaded at start); eSpeak NG can be selected per request. Each text segment between markers is synthesized separately, so marker offsets are exact.
  - Host sound card (`nao-sim-soundcard`, port 9562): TCP, one connection per stream, a JSON header line (`{"cmd": "play", "rate", "channels", "format": "s16le"}`), then raw PCM until the sender closes. A `{"cmd": "stop"}` connection interrupts playback. `--record FILE` writes a WAV; `--silent` paces in real time without a device.
- **Event sequence** follows the built-in's: `Status [id, "enqueued"]`, `TextDone 0`, `Status [id, "started"]`, `CurrentSentence`, `CurrentBookMark N` at each offset, then `Status [id, "done"]`, `CurrentSentence ""`, `TextDone 1`, `CurrentBookMark 0`. `TextInterrupted 1` is raised on stop.
- **Replacement procedure** is per version and driven by the entrypoint's environment (see [_overview.md](_overview.md), "nao-sim"). On 2.1: hold back `animatedspeech` and `dialog`, `exit()` the built-in, load ours, then `launchLocal` the held-back modules. On 2.8: `stopService` on `expressivity.autonomousabilitiesmodules`, `exit()` the built-in, load ours, then `startService`.
- **Fallback clock**: if the engine is unreachable, `say()` still blocks and raises bookmarks at 0.3 s per token, so nao-sim keeps working without sound.
- `\rspd` and `\vct` apply per call (the last value in the text), not mid-sentence. `CurrentWord` and `PositionOfCurrentWord` are not raised.

## Open questions

1. **Stop during synthesis is lost.** `Speaker.say` clears its stop flag after the engine replies, so a `stopAll` that arrives while the engine is still synthesizing (0.1–0.7 s) is dropped and the sentence plays in full. The fix is to clear the flag when `say()` starts. This is a known defect, not a design question.
2. **Host link.** The sound card's one-connection-per-stream protocol differs from the overview's "Host services" design (one port, length-prefixed messages, containers connect out). Decide which one the audio input (`ALAudioDevice`) and camera links should use, then bring the other into line.
3. **Microphone gate** (mute the microphone while playing, plus a 300 ms tail) and **subtitles** in the sim window: not built.
4. **Duration tolerance** against real-robot `say()` (proposed ±20% per sentence) is not agreed, and the reference durations from a real robot have not been measured.
5. **Tests.** Candidates: tag parsing and the event sequence with a fake engine (needs Python 2.7, see [testing.md](testing.md)); sound card record and stop in the fast tier; an end-to-end `say` and `ALAnimatedSpeech` bookmark test in `tests-e2e/` with the card in `--silent --record` mode.
6. **Language and voice API**: `getAvailableLanguages` is hard-coded to English and French; `setVoice` is ignored.
