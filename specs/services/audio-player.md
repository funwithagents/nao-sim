---
code:
  - docker/naoqi/services/audio-player/naoqi_sim_audio_player_front.cpp
  - docker/naoqi/services/audio-player/naoqi_sim_audio_player_core.py
  - docker/naoqi/services/audio-player/naoqi_sim_audio_player_almodule.py
  - docker/naoqi/services/audio-player/naoqi_sim_audio_player_qiservice.py
  - docker/naoqi/services/naoqi_sim_front_core.h
  - docker/naoqi/entrypoint-2.1.sh
  - docker/naoqi/entrypoint-2.8.sh
  - docker/naoqi/entrypoint-lib.sh
  - docker/naoqi/Dockerfile.naoqi-2.1
  - docker/naoqi/Dockerfile.naoqi-2.8
  - docker/compose.yaml
  - src/naoqi_sim/audio_output.py
tests:
  - tests/test_audio_player_core.py
  - tests/test_entrypoint.py
  - tests-e2e/test_audio_player_live.py
---

# ALAudioPlayer replacement

**Status:** Implemented

## Purpose

`ALAudioPlayer` plays sound files on a NAO: Choregraphe's Play Sound box and every box that embeds it, scripts, and the sound set behind animated speech's `^runSound`/`^startSound`. On the desktop NAOqi it cannot play anything in Docker, so naoqi-sim replaces it ([service-replacement.md](../container/service-replacement.md), "Replacing a built-in") with a module that behaves like a NAO's: files and speech play at once, mixed by the audio output ([audio-output.md](../host/audio-output.md), "Mixing"), with per-task volume and pan, `stop(id)`, loops and sound sets.

The aim is a NAO's architecture, not only its API. On a NAO, `ALAudioPlayer` and `ALTextToSpeech` are two clients of the robot's sound server, which mixes every stream into the one stereo output of the ear loudspeakers, and the microphones hear that mix. In naoqi-sim the replacement and the `tts` engine are the clients, and the audio output plays the sound server.

## Decided

### What the desktop suites ship (measured on 2.1 and 2.8)

- The desktop `ALAudioPlayer` is a stub on both versions: `playFile`, `playFileInLoop`, `playFileFromPosition` (each with a volume and pan overload) and `pause(id)`; no `loadFile`/`play`, `stop(id)`, `stopAll`, `playSine` or sound sets.
- It plays by spawning `/opt/naoqi/bin/sndfile-play <file>` and blocks until that process exits; in Docker the binary fails for lack of a sound device. It passes only the path, so it could not apply a volume or a pan even with a working device.
- It lives in the `audioout` library with `ALTextToSpeech`, which is already replaced.

### No shim: straight to the replacement

A script standing in for `sndfile-play` would make `playFile` play, but it receives only the path: no volume, no pan, no `stop(id)`, nothing to stop a loop with, and every file at full volume. That is not how a NAO behaves, so naoqi-sim skips it and replaces the service directly.

### The contract: a NAO's API

The methods are those of the 2.1 offline docs shipped in the suite (`share/doc/_sources/naoqi/audio/alaudioplayer-api.txt`):

| Group | Methods |
| --- | --- |
| Files | `playFile`, `playFileInLoop`, `playFileFromPosition`, each with and without `(volume, pan)` |
| Loaded files | `loadFile` (returns a task id), `play`, `playInLoop` (with and without `(volume, pan)`), `pause`, `goTo`, `getCurrentPosition`, `getFileLength`, `unloadFile`, `unloadAllFiles`, `getLoadedFilesIds`, `getLoadedFilesNames` |
| Volume and pan | `setVolume(id, v)`, `getVolume(id)`, `setMasterVolume`, `getMasterVolume`, `setPanorama` |
| Stop | `stop(id)`, `stopAll` |
| Sound sets | `loadSoundSet`, `unloadSoundSet`, `playSoundSetFile` (three overloads), `getInstalledSoundSetsList`, `getLoadedSoundSetsList`, `getSoundSetFileNames`, `isSoundSetInstalled`, `isSoundSetLoaded`, `isSoundSetFileInstalled` |
| Synthesis | `playSine(frequence, gain, pan, duration)` |

- Volume is in [0.0, 1.0] and pan in [-1.0 left, 1.0 right], as documented; the task volume is independent of the master volume, and both multiply.
- `playWebStream` raises "not supported": a sim has no reason to fetch internet radio (open question 4).

### Architecture: a C++ front and a Python core

Choregraphe's Play Sound box starts a sound with `id = player.post.playFileFromPosition(...)`, waits with `player.wait(id, 0)` and stops it with `ALProxy('ALAudioPlayer', True).stop(id)` (2.1); 2.8's does the same with qi: `pCall("playFileFromPosition", ...)`, `wait(id)`, `stop(id)`. Only a C++ `ALModule` can honour that `stop(id)`, on both versions (measured Oct 12, 2026; [service-replacement.md](../container/service-replacement.md), "Task ids, `wait` and `stop(id)`: a C++ front"). So the replacement is split:

- **`ALAudioPlayer`, the C++ front** (`docker/naoqi/services/audio-player/naoqi_sim_audio_player_front.cpp`, one source for both versions, built in the native build stage and loaded with `launchLocal`, on the pattern of the speech front built first, [speech.md](speech.md), "Architecture"): every method of the contract below, each forwarding to the core. A play method takes its task id with `getMethodID()` (or a new one from the core when called blocking), starts the playback in the core and polls every 20 ms until the core reports it done, calling the core's `stop(id)` when `isStopRequired(id)` turns true.
- **`_NaoqiSimAudioPlayer`, the Python 2.7 core**: decoding, task ids for loaded files, volumes, sound sets, and the streams to the audio output. `docker/naoqi/services/audio-player/naoqi_sim_audio_player_core.py`, importable under Python 3 so the fast tier tests it on the host, with the thin shells `naoqi_sim_audio_player_almodule.py` (2.1) and `naoqi_sim_audio_player_qiservice.py` (2.8).
- **Boot:** the entrypoints remove the built-in (`ALAudioPlayer.exit()`, step 2 of "Replacing a built-in"), load the core with the other Python modules, then the front, and check both names answer. The front also serves `stop(id)` and `wait(id, timeout)` for the Say-box pattern and every script that copies it.
- **The audio output's address** reaches the NAOqi container as it reaches the `tts` container (`NAOQI_SIM_SOUNDCARD=host.docker.internal:9562` in compose).

- **Long calls as a kind and parameters.** The front starts a play in the core with `start(id, kind, params)`: `kind` is `file`, `loaded`, `soundset` or `sine`, and `params` the call's arguments as a JSON object (`path`, `position`, `volume`, `pan`, `loop`, `id`, `set`, `file`, `frequency`, `gain`, `duration`), so every overload crosses with the same three typed arguments; then `waitDone(id, 20)` and `stopCall(id)` as the speech front does. The `Core` wrapper both fronts use (ALProxy on 2.1, a qi object on 2.8) is the shared `docker/naoqi/services/naoqi_sim_front_core.h`.
- **Ids.** Loaded files and blocking calls get ids from the core, from 1 000 000, above any task id the broker hands out; `getLoadedFilesIds` returns them as strings, as documented. `stopCall`, `pause`, `goTo`, `getCurrentPosition`, `getFileLength`, `setVolume` and `getVolume` take a task id or a loaded file's id. `play(id)` of a paused loaded file resumes it, and that call waits for the same playback.

### Formats: the suite's own decoder

- Aldebaran's docs say it: *"On a virtual robot, ALAudioPlayer can play OGG and WAV files but not MP3."* A robot decodes with GStreamer and libsndfile; the desktop suites ship libsndfile only.
- The replacement decodes with that same library, libsndfile 1.0.25 (OGG/Vorbis, FLAC, WAV), already in both images under `/opt/naoqi/lib`, through the suite's `sndfile-convert`. Measured on Oct 12, 2026: `hey6.ogg` from the `animations` package (48 kHz stereo) decodes on 2.1 and 2.8; an MP3 is refused ("unknown format").
- A 16-bit PCM WAV is read directly (Python's `wave`); everything else goes through `sndfile-convert -pcm16` to a temporary WAV. An MP3 raises with libsndfile's message ("unknown format"), as on a virtual robot. No ffmpeg, sox or other decoder is added to the images.

### Sound sets

- A sound set is an installed package named `soundset<name>` in the package store (`/home/nao/.local/share/PackageManager/apps/`, `NAOQI_SIM_APPS`): `soundsetaldebaran` is the set `Aldebaran`, as the docs load it (`loadSoundSet("Aldebaran")`). Its sounds are the `.ogg`/`.wav`/`.flac` files at the package's root (the layout of `soundsetaldebaran-1019.pkg`), named without their extension; names are matched case-insensitively.
- `playSoundSetFile(file)` plays from any loaded set; the other overloads name the set.

### Playing into the audio output

- Each playback task is its own stream of the audio output, named `player:<id>`, with its file's rate and channels, its task volume times the master volume, and its pan ([audio-output.md](../host/audio-output.md), "Streams" and "Mixing"). Speech is the `speech` stream, so a sound and a sentence play together.
- `setVolume`, `setMasterVolume` and `setPanorama` act on the streams already playing, through the audio output's `set` command; `pause`/`play` of a loaded file through `pause`/`resume`; `stop(id)` and `stopAll` stop their streams and no other (speech goes on).
- A blocking call returns when the audio output has played the stream to its end, or when it is stopped, as the stub's `playFile` does.

### Tests

The fast tier tests the module's core on the host, as for the speech and audio device cores; the live tier runs on 2.1 and 2.8 with a `MemorySink`:

- `playFile` blocks for the file's duration and its PCM reaches the sink, for WAV and OGG; an MP3 raises.
- Volume and pan scale the left and right channels as asked; `setVolume` and `setMasterVolume` change a stream while it plays.
- `playFileInLoop` keeps playing until `stop(id)`; `stopAll` stops every sound and not the speech.
- `loadFile`/`play`/`pause`/`goTo`/`getCurrentPosition`/`getFileLength` on a loaded file.
- A sound played during `say()`: both are heard in the mix and neither is cut.
- The Play Sound box's own calls: `post`, `wait(id, 0)`, and `stop(id)` from a second proxy ending that sound only.
- `playSine`, and the sound set calls with a sound set installed.

## Open questions

Deferrals; none changes the design.

1. **Dependents.** The modules known to call `ALAudioPlayer` (`ALAnimatedSpeech` for sound tags, `ALDialog`) load after the front on both versions, which takes the built-in's place in NAOqi's boot ([service-replacement.md](../container/service-replacement.md), "Replacing a built-in"), so no module holds a proxy to a built-in; boxes and scripts make their proxies when they run.
2. **Sound tags.** The user's `soundsetaldebaran` installs into a running sim (measured on both versions) and the core finds it by its package name ("Sound sets"), but it is not in the robot images, so it stays user-supplied ([container.md](../container/container.md)) and the live tier skips its test without it. That `ALAnimatedSpeech`'s `^runSound` reaches the replacement is to confirm with the set installed.
3. ~~**Loaded-file ids.**~~ Closed: a real NAO 2.1 accepts both (measured Oct 16, 2026, inside the robot's NAOqi): `stop(loaded file id)` and `stop(task id of the posted play)` each stop the sound, `isRunning(task id)` turns false and `wait(task id, 0)` returns at once, as the core does. The robot also ships 44 system sounds in `/usr/share/naoqi/wav` and the user's `Aldebaran` sound set has 1775 files (prefixes `amb_`, `bidi_`, `enu_`, `frf_`, `jpj_`, `sfx_`), listed by `getSoundSetFileNames` without loading the set.
4. **Web streams.** Whether `playWebStream` should play an HTTP stream through libsndfile's formats rather than raise; no known caller needs it.
