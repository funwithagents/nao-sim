---
code:
  - src/nao_sim/soundcard.py
tests:
---

# Host sound card

**Status:** Stable

## Purpose

The host's loudspeaker as a device the containers stream into. It plays PCM as it arrives and stops on request. It knows nothing about NAOqi or speech: no tags, no events, no `say()` semantics. Today the `tts` engine ([tts-engine.md](tts-engine.md)) is its only client; the planned `ALAudioPlayer` shim (sound files) and the full `ALAudioPlayer` replacement will stream into it too.

## Decided

### Command

`nao-sim-soundcard [--listen HOST:PORT] [--record FILE] [--silent]`. It listens on `0.0.0.0:9562` by default; the containers reach it at `host.docker.internal:9562`.

- `--record FILE` writes everything played to a mono 16-bit WAV. The file is reopened (overwritten) when the sample rate changes.
- `--silent` opens no audio device but paces the data in real time, so timing and stop behave as with a device. Used for tests and CI.
- State is reported on stdout as one JSON line per event: `listening`, `start` (`rate`, `channels`), `interrupted` (`played_s`), `end` (`played_s`), `stop-request`. Each line carries a `t` timestamp.

### Protocol (TCP)

Each connection carries one command: a JSON header line, then a body.

- `{"cmd": "play", "rate": 22050, "channels": 1, "format": "s16le"}`, then raw interleaved s16le PCM until the sender closes its side. Playback starts with the first 100 ms of data; `play` returns when the data ends, the stream is stopped, or a newer stream starts.
- `{"cmd": "stop"}`, no body: interrupts the current playback.
- An unparsable header closes the connection without effect.

### Semantics

- **One stream at a time, the newest wins.** Each `play` gets a generation number. An older stream that is still receiving stops at its next 100 ms chunk and logs `interrupted`.
- **Stop latency** is at most one chunk (100 ms) plus the device buffer.
- Audio goes to the default output device through `sounddevice` (`RawOutputStream`, int16), opened per stream.

## Open questions

1. **Microphone gate source.** The speech spec's microphone gate (mute while playing, plus a 300 ms tail) needs to know when the card is playing. The card tracks `playing_until` but never sets it, and has no way to report it to the containers. Decide this together with the host link ([_overview.md](_overview.md), "Host services").
2. **Protocol versus host link.** This one-connection-per-stream protocol differs from the overview's single host-link design (one port, length-prefixed messages). Settle it before building the microphone and camera links.
3. **Device selection and volume.** There is no output device option, and `ALTextToSpeech.setVolume` is not applied to the audio.
4. **Mixing.** Sound files and speech cannot play at once (the newest stream wins), whereas a real NAO mixes them.
