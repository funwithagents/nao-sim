---
code:
  - src/naoqi_sim/video_input.py
  - src/naoqi_sim/config.py
  - src/naoqi_sim/sim.py
  - src/naoqi_sim/viewer.py
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

The robot's head cameras as a host device ([devices.md](devices.md)). It feeds frames into `ALVideoDevice` so a client that subscribes to a camera gets images through `getImageRemote` as on a NAO, with NAO conventions: camera indices, resolutions, colorspace names, timestamps. Face, people and movement detection run in the clients on those frames, never in naoqi-sim ([_overview.md](../_overview.md), "Perception and speech recognition").

No NAOqi service is replaced: `ALVideoDevice.putImage(camera, width, height, rgb)` is public, so the device is an ordinary qi client. Verified on 2.1 and 2.8: injected frames come back through `subscribeCamera`/`getImageRemote`.

## Decided

### Sources

The `video_input` block of [config.md](../runtime/config.md) ("The video input: one block per camera") has one block per head camera, `top` and `bottom`, each picking its `source`, so what feeds each camera is a config choice:

| `source` | Frames for that camera | Built |
| --- | --- | --- |
| `none` (default) | Nothing; the camera's key stays `none` and NAOqi serves its placeholder (see "As measured") | — |
| `render` | The camera as naoqi-viewer renders it at the robot's current pose ([viewer.md](viewer.md)) | First: the only source CI can test. Top camera Oct 9, 2026; either camera Oct 16 |
| `webcam` | The host webcam `device`, cropped to the camera | After `render` |

- **Render** closes the loop: NAOqi moves the head, naoqi-viewer renders what the camera sees (`NaoqiViewer.camera_frame(camera, 640, 480)`, RGB), the device injects it, NAOqi serves it. It needs the viewer, so `render` on either camera makes the viewer run, windowed or headless ([viewer.md](viewer.md), "Which viewer runs").
- **Webcam**: OpenCV capture, cropped to the NAO camera's aspect and field of view (60.97° × 47.64°) and scaled to VGA. Off unless a camera's block says `webcam`, with the indicator of [devices.md](devices.md) ("Off unless asked"); while the source is on, the webcam captures. Each block names its own `device`, so a laptop's one webcam feeds the top camera (the bottom one rendered or unfed), or two webcams feed the two cameras.
- The device publishes each camera's key, `NaoqiSim/Camera/Top/Source` and `NaoqiSim/Camera/Bottom/Source` (`render`, `webcam`, or `none` for a camera not fed), then the summary `NaoqiSim/Camera/Source` that `status()` reads (`none` when no camera is fed, the one source feeding them, `mixed` when they differ) when it starts, and `none` everywhere when it stops ([status-service.md](../container/status-service.md), which seeds all three at boot).

### Frames: fixed rate, VGA, both cameras, whoever subscribes

The device injects frames on its own schedule, **independently of `ALVideoDevice`'s subscribers**: it never reads `getSubscribers()` and never converts a frame.

- **Rate**: each camera's `fps` (an integer from 1 to 30, default 15), on its own fixed schedule, all the schedules starting together at the device's start: a slot calls for one frame of that camera. A slot that is missed is skipped, never caught up, so no camera's rate exceeds its `fps`. `VideoInput.missed_by_camera` counts, per camera, the frames of its schedule that never reached NAOqi: a slot skipped by a render that ran past it, or a frame replaced by the next one before injection (`missed` is their sum); a camera's frames put plus its missed is its schedule, which the fast tier checks against the time the device actually ran (measured around `start()` and `stop()`), rather than a frame count in a fixed second a loaded machine can't hold. Two rates let a client-heavy top camera run fast while the bottom one, often unused, runs slow: bandwidth to the clients, and renders to the viewer (below).
- **Size and format**: one RGB frame of 640×480 (VGA) per slot, the largest size both versions accept: 2.8's `putImage` refuses anything above VGA and silently downgrades a 4VGA subscription to QVGA; 2.1 accepts up to 4VGA. Odd sizes are refused erratically on both, so the device sends VGA only.
- **Both cameras, each from its source**: the render thread takes the frame of every camera whose slot is due, `CameraTop` (index 0) then `CameraBottom` (index 1), and injects each into its own index. A client subscribing to a fed camera gets frames, as on a NAO. Two cameras at the same `fps` share their slots, back to back so both show the same pose, and a client reading both sees the same moment (two timestamps a `putImage` apart); at different rates they meet only when both are due. On a machine whose render outlasts a slot (CI's software renderer, about 110 ms a VGA frame), each camera skips its own slots and the two schedules drift apart, so the cameras are rendered in turn: no longer the same moment, but neither starves the other, which is why the live tier runs the bottom camera at 5 fps there and pins the shared slots in the fast tier. Renders are what the viewer pays: one per frame, at one per 60 Hz tick. Both cameras at the default 15 fps are 30 renders per second, half the ceiling, and 15 holds exactly; both at 30 fill every slot with two renders, so slots get missed (skipped, never caught up): the top camera, rendered first in each shared slot, keeps its 30, and the bottom one, rendered after it, gets 15 to 17; 30 on the top camera with 10 on the bottom one are 40 renders per second, and both rates hold (see "As measured"). The maximum stays 30, a NAO camera's.
- **NAOqi does the rest.** One injected RGB frame serves every subscriber of that camera at its own resolution and colorspace (RGB, BGR, YUV422, Y...), scaled up or down, with a timestamp NAOqi sets at `putImage`. A client asking for more than `fps` gets the last frame again, as `getImageRemote` returns it immediately with the same timestamp.
- NAOqi's own subscribers (`FrameGetter/*` on both versions; on 2.8 also people perception's `VideoDevice_TopCamera<QVGA>`, the depth camera's and `ALBasicAwareness`'s) need no special case: the device does not look at subscribers.
- **Render and inject run on separate threads**, the newest rendered frame of each camera winning, so a `putImage` (1–5 ms under emulation) never makes the next render miss naoqi-viewer's 60 Hz tick: 30 fps held on both versions with one camera; with two, see "As measured".

### In a running `NaoqiSim`

- The device runs in-process on its own threads, with its own qi session (`stack.connect`, one attempt), started by `NaoqiSim.start()` once the robot is ready **and, for `render`, once the viewer is launched**; `stop()` stops it before the viewer ([api.md](../runtime/api.md), "Lifecycle").
- **The window closed by the user** with a rendered camera: the next `camera_frame` raises `ViewerClosed`. The device drops every camera that source fed, writes their keys and the summary back (`none` once nothing is fed) and logs once, at warning level, that those cameras have no frames any more; NAOqi keeps serving their last frame. A camera fed by another source carries on; when none is left, the device stops. The robot keeps running, as for the window alone ([api.md](../runtime/api.md), "Lifecycle").
- A failing `putImage` or render (anything but `ViewerClosed`) is logged and the device carries on with the next slot; a run of failures is logged once, not once per frame.

### The image side

Nothing to change in the images. Both suites ship `/opt/naoqi/etc/naoqi/VideoDevice.xml` with `videoDeviceModule = Simulator` (2.8 adds simulated-camera preferences), and `putImage` works as shipped on both. There is no `VideoInput.xml` in either suite; the earlier plan to pin one is dropped.

### As measured

Spike of Oct 9, 2026 (`spike/RESULTS.md`, "Video input"), both versions, OrbStack on Apple Silicon:

- Per-subscriber conversion: six subscribers on `CameraTop` (QQVGA/QVGA/VGA RGB, QVGA BGR, YUV422, Y), one RGB `putImage`, each served correctly in its own format with one timestamp.
- `putImage` sizes: 2.1 accepts 80×60 to 1280×960; 2.8 accepts 80×60 to 640×480; 4VGA on 2.8, 2560×1920 on both and odd sizes return `False` and drop the frame.
- `camera_frame` runs at 58–60 per second at any resolution (one answer per tick of naoqi-viewer's render loop); `putImage` takes 0.8–1.8 ms at VGA; a serial render-then-inject loop reaches 30–32 VGA frames per second.
- A `CameraBottom` subscriber on a fresh stack, nothing ever injected (measured with the plan that built the top camera, before the bottom one was fed): `getImageRemote` answers at once with a constant placeholder at the requested size and colorspace, (0, 154, 0) green and black in RGB/BGR, all zeros in Y, timestamp 0 on 2.1 and the current time on 2.8. No error. This is what a client sees on `CameraBottom` with the webcam source, and on either camera with `source = "none"`.

Oct 16, 2026, both cameras rendered (plan [202610161135_video-input-both-cameras.md](../../plans/202610161135_video-input-both-cameras.md)), same machine:

- Both cameras at `fps = 15`: 15.0 frames per second on each camera, on 2.1 and 2.8, read by a QVGA subscriber of each (`getImageRemote` polled, distinct timestamps counted over 4 s).
- Both cameras at `fps = 30`: 29.8 (top) and 17.5 (bottom) per second on 2.1, 29.8 and 15.0 on 2.8. Two renders at one per 60 Hz tick take the whole 33 ms slot, so the slightest overhead runs past it and a slot is skipped; the top camera's slot comes first, so the bottom camera's is the one skipped. (With the one schedule for both cameras this plan first built, both fell to 15 to 20.)
- Top camera at 30, bottom at 10: 29.8 and 10.0 on 2.1, 29.2 and 10.0 on 2.8: 40 renders per second fit the viewer's budget, and each camera keeps its rate, which is what the per-camera `fps` is for.
- The live tier's pinhole test of the bottom camera (`test_the_bottom_camera_looks_down_at_the_pillars_foot`) passes on both versions with its 15-row tolerance at QVGA: the viewer's `CameraBottom` pose and NAOqi's `getPosition("CameraBottom")` agree.

## Open questions

Deferrals; none blocks the render source.

1. **30 fps on both cameras.** Two renders per slot cap the bottom camera at 15 to 17 per second when both ask for 30 ("As measured"). The lever is naoqi-viewer's: one `camera_frame` call returning both cameras' frames from one tick, which the device would take instead of two calls. Until a client needs 30 on both, 30 on the top and 10 to 15 on the bottom is the figure.
2. **Resolution and subscribers.** 4VGA on 2.1, or rendering a camera only while a client subscribes to it (which would need to tell NAOqi's own subscribers apart), if the fixed VGA streams prove wasteful or too small. Two cameras doubled the viewer's load, so this is the first lever if a small machine or CI's software renderer cannot hold the rate.
3. **Webcam selection.** An index (`device: 0`) is what OpenCV takes, but indices are not stable across reboots or USB changes; a name match may be needed.
4. **The webcam dependency.** `opencv-python-headless` as a runtime dependency, or behind a `webcam` extra so a CI or server install stays small.
5. **NAO V6 cameras.** The render uses naoqi-viewer's V5 model (47.64° vertical field of view). Whether 2.8 (NAO V6) needs its own geometry is open on the naoqi-viewer side.
