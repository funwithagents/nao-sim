---
code:
tests:
---

# Video input

**Status:** Draft

## Purpose

The robot's head cameras as a host device ([devices.md](devices.md)). It feeds frames into `ALVideoDevice` so a client that subscribes to a camera gets images through `getImageRemote` as on a NAO, with NAO conventions: camera indices, resolutions, colorspace names, timestamps. Face, people and movement detection run in the clients on those frames, never in nao-sim ([_overview.md](../_overview.md), "Perception and speech recognition").

No NAOqi service is replaced: `ALVideoDevice.putImage(camera, width, height, rgb)` is public, so the device is an ordinary qi client. Verified on 2.1 and 2.8: injected frames come back through `subscribeCamera`/`getImageRemote`.

## Decided

### Sources

The `video_input` block of [config.md](../runtime/config.md) picks one:

| `source` | Frames | Built |
| --- | --- | --- |
| `none` (default) | Nothing; `NaoSim/Camera/Source` stays `none` | — |
| `render` | `CameraTop` and `CameraBottom` rendered by nao-viewer at the robot's current pose ([viewer.md](viewer.md)) | First: the only source CI can test |
| `webcam` | The host webcam `video_input.device`, as `CameraTop` | After `render` |

- **Render** closes the loop: NAOqi moves the head, nao-viewer renders what that camera sees (`NaoViewer.camera_frame(camera, width, height)`, RGB with the pose sequence and age), the device injects it, NAOqi serves it. It needs the viewer, so `source = "render"` makes the viewer run, windowed or headless ([viewer.md](viewer.md), "Which viewer runs").
- **Webcam**: OpenCV capture, cropped to the NAO camera's aspect and field of view (60.97° × 47.64°) and scaled to the requested resolution. It feeds `CameraTop` only; `CameraBottom` gets no frames. Off unless the config says `webcam`, with the indicator of [devices.md](devices.md) ("Off unless asked").
- The device publishes `NaoSim/Camera/Source` (`render`, `webcam`) when it starts and `none` when it stops.

### The image side

Both NAOqi images pin `ALVideoDevice`'s input to `SimulatorCam` in `VideoInput.xml`, so `putImage` is the only source of frames. The desktop suites already accept `putImage` as shipped; the pin makes it explicit. This lands in [container.md](../container/container.md) (which becomes `Updated`) with the plan that builds this spec.

### Driving the frames from the subscribers

- The device reads `ALVideoDevice.getSubscribers()` twice a second, and for each subscriber its camera, resolution, colorspace and frame rate.
- It produces frames only for a camera that has subscribers, at the highest frame rate they ask for, and stops when the last one leaves: no subscriber, no render and no webcam capture.
- It converts each frame from RGB to what the subscribers need before `putImage` (see open question 1) and keeps NAO's resolution constants (QQVGA to 4VGA) and colorspace names.

## Open questions

1. **Several subscribers on one camera.** `putImage` injects one frame per camera, but two subscribers can ask the same camera for different resolutions or colorspaces. Whether NAOqi converts an injected frame per subscriber, or serves it as injected, is to measure on both versions before this spec can be `Stable`: it decides whether the device injects one RGB frame at the largest resolution or must pick one subscriber's format.
2. **Render throughput.** nao-viewer's protocol pulls one frame per request (0.9 MB per VGA frame over loopback). Two cameras at 30 fps may need a streaming operation or shared memory on the nao-viewer side; decide with measurements.
3. **Webcam selection.** An index (`device: 0`) is what OpenCV takes, but indices are not stable across reboots or USB changes; a name match may be needed.
4. **The webcam dependency.** `opencv-python-headless` as a runtime dependency, or behind a `webcam` extra so a CI or server install stays small.
5. **NAO V6 cameras.** The render uses nao-viewer's V5 model (47.64° vertical field of view). Whether 2.8 (NAO V6) needs its own geometry is open on the nao-viewer side.
