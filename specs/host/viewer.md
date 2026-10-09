---
code:
  - src/nao_sim/viewer.py
  - src/nao_sim/sim.py
  - pyproject.toml
tests:
  - tests/test_viewer.py
  - tests/test_sim.py
  - tests-e2e/test_naosim_live.py
---

# Viewer: the simulated world

**Status:** Stable

## Purpose

The NAO in its scene: a window showing the robot posed from nao-sim's NAOqi, the head-camera renders the video input injects ([video-input.md](video-input.md)), and later the clicks the touch input turns into touches ([touch-input.md](touch-input.md)). It comes from nao-viewer, a separate package that owns the NAO MuJoCo model, the license-gated meshes and the 3D rendering; nao-sim drives its **sim mode**, built and specified with nao-viewer (its `specs/api.md` and `specs/config.md`).

nao-viewer is a kinematic mirror, not a physics simulation: it reads joint angles and the torso pose from NAOqi over qi (`ALMotion.getAngles("Body", True)` and `getTransform("Torso", 1, True)` at 50 Hz), writes them into the model and renders at 60 Hz. The viewer is not a device ([devices.md](devices.md)), but it lives on the host and a running `NaoSim` owns it as it owns the devices.

## Decided

### Who does what

| | nao-viewer (viewer process) | nao-sim (host process) |
| --- | --- | --- |
| Process | Started by `NaoViewer.launch()` as its own process (`mjpython` on macOS when windowed), so MuJoCo's window, OpenGL and the macOS main-thread rule stay out of nao-sim | Builds the `NaoViewer`, launches it, and closes it when the `NaoSim` stops |
| Robot pose | Reads it from nao-sim's NAOqi over qi, like any client | Nothing: NAOqi is the source of truth |
| Scene | Loads and renders it: a bundled scene (`empty`, the default: a floor and a light; `table`: a low table with objects in front of the robot) or a user MJCF file | Chooses it (`viewer.scene`) |
| Head cameras | Renders RGB frames of `CameraTop`/`CameraBottom` on request, at the robot's current pose | Decides which camera, resolution and rate, converts, calls `putImage` ([video-input.md](video-input.md)) |
| Model variant | Aldebaran's meshes if the user ran `nao-viewer fetch-meshes`, else the placeholder visuals | Passes `viewer.variant` through; the meshes never pass through nao-sim |

- The viewer process only reads NAOqi. Everything NAOqi-specific (colorspaces, subscriptions, `putImage`, touch events) stays in nao-sim, which keeps the viewer generic.

### Configuration

nao-sim's `viewer` block ([config.md](../runtime/config.md), "The viewer and the video input") is its own subset, `{headless, scene, variant}`, not an embedded `NaoViewerConfig`. nao-sim builds `NaoViewerConfig(mode="sim", headless=viewer.headless, naoqi.url=sim.url, world={scene, variant})`: the mode and the URL follow from running nao-sim, so they are not settings; nao-viewer's other fields keep its defaults.

### Which viewer runs

`viewer.headless` decides the window; the video input decides whether a headless run needs the viewer at all:

| `viewer.headless` | `video_input.source` | Viewer | Needs `nao-sim[viewer]` |
| --- | --- | --- | --- |
| `false` | any | `NaoViewer` in sim mode, with its window | Yes |
| `true` | `render` | `NaoViewer` in sim mode, headless (offscreen renders, no display; Mesa's EGL on Linux) | Yes |
| `true` | `none` or `webcam` | None | No |

When the extra is needed and missing, `NaoSim.start()` fails before starting anything, with a message naming the extra ([api.md](../runtime/api.md), "Lifecycle").

### The public API only

- `NaoViewer(config).launch()` starts the process and returns once it can render (`LaunchError` otherwise, which fails `NaoSim.start()` like any other step); `camera_frame(camera, width, height)`; `status()`; `close()`. A window closed by the user makes the next call raise `ViewerClosed`.
- Importing `nao_viewer` loads neither MuJoCo nor qi, and nao-sim imports it lazily, only when the config needs it. The API is synchronous; `NaoSim` calls it through `asyncio.to_thread`.
- The viewer process exits when its caller's connection closes, so a `NaoSim` that dies never leaves a window behind.

### Window closed

Closing the sim window stops the viewer only; the robot keeps running, and the `NaoSim` logs it once and does not reopen the window ([api.md](../runtime/api.md), "Lifecycle"). A NAO does not stop when nobody watches it, and a nao-bridge app or a test that owns the `NaoSim` must not lose its robot to a click. Ctrl-C (or `NaoSim.stop()`) stops the run.

### Dependency

Through the `nao-sim[viewer]` extra, which pulls nao-viewer and with it MuJoCo. Without it, nao-sim runs with no window and no render camera: every NAOqi API, speech, the audio input and the webcam all work, which suits servers. nao-viewer depends on libqi only, never on nao-sim, so the chain stays one-way; `nao-bridge[sim]` pulls `nao-sim[viewer]`, so the full experience stays one install.

- nao-viewer is not on PyPI: `[tool.uv.sources]` takes it from its GitHub repository (`funwithagents/nao-viewer`), pinned to a commit, as the libqi wheels are taken from theirs, and a project depending on nao-sim from git gets that pin with it ([project.md](../project.md), "Distribution"). Its meshes, fetched with `nao-viewer fetch-meshes`, are shared by every environment on the machine.
- The dev environment installs the extra, so the code that drives the viewer type-checks against nao-viewer's real API; the fast tier never launches it.

### In the live tier and CI

The live tier runs the viewer from the start, headless, with the render camera and the placeholder variant: `{"viewer": {"headless": true, "variant": "placeholder"}, "video_input": {"source": "render"}}`. That tests the whole camera loop (a client subscribes, the viewer renders, `putImage` injects, the client reads the frame back) on a runner with no display ([ci.md](../testing/ci.md)). The placeholder visuals are enough to assert frames, and CI never accepts the meshes' license.

Until the render camera is built (milestone 4), a headless config with no render source runs no viewer, so the live tier has none; the window itself needs a display and is checked by a live test that skips without one.

### As built

The window is built: `NaoSim` launches the viewer for `headless = false`, closes it on `stop()`, and logs a window closed by the user. The headless viewer comes with the render camera ([video-input.md](video-input.md)): until then `video_input.source = "render"` is refused at start, and this spec stays `Stable`.

## Open questions

1. **Subtitles.** Showing what the robot says in the window, from the `ALTextToSpeech` replacement's sentences ([speech.md](../services/speech.md)); needs a nao-viewer operation.
2. **Virtual robot sensors.** What `getAngles(..., True)` and the ALMemory sensor keys return on the desktop NAOqi (likely the commanded values); it decides how faithful the pose, and so the render camera, are.
3. **NAO V6 geometry.** nao-viewer's model is V5; whether 2.8 (NAO V6) needs its own model is open on the nao-viewer side.
