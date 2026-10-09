---
code:
tests:
---

# Audio input

**Status:** Draft

## Purpose

The robot's microphones as a host device ([devices.md](devices.md)). It feeds the `ALAudioDevice` replacement ([audio-device.md](../services/audio-device.md)) with PCM over the host link, so a client that subscribes to `ALAudioDevice` gets microphone audio through `processRemote` as on a NAO. Speech recognition and sound processing run in the clients on that stream, never in nao-sim ([_overview.md](../_overview.md), "Perception and speech recognition").

It also holds the **microphone gate**: the robot does not hear its own voice.

## Decided

### Sources

The `audio_input` block of [config.md](../runtime/config.md) picks one:

| `source` | Audio | Built |
| --- | --- | --- |
| `none` (default) | Nothing: `ALAudioDevice` accepts subscriptions and delivers nothing; `NaoSim/Audio/Source` stays `none` | — |
| `wav` | A WAV file, `audio_input.wav` | First: the only source CI can test |
| `mic` | The host's default input device | After `wav` |

- **WAV replay.** 16-bit PCM, mono or 4-channel, at 16 or 48 kHz; any other format fails `NaoSim.start()` naming the file. The file starts from its beginning at the first subscription, plays once in real time, then the input delivers silence, so a test knows where its audio starts. A 4-channel file maps its channels in NAO order: left, right, front, rear.
- **Host microphone.** Captured with `sounddevice` (`RawInputStream`, int16) at 48 kHz from the default input device, mono, opened only while `ALAudioDevice` has subscribers. Off unless the config says `mic`, with the indicator of [devices.md](devices.md) ("Off unless asked") while it captures.

### Format, channels and the mono policy

- The host delivers exactly what the container side asks for in its `subscribe` message (see "On the host link"): 48 kHz with 4 channels, or 16 kHz with 4 channels or 1. The host converts: it resamples, and it spreads or picks channels. The Python 2.7 side does no signal processing.
- **Mono policy** (`audio_input.mono`) for a mono source asked for 4 channels: `duplicate` (default) copies it to every channel, `silence` puts it on the front channel and zeros on the others. A 4-channel WAV is `native`.
- The device publishes its source as `NaoSim/Audio/Source` (`wav`, `mic`) and the channel policy as `NaoSim/Audio/Channels` (`duplicate`, `silence`, `native`) when it starts, and `none` for both when it stops ([status-service.md](../container/status-service.md), "ALMemory keys").

### Microphone gate

The host has the microphone and the exact audio the robot plays, on one clock, so it keeps the robot from hearing itself without involving NAOqi:

- While `time.monotonic()` is before the audio output's `playing_until` ([audio-output.md](audio-output.md), "Playing state") plus a tail, the input sends **zeros** in place of the captured samples. The chunks keep coming at their cadence, so subscribers see silence, not a gap.
- The tail is `audio_input.gate_tail_s`, 0.3 s by default; 0 still gates while playing.
- The gate applies to the `mic` source. A `wav` source is not gated: a test replays a known file and expects it whole.
- Nothing about the gate crosses the host link: the container side never learns the robot is speaking.

### On the host link

The audio input's messages on the host link ([devices.md](devices.md), "The host link"), from the `ALAudioDevice` service (`hello {"service": "ALAudioDevice"}`):

| Type | Direction | Header | Payload |
| --- | --- | --- | --- |
| `subscribe` | container → host | `rate` (16000, 48000), `channels` (1, 4), `samples` (per channel per chunk) | — |
| `unsubscribe` | container → host | — | — |
| `pcm` | host → container | `rate`, `channels`, `samples` | Interleaved s16le |

- `subscribe` is sent whenever the format the subscribers need changes, and again after a reconnect; `unsubscribe` when the last subscriber leaves. The host captures (or advances the WAV) only between the two.
- The host paces `pcm` chunks in real time. The container stamps each chunk with its own clock on arrival, since `processRemote`'s `timeStamp` is the robot's time, comparable to NAOqi's other timestamps.

## Open questions

1. **Chunk size and cadence.** The `samples` a NAO delivers per `processRemote` (per rate and channel count) are the reference to match; values are still to be supplied from a real robot.
2. **Microphone selection.** No option picks an input device other than the default; decide with the audio output's device selection ([audio-output.md](audio-output.md), open question 1).
3. **Echo cancellation.** The gate is the default. Real cancellation is possible later for the same reason the gate is: the host has both signals on one clock.
4. **WAV looping and restart.** Whether a WAV restarts at each new subscription or can loop, for longer tests.
