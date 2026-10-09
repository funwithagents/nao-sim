---
code:
tests:
---

# ALAudioDevice replacement

**Status:** Draft

## Purpose

The desktop NAOqi has no audio input: neither version registers `ALAudioDevice`. An override module ([service-replacement.md](../container/service-replacement.md)) registers one, so clients subscribe to the microphones as on a NAO and receive audio through `processRemote`, from the audio input on the host ([audio-input.md](../host/audio-input.md)). The name is free on both versions, so it is registered directly, with no built-in to remove.

## Decided

### Modules

`docker/modules/nao_sim_audiodevice_core.py` (Python 2.7, importable under Python 3 so the fast tier tests it on the host), with `nao_sim_audiodevice_almodule.py` (2.1) and `nao_sim_audiodevice_qiservice.py` (2.8) as thin shells per object model, as the speech and status modules are. Each entrypoint loads it with the other modules ([container.md](../container/container.md), "Entrypoint"), and the readiness check covers it.

### Methods

- `subscribe(name)`, `unsubscribe(name)`, `setClientPreferences(name, sampleRate, channels, deinterleaved)`.
- `openAudioInputs`, `closeAudioInputs`, `isInputMuted` (always `false`: the microphone gate is invisible to NAOqi, [audio-input.md](../host/audio-input.md)).
- `enableEnergyComputation`, `disableEnergyComputation`, `getFrontMicEnergy`, `getRearMicEnergy`, `getLeftMicEnergy`, `getRightMicEnergy`: computed from the PCM received (RMS per channel over the last chunk) while enabled.
- `getOutputVolume`, `setOutputVolume`: the value is kept and returned (see open question 3).

### Preferences, as NAOqi's device

- 48 kHz with all 4 channels, or 16 kHz with all 4 channels or one (the front microphone); any other combination is refused as NAOqi refuses it.
- Several subscribers may ask for different formats; the module asks the host for the richest one needed and derives each subscriber's own from it (dropping channels, or decimating 48 kHz to 16 kHz).

### Delivery

- The module holds the host link connection ([devices.md](../host/devices.md), "The host link") and sends `subscribe`/`unsubscribe` as its subscribers change ([audio-input.md](../host/audio-input.md), "On the host link").
- Each `pcm` chunk is delivered to each subscriber's `processRemote(nbOfChannels, nbOfSamplesByChannel, timeStamp, buffer)`, interleaved 16-bit samples, stamped with the container's clock on arrival.
- The call goes through the broker, `naoqi.ALProxy(subscriber)`, which reaches a host subscriber over the socket the host opened. Verified on 2.1; a module's own `qi.Session` cannot reach it ([service-replacement.md](../container/service-replacement.md), "Calling services registered on the host").
- With no host source (`NaoSim/Audio/Source` is `none`), subscriptions are accepted and nothing is delivered.

## Open questions

1. **Callbacks on 2.8.** Reaching a host subscriber from inside the container through the gateway is expected to work as on 2.1 and is to confirm ([service-replacement.md](../container/service-replacement.md), open question 1). Load-bearing: this spec cannot be `Stable` before it is measured.
2. **Chunk size and cadence.** The samples per `processRemote` a NAO delivers are the reference ([audio-input.md](../host/audio-input.md), open question 1).
3. **Output volume and output buffers.** Whether `setOutputVolume` drives the audio output's volume ([audio-output.md](../host/audio-output.md), open question 1), and whether `sendRemoteBufferToOutput` (a client playing its own PCM through the robot) is served, by streaming to the audio output.
4. **Other methods.** The rest of the NAO's `ALAudioDevice` (`setParameter`, `muteAudioOut`, recording to a file through `ALAudioRecorder`) is out of v1 unless a client needs it.
