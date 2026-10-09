---
code:
  - src/nao_sim/audio_output.py
tests:
  - tests/test_audio_output.py
  - tests-e2e/test_speech_live.py
---

# Audio output

**Status:** Implemented

## Purpose

The robot's loudspeaker as a host device ([devices.md](devices.md)) the containers stream into. It plays PCM as it arrives and stops on request. Today the `tts` engine ([tts-engine.md](../container/tts-engine.md)) is its only client; the `ALAudioPlayer` shim and replacement ([audio-player.md](../services/audio-player.md)) will stream into it too.

It is named after its role, not after a loudspeaker: where the audio ends up is a seam, the audio sink, and a test's sink is memory.

## Decided

### Naming

- Module `src/nao_sim/audio_output.py`, class `AudioOutput`, config block `audio_output` ([config.md](../runtime/config.md)).
- It was first built as the "speaker" (class `Speaker`, command `nao-sim-speaker`), and before that the "sound card".
- The `tts` container's `NAO_SIM_SOUNDCARD` setting keeps its name: it is internal to the container recipes.

### Run by `NaoSim`

The audio output has no command of its own: a running `NaoSim` ([api.md](../runtime/api.md)) starts it in-process, listening on `0.0.0.0:9562`, before the containers, and stops it after them. The containers reach it at `host.docker.internal:9562`. Its events (`start`, `interrupted`, `end`, `stop-request`) go to the debug log.

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

Where the played audio goes is a seam, as tts-engine's `AudioSink` (its `specs/audio-sink.md`), adapted to an output that receives several streams with their own format and that can cut one off. The audio output owns the protocol, the generations and the pacing; the sink only receives audio.

```python
class AudioSink(Protocol):
    def begin(self, rate: int, channels: int) -> None:
        """A new stream starts."""

    def feed(self, chunk: bytes) -> None:
        """Interleaved s16le PCM, at most 100 ms."""

    def end(self, interrupted: bool) -> None:
        """The stream finished, or was cut by a stop or a newer stream."""
```

- **Call discipline:** for each stream, `begin` once, `feed` any number of times, `end` exactly once, also when the stream fails. Calls come from the audio output's connection threads, never overlapping: it ends the current stream before it begins a newer one.
- **The audio output paces, the sink does not.** Chunks are fed in real time whatever the sink ([devices.md](devices.md), "Real time").
- **Shipped sinks:**

  | Sink | Does | Chosen by |
  | --- | --- | --- |
  | `DevicePlayer(device=None)` | Plays on the output device (`sounddevice`, imported lazily at the first `begin`, so a host without PortAudio can use the other sinks) | `audio_output.mode = "play"`, the default |
  | `NullSink()` | Discards | `"silent"` |
  | `WavSink(path)` | Writes mono 16-bit WAV, reopened when the rate changes; `close()` finishes the file (`NaoSim.stop()` calls it) | `"record"` |
  | `MemorySink()` | Keeps each stream as a `Playback(rate, channels, pcm, started_at, ended_at, interrupted)`; `playbacks`, `wait_for(predicate, timeout)` | Tests, passed as `NaoSim(config, sink=MemorySink())` |

- `AudioOutput(sink)` takes one sink. A `NaoSim` builds it from its `sink=` argument or the config's `audio_output` block ([api.md](../runtime/api.md), "Construction").
- The live tier runs its `NaoSim` with a `MemorySink` and asserts on the playbacks.

### Playing state

Whether audio is playing belongs to the audio output, not the sink, so the audio input's microphone gate ([audio-input.md](audio-input.md), "Microphone gate") reads it whatever the sink:

- `playing_until: float`, in `time.monotonic()` seconds: when the audio fed so far finishes playing (the last chunk's pacing deadline). In the past when idle.
- It is updated at every chunk and set to now on a stop or an interruption, so a cut stream ends the gate's playing period at once (the gate's tail still applies).
- Read from another thread without a lock: a float assignment is atomic in CPython.

## Open questions

1. **Device selection and volume.** The audio output has no output device option, and `ALTextToSpeech.setVolume` (or `ALAudioDevice.setOutputVolume`, [audio-device.md](../services/audio-device.md)) is not applied to the audio.
2. **Mixing.** Sound files and speech cannot play at once (the newest stream wins), whereas a real NAO mixes them. Decided with [audio-player.md](../services/audio-player.md), together with whether the audio output moves onto the host link ([devices.md](devices.md), open question 1).
