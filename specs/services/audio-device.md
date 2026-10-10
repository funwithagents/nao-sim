---
code:
  - docker/modules/nao_sim_audiodevice_core.py
  - docker/modules/nao_sim_audiodevice_almodule.py
  - docker/modules/nao_sim_audiodevice_qiservice.py
  - docker/relay/naosim_audiorelay.cpp
  - docker/entrypoint-2.1.sh
  - docker/entrypoint-2.8.sh
  - docker/compose.yaml
tests:
  - tests/test_audiodevice_core.py
  - tests/test_entrypoint.py
---

# ALAudioDevice replacement

**Status:** Stable

## Purpose

The desktop NAOqi has no audio input: neither version registers `ALAudioDevice`. An override module ([service-replacement.md](../container/service-replacement.md)) registers one, so clients subscribe to the microphones as on a NAO and receive audio through `processRemote`, from the audio input on the host ([audio-input.md](../host/audio-input.md)). The name is free on both versions, so it is registered directly, with no built-in to remove.

The module routes audio; it does no signal processing. The host produces every format the subscribers ask for, and a small native relay hands each buffer to a subscriber as a binary, as the C++ `ALAudioDevice` of a NAO does ("Delivery").

## Decided

### Modules

- `docker/modules/nao_sim_audiodevice_core.py`: the subscribers, their preferences, the formats they need, the host link client and the delivery threads. Python 2.7, importable under Python 3 so the fast tier tests it on the host, as the speech and status cores are.
- `nao_sim_audiodevice_almodule.py` (2.1, an `ALModule` named `ALAudioDevice`) and `nao_sim_audiodevice_qiservice.py` (2.8, a qi service, `@qi.multiThreaded()`): thin shells per object model.
- `docker/relay/naosim_audiorelay.cpp`: the native relay, one C++ source for both versions ([service-replacement.md](../container/service-replacement.md), "Binary arguments: the native relay").
- Each entrypoint loads the relay, then the module with the other modules, and its readiness check covers both names ([container.md](../container/container.md), "Entrypoint").

### Methods

| Method | Behavior |
| --- | --- |
| `setClientPreferences(name, sampleRate, channels, deinterleaved)` | Stores the format for `name`, taken into account at its next `subscribe` (as NAOqi's documentation says). Without a call, a subscriber gets the default: 48 kHz, all channels, interleaved |
| `subscribe(name)` | Starts delivering to the service `name` (a module or a service a client registered). `name` must exist: a name no service holds raises (on 2.8 after waiting up to 3 s for it, see "As measured"). Subscribing a name already subscribed is a no-op |
| `unsubscribe(name)` | Stops delivering to it; an unknown name is a no-op |
| `enableEnergyComputation()`, `disableEnergyComputation()` | Energy is computed only while enabled, with or without subscribers |
| `getFrontMicEnergy()`, `getRearMicEnergy()`, `getLeftMicEnergy()`, `getRightMicEnergy()` | The last energy the host computed for that microphone, in [0, 32768]; `0.0` while disabled |
| `openAudioInputs()`, `closeAudioInputs()` | No-ops: capture follows the subscribers |
| `isInputMuted()` | Always `false`: the microphone gate is invisible to NAOqi ([audio-input.md](../host/audio-input.md), "Microphone gate") |
| `getOutputVolume()`, `setOutputVolume(volume)` | The value (0 to 100, initially 50) is kept and returned (open question 2) |

### Preferences, as NAOqi's device

The formats are those of NAOqi's documentation (the 2.1 suite's offline docs, `alaudiodevice.txt` and `alaudiodevice-api.txt`):

- `sampleRate` is 16000 or 48000. `channels` is NAOqi's channel constant, not a count: `0` all channels (`ALLCHANNELS`), `1` left, `2` right, `3` front, `4` rear.
- 48 kHz takes all channels, interleaved or deinterleaved (`deinterleaved` = 1: the buffer holds each channel's samples one channel after the other, in the order left, right, front, rear).
- 16 kHz takes one channel, any of the four.
- Any other combination raises, and the stored preferences stay as they were.
- A subscriber's format is a triple (rate, channel, deinterleaved), with channel one of `all`, `left`, `right`, `front`, `rear`. The module asks the host for the set of distinct formats its subscribers need ([audio-input.md](../host/audio-input.md), "On the host link"), and routes each `pcm` message to the subscribers of that format, unchanged.

### Delivery

- The module holds the host link connection ([devices.md](../host/devices.md), "The host link"), at the address the compose service gives it (`NAO_SIM_HOST_LINK`, `host.docker.internal:9563`). It retries every second while the host is absent, logging only the first failure, and sends its current need again after each reconnect.
- **Each subscriber has its own delivery thread** with a queue of 4 buffers: the link thread never waits on a subscriber, and a slow subscriber costs only itself. When the queue is full the oldest buffer is dropped, logged once per run of drops.
- **Through the native relay.** The delivery thread calls `_NaoSimAudioRelay.deliver(name, nbOfChannels, nbOfSamplesByChannel, timeStamp, buffer)` with the PCM as a Python string; the relay calls the subscriber's `processRemote(nbOfChannels, nbOfSamplesByChannel, timeStamp, buffer)` with the buffer as a binary, so a libqi 3 client receives a `bytearray` as from a NAO. 2.1 reaches the relay with `naoqi.ALProxy`, 2.8 through the module's own `qi.Session` (both measured, see "As measured").
- **Timestamps.** Each buffer is stamped on arrival in the container, `[seconds, microseconds]` of the container's clock, since `processRemote`'s `timeStamp` is the robot's time, comparable to NAOqi's other timestamps.
- **A subscriber that goes away.** Three consecutive failed deliveries to a name spanning at least 2 s (a client disconnected without unsubscribing) unsubscribe it, logged, and the relay is told to forget its proxy. The 2 s keep a new subscriber that the relay cannot reach yet (2.8, "As measured") from being dropped.
- **No host source.** With no host link, or while the host has no source (`NaoSim/Audio/Source` is `none`), subscriptions are accepted and nothing is delivered.

### Chunks

The host cuts the buffers ([audio-input.md](../host/audio-input.md), "Chunks"); the module passes them on as they come. Provisionally 4096 samples per channel at 48 kHz and 1365 at 16 kHz (about 85 ms), the values clients report from NAO robots; the 2.1 docs say 170 ms (open question 1).

## As measured

Oct 10, 2026, both versions, a libqi 3 host client registering a service with `processRemote` (`spike/RESULTS.md`, "Audio input: host callbacks, binary buffers, the native relay"):

- **Callbacks reach the host on both versions**: 2.1 through the broker, 2.8 through the gateway from the module's own session. A call costs 0.4 to 1.3 ms per chunk.
- **Python 2.7 cannot send a binary** on either version: `str` and `bytearray` travel as a qi string (the host gets a `str`, mangled when not UTF-8, so `bytes(inputBuffer)` fails), and `ALProxy` turns a `bytearray` into `None`. A C++ `ALValue` binary arrives as a `bytearray`. Hence the relay.
- **Through the relay**, both versions: the host receives a `bytearray` with the exact bytes and the timestamp sent, from `ALProxy` (2.1) and a qi session (2.8). A 48 kHz four-channel chunk (8192 samples) costs 0.74 ms on 2.1 and 1.28 ms on 2.8.
- **2.8: a client's service reaches the container a moment late.** A client registers its service and subscribes at once; through the gateway, the module's session may not find the name yet (`session.service` fails for a moment), and `session.services()` never lists it. So on 2.8, `subscribe` asks for the service directly, retrying for up to 3 s (measured with the live tier: intermittent failures without the retry, none with it). 2.1, through the broker, finds it at once.

## Open questions

1. **Chunk size and cadence.** The samples per `processRemote` a NAO delivers are the reference: about 85 ms as reported by clients, 170 ms in the 2.1 docs. To measure on a robot; a constant on the host ([audio-input.md](../host/audio-input.md), open question 1).
2. **Output volume and output buffers.** Whether `setOutputVolume` drives the audio output's volume ([audio-output.md](../host/audio-output.md), open question 1), and whether `sendRemoteBufferToOutput` (a client playing its own PCM through the robot) is served, by streaming to the audio output.
3. **Other methods and formats.** The rest of the NAO's `ALAudioDevice` (`setParameter`, `muteAudioOut`, `flushAudioOutputs`, `setFileAsInput`, recording through `ALAudioRecorder`), and four channels at 16 kHz, which later NAOqi versions may accept, are out of v1 unless a client needs them.
