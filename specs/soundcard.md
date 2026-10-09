---
code:
  - src/nao_sim/soundcard.py
tests:
  - tests/test_soundcard.py
  - tests-e2e/test_speech_live.py
---

# Host sound card

**Status:** Updated

## Purpose

The host's loudspeaker as a device the containers stream into. It plays PCM as it arrives and stops on request. It knows nothing about NAOqi or speech: no tags, no events, no `say()` semantics. Today the `tts` engine ([tts-engine.md](tts-engine.md)) is its only client; the planned `ALAudioPlayer` shim (sound files) and the full `ALAudioPlayer` replacement will stream into it too.

## Decided

### Command

`nao-sim-soundcard [--listen HOST:PORT] [--record FILE] [--silent]`, for a stack started by hand with `docker compose`; a `NaoSim` ([api.md](api.md)) runs the same sound card in-process instead. It listens on `0.0.0.0:9562` by default; the containers reach it at `host.docker.internal:9562`.

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
- With a `DevicePlayer` (see "Audio sinks"), audio goes to the default output device through `sounddevice` (`RawOutputStream`, int16), opened per stream.

### Audio sinks

Where the played audio goes is a seam, as tts-engine's `AudioSink` (its `specs/audio-sink.md`), adapted to a card that receives several streams with their own format and that can cut one off. The sound card owns the protocol, the generations and the pacing; the sink only receives audio.

```python
class AudioSink(Protocol):
    def begin(self, rate: int, channels: int) -> None:
        """A new stream starts."""

    def feed(self, chunk: bytes) -> None:
        """Interleaved s16le PCM, at most 100 ms."""

    def end(self, interrupted: bool) -> None:
        """The stream finished, or was cut by a stop or a newer stream."""
```

- **Call discipline:** for each stream, `begin` once, `feed` any number of times, `end` exactly once, also when the stream fails. Calls come from the card's connection threads, never overlapping: the card ends the current stream before it begins a newer one.
- **The card paces, the sink does not.** Chunks are fed in real time whatever the sink, so `say()` timing and stop behave the same with a device, a file or memory (what `--silent` does today).
- **Shipped sinks:**

  | Sink | Does | Chosen by |
  | --- | --- | --- |
  | `DevicePlayer(device=None)` | Plays on the output device (`sounddevice`, imported lazily at the first `begin`, so a host without PortAudio can use the other sinks) | `speaker.mode = "play"`, the default |
  | `NullSink()` | Discards | `"silent"`, `--silent` |
  | `WavSink(path)` | Writes mono 16-bit WAV, reopened when the rate changes (today's `--record`) | `"record"`, `--record FILE` |
  | `MemorySink()` | Keeps each stream as a `Playback(rate, channels, pcm, started_at, ended_at, interrupted)`; `playbacks`, `wait_for(predicate, timeout)` | Tests, passed as `NaoSim(config, sink=MemorySink())` |

- `SoundCard(sink)` takes one sink. The command builds it from its flags, a `NaoSim` from its `sink=` argument or the config's `speaker` block ([api.md](api.md), "Construction").
- **Playing state** (whether, and until when, audio plays) belongs to the card, not the sink, so the microphone gate reads it from the card whatever the sink (open question 1).
- The stdout JSON lines stay for the command; the live tier moves from them to a `MemorySink` once it runs through `NaoSim`.

## Open questions

1. **Microphone gate source.** The speech spec's microphone gate (mute while playing, plus a 300 ms tail) needs to know when the card is playing. The card tracks `playing_until` but never sets it, and has no way to report it to the containers. Decide this together with the host link ([_overview.md](_overview.md), "Host services").
2. **Protocol versus host link.** This one-connection-per-stream protocol differs from the overview's single host-link design (one port, length-prefixed messages). Settle it before building the microphone and camera links.
3. **Device selection and volume.** There is no output device option, and `ALTextToSpeech.setVolume` is not applied to the audio.
4. **Mixing.** Sound files and speech cannot play at once (the newest stream wins), whereas a real NAO mixes them.
