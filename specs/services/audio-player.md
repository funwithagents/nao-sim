---
code:
tests:
---

# ALAudioPlayer: sound files

**Status:** Draft

## Purpose

`ALAudioPlayer` plays sound files on a NAO: Choregraphe's Play Sound box and every box that embeds it, scripts, and the sound set behind animated speech's `^runSound`/`^startSound`. On the desktop NAOqi it cannot play anything in Docker, so nao-sim makes it play through the audio output ([audio-output.md](../host/audio-output.md)), in two steps: a shim first, a full replacement later.

## Decided

### What the desktop suites ship (measured on 2.1 and 2.8)

- The desktop `ALAudioPlayer` is a stub on both versions: `playFile`, `playFileInLoop`, `playFileFromPosition` (each with a volume and pan overload) and `pause(id)`; no `loadFile`/`play`, `stop(id)`, `stopAll`, `playSine` or sound sets.
- It plays by spawning `/opt/naoqi/bin/sndfile-play <file>` and blocks until that process exits; in Docker the binary fails for lack of a sound device.
- The Choregraphe box library only calls `playFileFromPosition`, `playFileInLoop` and `stop(id)` (the Play Sound File box); animations never touch `ALAudioPlayer`.

### Step 1: the `sndfile-play` shim

- Both images install a script at `/opt/naoqi/bin/sndfile-play` in place of the binary. It decodes the file, streams it to the audio output on `host.docker.internal:9562` with the `play` protocol, and exits when playback ends, so `playFile` blocks for the real duration with no NAOqi change (measured with a sleep stand-in).
- It covers the box library except `stop(id)`, which the stub does not have.

### Step 2: the replacement

A full `ALAudioPlayer` replacement ([service-replacement.md](../container/service-replacement.md), "Replacing a built-in"), for `stop(id)`, `stopAll`, `loadFile`/`play`, `playSine` and the sound sets. It needs speech and sound files to play at once, so it comes with mixing in the audio output.

## Open questions

1. **Formats.** Which formats the shim decodes inside the container (WAV with Python 2.7's `wave`; OGG and MP3, which the robot's sounds use, need a decoder in the image).
2. **Mixing.** How the audio output mixes several streams (speech plus sounds), and whether that moves it onto the host link ([devices.md](../host/devices.md), open question 1). Load-bearing for step 2.
3. **Volume and pan.** The shim receives only the file path, so the volume and pan overloads are ignored in step 1.
4. **Sound set.** Confirm the user's `soundsetaldebaran` installs into the running sim (the package store, [container.md](../container/container.md)) and that `^runSound` finds it once the replacement exists.
