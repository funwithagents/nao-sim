---
code:
  - src/nao_sim/config.py
  - docker/compose.yaml
  - examples/configs/default.json
  - examples/configs/2.8.json
  - examples/configs/headless.json
tests:
  - tests/test_config.py
  - tests/test_project_map.py
---

# Configuration

**Status:** Implemented

## Purpose

One declarative description of *which simulated NAO to run and which devices to attach to it*. A [`NaoSim`](api.md) is built from it, the `nao-sim` CLI loads it from a file, and nao-bridge's `sim` backend embeds it. Today the same facts are spread over `docker compose` profiles, environment variables (`NAO_SIM_VERSION`, `NAO_SIM_TTS_ENGINE`) and the audio output's flags; a config file makes a setup reproducible and lets a test, a CLI user and nao-bridge describe the same stack the same way.

It follows nao-bridge's configuration conventions on purpose (its `specs/config.md`), so the two packages' files look alike and a nao-sim config can be pasted into a nao-bridge one unchanged.

This config is the **host-level** description. The container keeps its own interface, the entrypoint's environment variables ([container.md](../container/container.md), "Entrypoint"); `NaoSim` generates the compose environment from the config, and nobody writes those variables by hand any more.

## Decided

### `NaoSimConfig`: top-level structure

```json
{
  "naoqi": { "version": "2.1", "ready_timeout_s": 240 },
  "speech": { "engine": "piper" },
  "audio_output": { "mode": "play", "record": null },
  "audio_input": { "source": "none", "wav": null, "mono": "duplicate", "gate_tail_s": 0.3 },
  "video_input": { "source": "none", "device": 0 },
  "viewer": { "headless": false, "scene": "empty", "variant": "auto" }
}
```

```python
@dataclass
class NaoSimConfig:
    naoqi: NaoqiSettings = field(default_factory=NaoqiSettings)
    speech: SpeechSettings = field(default_factory=SpeechSettings)
    audio_output: AudioOutputSettings = field(default_factory=AudioOutputSettings)
    audio_input: AudioInputSettings = field(default_factory=AudioInputSettings)
    video_input: VideoInputSettings = field(default_factory=VideoInputSettings)
    viewer: ViewerSettings = field(default_factory=ViewerSettings)


@dataclass
class NaoqiSettings:
    # "2.1" | "2.8"
    version: NaoqiVersion = "2.1"
    # start() waits this long for the container to be healthy
    ready_timeout_s: float = 240.0


@dataclass
class SpeechSettings:
    # "piper" | "espeak" (the tts container's NAO_SIM_TTS_ENGINE)
    engine: SpeechEngine = "piper"


@dataclass
class AudioOutputSettings:
    """The audio output (audio-output.md)."""

    # "play" | "silent" | "record"
    mode: AudioOutputMode = "play"
    # WAV file, required by "record"
    record: Path | None = None


@dataclass
class AudioInputSettings:
    """The audio input, feeding the ALAudioDevice replacement (audio-input.md)."""

    # "none" | "mic" | "wav"
    source: AudioInputSource = "none"
    # required by "wav"
    wav: Path | None = None
    # "duplicate" | "silence", published as NaoSim/Audio/Channels
    mono: MonoPolicy = "duplicate"
    # the microphone gate's tail after the robot's audio ends, in seconds
    gate_tail_s: float = 0.3


@dataclass
class VideoInputSettings:
    """The video input, injected into ALVideoDevice (video-input.md)."""

    # "none" | "render" | "webcam"
    source: VideoInputSource = "none"
    # webcam index, used by "webcam"
    device: int = 0


@dataclass
class ViewerSettings:
    """The simulated world (nao-viewer sim mode)."""

    headless: bool = False
    # a bundled scene name ("empty", "table") or a path to an MJCF file
    scene: str = "empty"
    # "auto" | "placeholder" | "aldebaran" (nao-viewer's world.variant)
    variant: ViewerVariant = "auto"
```

- Every block is optional. Missing blocks and fields take the defaults above. **A default is declared once**, on the dataclass field; the loaders read it from there (`dataclasses.fields`), so a default cannot drift between direct construction and JSON.
- **The device blocks are named after the device** ([devices.md](../host/devices.md)): `audio_output`, `audio_input`, `video_input`, each specified in its own spec under `host/`.
- **`NaoSimConfig()` is valid and useful**: NAOqi 2.1 with speech on the host loudspeaker, the viewer window on the `empty` scene, and no video or audio input (each `NaoSim/*/Source` key stays `none`).
- The `audio_output` block picks the audio output's sink when the caller passes none ([audio-output.md](../host/audio-output.md), "Audio sinks"; [api.md](api.md)): `play` a `DevicePlayer`, `silent` a `NullSink`, `record` a `WavSink`. A sink passed in code (`MemorySink` in tests) wins over the block.
- Paths (`audio_output.record`, `audio_input.wav`, and `viewer.scene` when it ends in `.xml`) are resolved relative to the config file when loaded with `from_json_file`, and relative to the working directory otherwise.

### Constructors and validation

- Every config class has the same three constructors: `from_dict(data)`, `from_json(text)` (parses, then calls `from_dict`), and `from_json_file(path)` (reads, then calls `from_json`; an invalid-JSON error names the path). All three share one validation path.
- Errors raise `ConfigError(ValueError)`, with a message that names the offending key path (e.g. `audio_input.wav`). A block's own checks raise `ConfigError(message, key=<field>)`, and each enclosing loader prefixes `key` with its own path; the message is never parsed to find the key.
- **Unknown keys are errors**, so a typo fails when the config loads.
- **Type and range checks:** each `Literal` field takes one of its values; `ready_timeout_s` is a positive, finite number; `gate_tail_s` is a non-negative, finite number; `device` is a non-negative integer; `viewer.scene` is a non-empty string.
- **Cross-field checks at load:** `audio_output.mode = "record"` needs `audio_output.record`; `audio_input.source = "wav"` needs `audio_input.wav`. Other fields that do not apply (`device` without a webcam, `wav` with `mic`) are validated but not applied, so switching a source is a one-word change.
- **Environment checks are not config checks.** Whether the `viewer` extra is installed, Docker answers, the images are built and verified, a webcam or a WAV file exists: `NaoSim.start()` checks these ([api.md](api.md)), so a config file stays valid on any machine.
- `config.py` imports neither `qi`, nor `nao_viewer`, nor `sounddevice`.

### The viewer and the video input

`viewer.headless` and `video_input.source` together decide whether the simulated world runs ([viewer.md](../host/viewer.md), "Which viewer runs"):

| `viewer.headless` | `video_input.source` | Sim process | Needs `nao-sim[viewer]` |
| --- | --- | --- | --- |
| `false` | any | `NaoViewer` in sim mode, with its window | Yes |
| `true` | `render` | `NaoViewer` in sim mode, headless | Yes |
| `true` | `none` or `webcam` | None | No |

So a server config is `{"viewer": {"headless": true}}`, and it needs no extra; CI runs a headless viewer with the render camera instead ([ci.md](../testing/ci.md)).

The `viewer` block is nao-sim's own, not an embedded `NaoViewerConfig`: `NaoSim` builds the viewer's config from it as `NaoViewerConfig(mode="sim", headless=headless, naoqi=NaoqiSettings(url=sim.url), world=WorldSettings(scene=scene, variant=variant))`. The mode and the NAOqi URL follow from running nao-sim, so they are not settings; nao-viewer's other fields (`ghost`, `naoqi.rate_hz`, `launch_timeout_s`) keep nao-viewer's defaults. `scene` and `variant` take nao-viewer's values and defaults (`empty`, `auto`); this module only checks their form (a non-empty string; one of the three variants), since `config.py` does not import `nao_viewer`. The rest is checked by nao-viewer itself, in `NaoSim.start()` ([api.md](api.md), "Lifecycle"): an unknown bundled scene when step 1 builds the `NaoViewerConfig` (re-raised as a `ConfigError` with key `viewer.scene`, before anything starts), missing meshes when the viewer launches.

### Sources not built yet

The config accepts every source value from the start (`webcam`, `render`, `mic`, `wav`), so config files written now stay valid as the device specs land. Until a device is built, `NaoSim.start()` fails with an error naming the missing device instead of silently running without it.

### File format

JSON, as nao-bridge: a `sim` block is pasted between a nao-sim file and a nao-bridge file unchanged, which a second format would break. The example files carry no comments; what each one is for is listed below and in the README.

### Embedding in other configs

- The `nao-sim` CLI reads a `NaoSimConfig` file as is (`nao-sim run --config sim.json`, see [cli.md](cli.md)).
- nao-bridge's `sim` backend (`"backend": "sim"`) embeds it as its `sim` block, exactly a `NaoSimConfig`, so a block can be copied between a nao-sim file and a nao-bridge file. nao-bridge imports `NaoSimConfig` from `nao_sim` (lazily, behind its `[sim]` extra); nao-sim never imports nao-bridge.

### Example files

`examples/configs/` holds ready-to-use files, kept in sync with this spec:

- `default.json`: 2.1, window, speech only;
- `2.8.json`: the same on 2.8;
- `headless.json`: 2.1, no window, silent audio output (servers);
- `ci.json`: 2.1, headless viewer with the placeholder variant, `video_input.source = "render"`, silent audio output (the live tier and CI, once the viewer is built);
- `wav-replay.json`: headless, `audio_input.source = "wav"` (once `ALAudioDevice` is built).

## Open questions

1. **More blocks.** Candidates, each deferred until its spec needs it: `speech.language` and voice, the audio output's device and volume ([audio-output.md](../host/audio-output.md), open questions), the microphone's device ([audio-input.md](../host/audio-input.md), open questions), a vendor directory other than the default ([api.md](api.md), "Files on disk"), ports (today 9559, 9562 and the host link's 9563 are fixed, so one nao-sim runs per machine). Adding a block does not break existing files.
