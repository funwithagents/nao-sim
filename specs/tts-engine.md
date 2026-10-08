---
code:
  - docker/tts/server.py
  - docker/tts/Dockerfile
tests:
  - tests/test_tts_engine.py
  - tests-e2e/test_speech_live.py
---

# TTS engine container

**Status:** Implemented

## Purpose

A small speech engine container that turns a list of text, marker and pause items into audio. It streams the PCM to the host sound card ([soundcard.md](soundcard.md)) and replies with the exact timings. It knows nothing about NAOqi: tags, events and `say()` semantics stay in the `ALTextToSpeech` replacement ([speech.md](speech.md)).

It is its own container because:
- the NAOqi images (glibc 2.19 on 2.1, Python 2.7, amd64 emulation on Apple Silicon) rule out every current engine;
- keeping the engine off the host keeps `pip install` light and isolates the engine's models and dependencies.

## Decided

### Image

- `python:3.12-slim`, native architecture (no emulation), `espeak-ng`, `piper-tts` (onnxruntime) and `numpy`. No torch, no cloud.
- Piper voices from `rhasspy/piper-voices` v1.0.0, baked into `/voices`: `en_US-lessac-medium` (English) and `fr_FR-siwis-medium` (French), keyed by NAOqi language name (case-insensitive). Unknown languages use English.
- Environment: `NAO_SIM_SOUNDCARD` (`host:port`, default `host.docker.internal:9562`), `NAO_SIM_TTS_ENGINE` (`piper` default, or `espeak`).
- With Piper, both voices are loaded at start, so the first `say` does not pay for it (about 0.5 s each).

### HTTP API (port 8080, standard-library `ThreadingHTTPServer`)

- `POST /say` with `{"language": "English", "rate": 100, "pitch": 100, "engine": "piper"|"espeak" (optional), "items": [...]}`. Items:
  - `{"type": "text", "text": "..."}`
  - `{"type": "mark", "id": N}`
  - `{"type": "pause", "ms": N}`

  The reply is `{"duration": s, "marks": {"N": offset_s}, "rate": sample_rate, "engine": name, "synth_time": s}`. On a synthesis error: 500 `{"error": ...}`.
- `POST /stop`: stops the stream in progress and sends a stop to the sound card. Returns `{"stopped": true}`.
- `GET /health`: `{"ok": true, "engine", "voices", "soundcard"}`.

### Rendering

- Each text item is synthesized on its own and the parts are concatenated, so a marker's offset is exactly the duration of everything before it. The cost is a small prosody break at each marker. The same scheme serves both engines.
- A pause item is silence of the given length. Offsets and durations are computed from sample counts, so they match the audio exactly.
- `rate` (percent, 100 = normal):
  - Piper: `length_scale = 100 / max(rate, 20)`.
  - eSpeak NG: `-s 175 * rate / 100` words per minute.
- `pitch` (percent) is passed to eSpeak NG as `-p pitch/2`; Piper ignores it.
- The output is mono s16le at the first text item's sample rate (22050 Hz for both Piper voices; 22050 when there is no text). Other parts are resampled by linear interpolation.
- The reply is sent as soon as synthesis is done. The PCM is streamed to the sound card in a background thread, in 100 ms chunks, so the caller's clock starts with the audio.
- Synthesis takes 0.1–0.2 s per sentence with Piper once the voices are loaded.

### Failure behaviour

- If the sound card is unreachable, the audio is dropped (logged) and `/say` still returns the timings, so callers keep their clock.
- A new `/say` while one is still streaming starts a new stream. The sound card plays only the newest one (see [soundcard.md](soundcard.md)).

## Open questions

1. **More languages and voices.** Only English and French are mapped; `getAvailableLanguages` on the NAOqi side is hard-coded to match. Adding a language means a voice in the image and a map entry.
2. **Word events.** `CurrentWord` and `PositionOfCurrentWord` would need per-word timings: eSpeak NG can produce them, Piper cannot. Not in v1.
3. **Stop and concurrent streams.** `/stop` sets one global flag that the next stream clears. A `/stop` racing a new `/say` can therefore be lost. It is harmless today, because the replacement serializes `say()`.
