---
code:
  - src/nao_sim/config.py
  - src/nao_sim/sim.py
  - src/nao_sim/audio_input.py
  - src/nao_sim/host_link.py
tests:
  - tests/test_config.py
  - tests/test_audio_input.py
  - tests/test_sim.py
  - tests-e2e/test_audio_input_live.py
  - tests-e2e/test_audio_loopback_live.py
---

# Audio input

**Status:** Implemented

## Purpose

The robot's microphones as a host device ([devices.md](devices.md)). It feeds the `ALAudioDevice` replacement ([audio-device.md](../services/audio-device.md)) with PCM over the host link, so a client that subscribes to `ALAudioDevice` gets microphone audio through `processRemote` as on a NAO. Speech recognition and sound processing run in the clients on that stream, never in nao-sim ([_overview.md](../_overview.md), "Perception and speech recognition").

It also holds the **microphone gate**: the robot does not hear its own voice.

## Decided

### Module

`src/nao_sim/audio_input.py`, class `AudioInput`, run in-process by a `NaoSim` ([api.md](../runtime/api.md)); config block `audio_input` ([config.md](../runtime/config.md)). The host link it is served on is `src/nao_sim/host_link.py` ([devices.md](devices.md), "The host link").

### Sources

The `audio_input` block picks one:

| `source` | Audio |
| --- | --- |
| `none` (default) | Nothing: the host link is not opened, `ALAudioDevice` accepts subscriptions and delivers nothing, `NaoSim/Audio/Source` stays `none` |
| `fake` | A quiet room in which code plays sounds: silence, plus what a test (or nao-bridge's `sim` backend) plays through `NaoSim.fake_audio`. The source CI tests on every run |
| `mic` | The host's default input device |

#### The fake source

`FakeAudioSource`, reached as `sim.fake_audio` on a running `NaoSim` whose source is `fake` (any other source raises `NaoSimError`). It is the input side's counterpart of the audio output's `MemorySink`: the test decides what the robot hears and when.

```python
take = sim.fake_audio.play("hello.wav")            # or play(samples, rate=16000)
take.wait(timeout=5)                               # take.started_at, take.ended_at
sim.fake_audio.stop()                              # every sound playing now
```

- **Silence until told otherwise.** Subscribers get zero chunks at the normal cadence, as from a quiet room.
- **`play(sound, rate=None)`** starts the sound at once and returns a `Take` (`started_at`, `ended_at`, both `time.monotonic()`; `done`; `wait(timeout)`). `sound` is a WAV path (16-bit PCM, mono or 4-channel, 16 or 48 kHz) or a `numpy` int16 array (`(n,)` mono or `(n, 4)` in NAO order: left, right, front, rear) with its `rate` (16000 or 48000). Any other format raises `ValueError` at the call, naming the problem.
- **Sounds overlap and mix**, as in a room: samples are summed and clipped to int16.
- **Wall-clock time.** A sound plays from the moment `play` is called, whether or not anybody subscribes: a subscriber that arrives mid-sound hears the rest, and one played while nobody listens goes unheard. `ended_at` is when its last sample is due.
- **Split files.** A test plays one part, has the robot act, then plays the next: the timing is the test's.
- **It stands in for the microphone**, so the microphone gate applies to it ("Microphone gate"): a sound played while the robot speaks reaches subscribers as zeros, as it would on a NAO whose gate is the host's.
- `play` is thread-safe and may be called from any thread or before a subscription; `stop()` ends every sound playing (their `ended_at` becomes now).

#### The host microphone

Captured with `sounddevice` (`RawInputStream`, int16, mono, 48 kHz, blocks of 10 ms) from the default input device, opened only while the container side needs audio and closed when it needs none. `NaoSim.start()` checks at step 1 that `sounddevice` imports (PortAudio is present) and that a default input device exists, failing with `DeviceUnavailableError` otherwise. While it captures, the input logs at info level that the microphone is live, and that it is off when it closes: the terminal indicator of [devices.md](devices.md) ("Off unless asked"). An indicator in the sim window waits for nao-viewer to offer one.

### Formats, channels and the mono policy

- **The host produces every format the container side asks for**, and the Python 2.7 side does no signal processing: the need message lists formats (rate, channel, deinterleaved), as [audio-device.md](../services/audio-device.md) ("Preferences, as NAOqi's device") defines them, and the host sends one `pcm` stream per format.
- **Resampling** between 16 and 48 kHz is by a factor of 3, with a windowed-sinc low-pass filter (`numpy`), applied continuously across chunks so a stream has no seams.
- **Channels.** The source becomes four channels (left, right, front, rear); a format with one channel takes that microphone's channel; a deinterleaved format lays the four channels one after the other.
- **Mono policy** (`audio_input.mono`) for mono audio (the `mic`, a mono sound played on the fake source): `duplicate` (default) copies it to every channel, `silence` puts it on the front channel and zeros on the others. A 4-channel sound keeps its channels.
- The device publishes its source as `NaoSim/Audio/Source` (`fake`, `mic`) and the mono policy as `NaoSim/Audio/Channels` (`duplicate`, `silence`) when it starts, and `none` for both when it stops ([status-service.md](../container/status-service.md), "ALMemory keys").

### Chunks

- Each format's stream is cut in chunks of a fixed number of samples per channel: **4096 at 48 kHz, 1365 at 16 kHz** (about 85 ms), the values clients report from NAO robots; provisional (open question 1), one constant per rate in `audio_input.py`.
- **Real time.** Each stream is paced on its own sample clock: chunk `k` is sent when its last sample is due, `t0 + (k + 1) × samples / rate` after the stream starts, never in bursts; a late slot is sent at once and the schedule kept, not reset.
- **Energy.** When the need asks for it, the host computes each microphone's energy, the RMS of the 48 kHz four-channel signal over the last 4096 samples, in [0, 32768], and sends it on that cadence.

### Microphone gate

The host has the microphone and the exact audio the robot plays, on one clock, so it keeps the robot from hearing itself without involving NAOqi:

- While `time.monotonic()` is before the audio output's `playing_until` ([audio-output.md](audio-output.md), "Playing state") plus a tail, the input replaces the captured samples with **zeros**, decided per captured 10 ms block. The chunks keep coming at their cadence, so subscribers see silence, not a gap.
- The tail is `audio_input.gate_tail_s`, 0.3 s by default; it also covers the output device's latency, from the audio output's last write to the sound in the room. The `DevicePlayer` and the microphone open their streams at low latency (`latency="low"`) to keep that short. 0 still gates while playing.
- The gate applies to both sources, `mic` and `fake`: the fake source stands in for the microphone, so the gate is tested on every live run and not only over a real loopback.
- Nothing about the gate crosses the host link: the container side never learns the robot is speaking.

### On the host link

The audio input's messages on the host link ([devices.md](devices.md), "The host link"), from the `ALAudioDevice` service (`hello {"service": "ALAudioDevice"}`):

| Type | Direction | Header | Payload |
| --- | --- | --- | --- |
| `need` | container → host | `formats`: a list of `{"rate": 16000 \| 48000, "channel": "all" \| "left" \| "right" \| "front" \| "rear", "deinterleaved": bool}`; `energy`: bool | — |
| `pcm` | host → container | `format` (as in `need`), `channels` (1 or 4), `samples` (per channel) | s16le, interleaved or deinterleaved as the format says |
| `energy` | host → container | `left`, `right`, `front`, `rear` (floats) | — |

- `need` is sent whenever the set of formats or the energy flag changes, and again after every reconnect; `{"formats": [], "energy": false}` means nothing is needed. The host opens the microphone only while something is needed; the fake source's sounds run on the wall clock either way.
- A `need` that arrives before the device has started (step 6 of `NaoSim.start()`) is kept and served once it starts.
- The container stamps each chunk with its own clock on arrival ([audio-device.md](../services/audio-device.md), "Delivery").

### In the live tier and CI

- **Every live run uses the fake source.** The live tier's config has `audio_input = {source: "fake"}`, so `ALAudioDevice` and the gate are exercised on every run of both versions: a test subscribes as a client does, plays tones through `sim.fake_audio` and checks what it receives against them.
- **The loopback tests** use a real device: the `mic` source, the gate with the robot's speech played by a `DevicePlayer` and coming back into the microphone, and the `DevicePlayer` itself. They run only when the default output and input devices form a loopback, which `NAO_SIM_E2E_AUDIO=loopback` declares; without it they skip, since playing into a user's loudspeakers and recording their microphone is not acceptable by default. CI's live entries provide the loopback (a PulseAudio null sink as the default sink, its monitor as the default source) and set the variable, so there they cannot skip ([ci.md](../testing/ci.md)).

## Open questions

1. **Chunk size and cadence.** The `samples` a NAO delivers per `processRemote` are the reference: about 85 ms as clients report, 170 ms in the 2.1 docs. To measure on a robot; one constant per rate.
2. **Microphone selection.** No option picks an input device other than the default; decided with the audio output's device selection ([audio-output.md](audio-output.md), open question 1).
3. **Output latency beyond the tail.** A device that buffers more than the tail lets the robot hear the end of its own voice. Measured on CI: a PulseAudio null sink with no low-latency client renders about 1.5 s late, whatever PortAudio asks for, so CI keeps one ([ci.md](../testing/ci.md)); real loudspeakers measured so far are well under the tail. Reading the device's reported latency into `playing_until` waits for a host that needs it.
4. **Echo cancellation.** The gate is the default. Real cancellation is possible later for the same reason the gate is: the host has both signals on one clock.
5. **Replaying a file from the config.** `nao-sim run` has no way to feed a recording (the fake source is driven from code); a CLI option or a `fake` setting that plays a file at the first subscription waits for a user who needs it.
