---
code:
  - src/nao_sim/speaker.py
tests:
  - tests/test_speaker.py
  - tests-e2e/test_speech_live.py
---

# Host devices

**Status:** Updated

## Purpose

The simulated robot's inputs and outputs, on the host. A NAO has a loudspeaker, microphones and cameras, and it perceives people; inside Docker, NAOqi has none of these, so nao-sim provides them on the host as **devices**: dumb, each doing one job, knowing nothing about NAOqi's tags, events or `say()` semantics. Every NAOqi-specific decision stays in the containers (the override modules) or, for the few devices that are ordinary qi clients, at the edge of the device.

| Device | Direction | Feeds or is fed by | State |
| --- | --- | --- | --- |
| [Speaker](#speaker) | Output: the robot's voice and sounds | The `tts` engine ([tts-engine.md](tts-engine.md)); later the `ALAudioPlayer` shim and replacement | Built (`speaker.py`); its audio sinks are not |
| Microphone (host mic or WAV replay) | Input | The `ALAudioDevice` replacement | Planned ([_overview.md](_overview.md), "ALAudioDevice replacement") |
| Camera (webcam or nao-viewer render) | Input | `ALVideoDevice.putImage` | Planned ([_overview.md](_overview.md), "Video injection") |
| Perception feed | Input | The people-perception contract in ALMemory | Planned ([_overview.md](_overview.md), "Perception") |

This spec holds the contract every device follows, then one section per device. A device that grows heavy moves to its own spec, linked from here. The NAOqi-side replacements the devices talk to (`ALAudioDevice`, the perception modules) are specified on their own: they run inside the container, this spec covers only the host side.

## Decided

### The device contract

- **Owned by `NaoSim`.** A running `NaoSim` ([api.md](api.md)) starts each device the config asks for (step 2 for the speaker, step 5 for the inputs of "Lifecycle"), in its own process, and stops them in reverse order. A device is never a user command: the only standalone entry point left is a debugging one (see [Speaker](#speaker), "Command").
- **Configured by its block** of [config.md](config.md): `speaker`, `audio` (the microphone), `camera`, later `perception`. A device whose block says `none` is not started.
- **Pluggable at its edge.** Where the data goes or comes from is a seam, chosen by the config or passed in code: the speaker's `AudioSink`; the microphone's source (host mic or WAV file); the camera's source (webcam or render). Tests plug in-memory ends.
- **Publishes its source.** An input device writes its `NaoSim/*/Source` key when it starts ([status-service.md](status-service.md), "ALMemory keys"), as an ordinary qi client; whether it resets it to `none` on stop is the device's to decide.
- **Real time.** A device paces its data in real time whatever its seam, so NAOqi's timing (a blocking `say()`, a microphone chunk cadence) is the same with a device, a file or memory.
- **Off unless asked** for the devices that capture the user: the webcam and the microphone run only when the config enables them, with an indicator in the sim window (or the terminal when headless) while live.
- **The link to the containers** is the speaker's own TCP protocol today. The single host link ([_overview.md](_overview.md), "Host services") is to be settled before the microphone and camera links are built (open question 1).

### Speaker

The host's loudspeaker as a device the containers stream into (formerly the "sound card"; the `tts` container's `NAO_SIM_SOUNDCARD` setting keeps that name). It plays PCM as it arrives and stops on request. Today the `tts` engine is its only client; the planned `ALAudioPlayer` shim (sound files) and the full `ALAudioPlayer` replacement will stream into it too.

#### Command

`nao-sim-speaker [--listen HOST:PORT] [--record FILE] [--silent]` (`src/nao_sim/speaker.py`). It is not meant to be started directly: a `NaoSim` runs the speaker in-process. The script exists until `NaoSim` is built (the README's hand-run stack and the live tier start it today); then it leaves `[project.scripts]` and only `python -m nao_sim.speaker`, same options, remains, for a stack started by hand with `docker compose` ([cli.md](cli.md), "Existing commands"). It listens on `0.0.0.0:9562` by default; the containers reach it at `host.docker.internal:9562`.

- `--record FILE` writes everything played to a mono 16-bit WAV. The file is reopened (overwritten) when the sample rate changes.
- `--silent` opens no audio device but paces the data in real time, so timing and stop behave as with a device. Used for tests and CI.
- State is reported on stdout as one JSON line per event: `listening`, `start` (`rate`, `channels`), `interrupted` (`played_s`), `end` (`played_s`), `stop-request`. Each line carries a `t` timestamp.

#### Protocol (TCP)

Each connection carries one command: a JSON header line, then a body.

- `{"cmd": "play", "rate": 22050, "channels": 1, "format": "s16le"}`, then raw interleaved s16le PCM until the sender closes its side. Playback starts with the first 100 ms of data; `play` returns when the data ends, the stream is stopped, or a newer stream starts.
- `{"cmd": "stop"}`, no body: interrupts the current playback.
- An unparsable header closes the connection without effect.

#### Semantics

- **One stream at a time, the newest wins.** Each `play` gets a generation number. An older stream that is still receiving stops at its next 100 ms chunk and logs `interrupted`.
- **Stop latency** is at most one chunk (100 ms) plus the device buffer.
- With a `DevicePlayer` (see "Audio sinks"), audio goes to the default output device through `sounddevice` (`RawOutputStream`, int16), opened per stream.

#### Audio sinks

Where the played audio goes is a seam, as tts-engine's `AudioSink` (its `specs/audio-sink.md`), adapted to a speaker that receives several streams with their own format and that can cut one off. The speaker owns the protocol, the generations and the pacing; the sink only receives audio.

```python
class AudioSink(Protocol):
    def begin(self, rate: int, channels: int) -> None:
        """A new stream starts."""

    def feed(self, chunk: bytes) -> None:
        """Interleaved s16le PCM, at most 100 ms."""

    def end(self, interrupted: bool) -> None:
        """The stream finished, or was cut by a stop or a newer stream."""
```

- **Call discipline:** for each stream, `begin` once, `feed` any number of times, `end` exactly once, also when the stream fails. Calls come from the speaker's connection threads, never overlapping: the speaker ends the current stream before it begins a newer one.
- **The speaker paces, the sink does not.** Chunks are fed in real time whatever the sink (the device contract's "Real time").
- **Shipped sinks:**

  | Sink | Does | Chosen by |
  | --- | --- | --- |
  | `DevicePlayer(device=None)` | Plays on the output device (`sounddevice`, imported lazily at the first `begin`, so a host without PortAudio can use the other sinks) | `speaker.mode = "play"`, the default |
  | `NullSink()` | Discards | `"silent"`, `--silent` |
  | `WavSink(path)` | Writes mono 16-bit WAV, reopened when the rate changes (today's `--record`) | `"record"`, `--record FILE` |
  | `MemorySink()` | Keeps each stream as a `Playback(rate, channels, pcm, started_at, ended_at, interrupted)`; `playbacks`, `wait_for(predicate, timeout)` | Tests, passed as `NaoSim(config, sink=MemorySink())` |

- `Speaker(sink)` takes one sink. The command builds it from its flags, a `NaoSim` from its `sink=` argument or the config's `speaker` block ([api.md](api.md), "Construction").
- **Playing state** (whether, and until when, audio plays) belongs to the speaker, not the sink, so the microphone gate reads it from the speaker whatever the sink (open question 2).
- The stdout JSON lines stay for the command; the live tier moves from them to a `MemorySink` once it runs through `NaoSim`.

As built, `Speaker(record=None, silent=False)` takes the two flags instead of a sink: the sinks are the gap this spec's `Updated` status marks.

## Open questions

1. **Protocol versus host link.** The speaker's one-connection-per-stream protocol differs from the overview's single host-link design (one port, length-prefixed messages). Settle it before building the microphone and camera links.
2. **Microphone gate source.** The speech spec's microphone gate (mute while playing, plus a 300 ms tail) needs to know when the speaker is playing. The speaker tracks `playing_until` but never sets it, and has no way to report it to the containers. Decide with the host link.
3. **Device selection and volume.** The speaker has no output device option, and `ALTextToSpeech.setVolume` is not applied to the audio.
4. **Mixing.** Sound files and speech cannot play at once (the newest stream wins), whereas a real NAO mixes them.
