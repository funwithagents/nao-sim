---
code:
  - src/nao_sim/video_input.py
  - src/nao_sim/config.py
  - src/nao_sim/sim.py
  - src/nao_sim/viewer.py
tests:
  - tests/test_video_input.py
  - tests/test_config.py
  - tests/test_sim.py
  - tests/test_viewer.py
  - tests-e2e/test_video_input_live.py
---

# Video input

**Status:** Implemented

## Purpose

The robot's head cameras as a host device ([devices.md](devices.md)). It feeds frames into `ALVideoDevice` so a client that subscribes to a camera gets images through `getImageRemote` as on a NAO, with NAO conventions: camera indices, resolutions, colorspace names, timestamps. Face, people and movement detection run in the clients on those frames, never in nao-sim ([_overview.md](../_overview.md), "Perception and speech recognition").

No NAOqi service is replaced: `ALVideoDevice.putImage(camera, width, height, rgb)` is public, so the device is an ordinary qi client. Verified on 2.1 and 2.8: injected frames come back through `subscribeCamera`/`getImageRemote`.

## Decided

### Sources

The `video_input` block of [config.md](../runtime/config.md) picks one:

| `source` | Frames | Built |
| --- | --- | --- |
| `none` (default) | Nothing; `NaoSim/Camera/Source` stays `none` | — |
| `render` | `CameraTop` rendered by nao-viewer at the robot's current pose ([viewer.md](viewer.md)) | First: the only source CI can test |
| `webcam` | The host webcam `video_input.device`, as `CameraTop` | After `render` |

- **Render** closes the loop: NAOqi moves the head, nao-viewer renders what the top camera sees (`NaoViewer.camera_frame("top", 640, 480)`, RGB), the device injects it, NAOqi serves it. It needs the viewer, so `source = "render"` makes the viewer run, windowed or headless ([viewer.md](viewer.md), "Which viewer runs").
- **Webcam**: OpenCV capture, cropped to the NAO camera's aspect and field of view (60.97° × 47.64°) and scaled to VGA. Off unless the config says `webcam`, with the indicator of [devices.md](devices.md) ("Off unless asked"); while the source is on, the webcam captures.
- The device publishes `NaoSim/Camera/Source` (`render`, `webcam`) when it starts and `none` when it stops.

### Frames: fixed rate, VGA, top camera, whoever subscribes

The device injects frames on its own schedule, **independently of `ALVideoDevice`'s subscribers**: it never reads `getSubscribers()` and never converts a frame.

- **Rate**: `video_input.fps` frames per second (an integer from 1 to 30, default 15), on a fixed schedule from the device's start. A frame that misses its slot is skipped, never caught up, so the rate never exceeds `fps`.
- **Size and format**: one RGB frame of 640×480 (VGA) per slot, the largest size both versions accept: 2.8's `putImage` refuses anything above VGA and silently downgrades a 4VGA subscription to QVGA; 2.1 accepts up to 4VGA. Odd sizes are refused erratically on both, so the device sends VGA only.
- **One camera**: `CameraTop` (index 0) only. `CameraBottom` gets no frames from either source for now; a client subscribing to it gets what NAOqi serves for a camera never fed (see "As measured").
- **NAOqi does the rest.** One injected RGB frame serves every subscriber of that camera at its own resolution and colorspace (RGB, BGR, YUV422, Y...), scaled up or down, with a timestamp NAOqi sets at `putImage`. A client asking for more than `fps` gets the last frame again, as `getImageRemote` returns it immediately with the same timestamp.
- NAOqi's own subscribers (`FrameGetter/*` on both versions; on 2.8 also people perception's `VideoDevice_TopCamera<QVGA>`, the depth camera's and `ALBasicAwareness`'s) need no special case: the device does not look at subscribers.
- **Render and inject run on separate threads**, the newest rendered frame winning, so a `putImage` (1–5 ms under emulation) never makes the next render miss nao-viewer's 60 Hz tick: 30 fps holds on both versions.

### In a running `NaoSim`

- The device runs in-process on its own threads, with its own qi session (the connect retry 2.1 needs), started by `NaoSim.start()` once the robot is ready **and, for `render`, once the viewer is launched**; `stop()` stops it before the viewer ([api.md](../runtime/api.md), "Lifecycle").
- **The window closed by the user** with `source = "render"`: the next `camera_frame` raises `ViewerClosed`. The device stops, writes `NaoSim/Camera/Source` back to `none` and logs once, at warning level, that the camera has no frames any more; NAOqi keeps serving the last frame. The robot keeps running, as for the window alone ([api.md](../runtime/api.md), "Lifecycle").
- A failing `putImage` or render (anything but `ViewerClosed`) is logged and the device carries on with the next slot; a run of failures is logged once, not once per frame.

### The image side

Nothing to change in the images. Both suites ship `/opt/naoqi/etc/naoqi/VideoDevice.xml` with `videoDeviceModule = Simulator` (2.8 adds simulated-camera preferences), and `putImage` works as shipped on both. There is no `VideoInput.xml` in either suite; the earlier plan to pin one is dropped.

### As measured

Spike of Oct 9, 2026 (`spike/RESULTS.md`, "Video input"), both versions, OrbStack on Apple Silicon:

- Per-subscriber conversion: six subscribers on `CameraTop` (QQVGA/QVGA/VGA RGB, QVGA BGR, YUV422, Y), one RGB `putImage`, each served correctly in its own format with one timestamp.
- `putImage` sizes: 2.1 accepts 80×60 to 1280×960; 2.8 accepts 80×60 to 640×480; 4VGA on 2.8, 2560×1920 on both and odd sizes return `False` and drop the frame.
- `camera_frame` runs at 58–60 per second at any resolution (one answer per tick of nao-viewer's render loop); `putImage` takes 0.8–1.8 ms at VGA; a serial render-then-inject loop reaches 30–32 VGA frames per second.
- A `CameraBottom` subscriber on a fresh stack, nothing ever injected (measured with the plan that builds this spec): `getImageRemote` answers at once with a constant placeholder at the requested size and colorspace, (0, 154, 0) green and black in RGB/BGR, all zeros in Y, timestamp 0 on 2.1 and the current time on 2.8. No error, so the device feeds nothing there.

## Open questions

Deferrals; none blocks the render source.

1. **The bottom camera.** Rendering `CameraBottom` too (alternating renders, at most 30 fps each within nao-viewer's 60 per second), once a client needs it.
2. **Resolution and subscribers.** 4VGA on 2.1, or rendering only while a client subscribes (which would need to tell NAOqi's own subscribers apart), if the fixed VGA stream proves wasteful or too small.
3. **Webcam selection.** An index (`device: 0`) is what OpenCV takes, but indices are not stable across reboots or USB changes; a name match may be needed.
4. **The webcam dependency.** `opencv-python-headless` as a runtime dependency, or behind a `webcam` extra so a CI or server install stays small.
5. **NAO V6 cameras.** The render uses nao-viewer's V5 model (47.64° vertical field of view). Whether 2.8 (NAO V6) needs its own geometry is open on the nao-viewer side.
