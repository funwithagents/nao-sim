# A block per camera, and the render feeding both

**Status:** Done

Implements [video-input.md](../specs/host/video-input.md) ("Sources", "Frames: fixed rate, VGA, both cameras, whoever subscribes"), [config.md](../specs/runtime/config.md) ("The video input: one block per camera") and [status-service.md](../specs/container/status-service.md) ("ALMemory keys"). The config says what feeds each head camera (`video_input.top`, `video_input.bottom`, each a `source`, an `fps` and a webcam `device`), and the video input feeds every configured camera from its own source each on its own schedule (two cameras at the same `fps` share their slots: `CameraTop` then `CameraBottom` from naoqi-viewer, back to back at the same pose), and injects each into its `ALVideoDevice` index, so a client subscribing to the bottom camera gets what it sees instead of NAOqi's placeholder. It leaves the webcam source unbuilt: accepted by the config, refused by `NaoqiSim.start()` as before.

## Scope

- `src/naoqi_sim/config.py` — `CameraSettings` (`source`, `fps`, `device`); `VideoInputSettings` becomes `top`, `bottom`, with `sources`, `rates` and `cameras(source)` for the callers; error keys `video_input.top.device` and so on
- `src/naoqi_sim/video_input.py` — `VideoInput(sources, fps)` over a mapping of camera name to `FrameSource` (`name`, `frame()`) and one of camera name to rate; `RenderSource(world, camera)`; the render thread runs a schedule per camera, taking the frame of each camera whose slot is due, the inject thread puts each pending camera's newest frame into its index; `missed` counts frames of the schedule (a skipped slot misses one per camera); a closed source drops its cameras, the others carry on; the per-camera keys and the summary (`none`, the one source, `mixed`)
- `src/naoqi_sim/viewer.py` — `needs_viewer`: `render` on either camera
- `src/naoqi_sim/sim.py` — the not-built check per camera (`video_input.<camera>.source`); the device started with a `RenderSource` per rendered camera
- `docker/naoqi/services/status-service/naoqi_sim_status_core.py` — seeds `NaoqiSim/Camera/Top/Source` and `NaoqiSim/Camera/Bottom/Source` at boot beside the summary
- `tests/test_config.py`, `tests/test_viewer.py`, `tests/test_sim.py`, `tests/test_status_core.py`, `tests/test_video_input.py` — the new shape; both cameras injected in order at VGA; the schedule bounds count slots times cameras and the no-burst check reads one camera's puts; a camera whose render fails does not starve the other; one camera alone; the summary `mixed`; a closed source dropping its cameras while another's carry on
- `tests-e2e/conftest.py`, `examples/configs/ci.json` — both cameras on `render`
- `tests-e2e/test_video_input_live.py` — the three keys; `test_the_bottom_camera_gets_no_frames` inverted: the bottom camera's frames come with the top camera's (same slot, fresh timestamps) and show the pillar's foot where a pinhole at `ALMotion.getPosition("CameraBottom")` says, with the head raised so the foot is well in view; the rate test's lower bound allows CI's software renderer paying two renders per slot
- The three specs above (`Updated` until this plan is `Done`), `specs/_index.md`, `specs/_overview.md`, `specs/host/viewer.md`, `specs/host/devices.md`, `AGENTS.md` — "the top camera" becomes both cameras, each as configured

## Steps

1. The specs: a block per camera with its own `fps`; both cameras, `missed` over slots times cameras; the per-camera keys and the summary; the webcam per camera; open question 1 of video-input.md closed; the other specs' and the map's one-liners.
2. `config.py`, `viewer.py`, `sim.py`, the status core, and `video_input.py` as above.
3. The fast tier as above.
4. The live tier: the key and bottom-camera tests, the rate test's bound, run on 2.1 and 2.8 (the status core changed, so the images rebuild); record the rate per camera in the spec's "As measured".

## Result (Oct 16, 2026)

- Fast tier: 307 passed, 1 skipped; ruff, format and pyright clean.
- Live tier, `test_video_input_live.py`, `test_status_live.py`, `test_naoqisim_live.py` on 2.1 and 2.8 (images rebuilt for the status core): 27 passed, 1 skipped. The pinhole test of the bottom camera passes on both with a 15-row tolerance at QVGA.
- Rates with both cameras rendered, a QVGA subscriber per camera, with the per-camera schedules: 15.0/s each at 15/15 on both versions; at 30/30, the top keeps 29.8 and the bottom gets 17.5 (2.1) or 15.0 (2.8), two renders filling the 33 ms slot; at 30/10, 29.8 and 10.0 (2.1), 29.2 and 10.0 (2.8). Recorded in video-input.md ("As measured") with the lever (one viewer call for both cameras) as its open question 1. The first build, one schedule for both cameras, measured 19.5/17.5 (2.1) and 15.0/15.0 (2.8) at 30 on both.
- Live tier again after the per-camera schedules, same three files on 2.1 and 2.8: 27 passed, 1 skipped. Fast tier: 309 passed, 1 skipped.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`, `uv run pytest tests-e2e/test_video_input_live.py tests-e2e/test_status_live.py tests-e2e/test_naoqisim_live.py` on both versions. Then the three specs go back to `Implemented` (file and index) and this plan to `Done`.
