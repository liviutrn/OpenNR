# DuoView v24 — eye-gaze frame fix (root cause of the headset trembling)

Date: 2026-10-18. Base: `experiments/duoview-temporal-shading-v22` @ `8d13ad8f`
(v23 Build32 binary-tested source; docs-only commits after it).

## User symptom

Eye-tracked fovea trembles/shakes: both the crop edge AND the image inside the
foveal region. Worse when gaze is held relatively still and the head moves.
Fixed-center mode is stable.

## Root cause

`DuoViewPSVR2Gaze.hpp` / `optical_ray()` applied the INVERSE of the left eye's
OpenXR stage-space rotation to the PSVR2 Toolkit calibrated gaze ray before
projecting it to screen UV.

That transform is a frame error. The Toolkit ray is HMD-local (a driver-level
eye tracker cannot know the app's stage space). Joey's Mono render camera is
rotation-locked to the HMD, so for a gaze *direction*:

    r_camera = R_cam^T · R_hmd · r_hmd = r_hmd

(any stage-to-world rotation, incl. snap turn, cancels exactly). The HMD-local
ray is already in the camera basis — no transform is needed or valid.

The old code computed `R_eye_stage^T · r_hmd`. During head motion with fixed
world gaze this swings at twice the head rate in the wrong direction, so the
foveal crop chased a phantom: crop edge swims, the cropped projection changes
every frame so TAA/Lumen never converge and the image inside the fovea
shimmers. With the head still the error froze to a constant offset, which is
why it read as "trembling, worse when the head moves" rather than a clean
misalignment. Build32's smoothing/deadzone/50ms-hold could not fix a wrong
transform — it only capped how fast the phantom moved.

## Fix

- `DuoViewPSVR2Gaze.hpp`: `Reader::read_uv(projection)` — the calibrated ray
  projects directly via `projection_uv`; the `optical_rotation` parameter and
  the `optical_ray` call are gone.
- `DuoViewGaze.hpp`: removed `optical_ray` (now unused; keeping it invites
  reintroducing the bug). `ray_to_uv`/`GazeCache` kept (public-SDK path uses
  them). Header documents the no-transform invariant.
- `duoview/joey_stage1/apply_stage234.py`: no longer builds/passes the `optical`
  matrix from `get_eye_transform(0)`; calls `read_uv(frozen)`.
- `duoview/joey_stage1/verify_stage234.py`: verifier token updated.
- `duoview/stage4_gaze_tests.cpp`: removed `optical_ray` tests.
- `duoview/joey_stage1/ProductionPSVR2GazeTests.cpp`: replaced the pinned
  "projected after inverse optical yaw" assertion with a regression test that
  the HMD-local ray projects directly (straight ray -> center, oblique ray ->
  exact direct projection, no rotation parameter exists on `read_uv`).

The Build32 stabilizer (deadzone, 85ms exponential follow, 1.4 UV/s cap,
single-source-pixel alignment, 50ms hold / 100ms gap / drift-to-center) is
unchanged and now operates on a correct UV signal: tracker jitter stays inside
the deadzone during fixation, so the ROI and its projection stay pixel-static
and temporal history converges.

## Validation

- Host: `ctest` 5/5 pass (geometry, gaze, frame, config, state). Windows CI
  runs the full gate incl. `pinned-psvr2-capi-projection-and-validation`.
- Headset (still required): ID6, eye tracking ON, `Smooth tracked crop` ON,
  guard 8%, smoothing 85ms. Stare at a fixed near/far detail, move ONLY the
  head: the foveal region must stay glued to the fixated point with no
  swimming. Then deliberate saccades: the fovea should follow smoothly.
  Compare against eye-tracking OFF (fixed center) as control.

## Deliberately not changed

- Blink/invalid handling, 50ms fresh-hold, 100ms gap hold, drift-to-center:
  unchanged.
- No `frame_counter`-based freshness check: the CAPI already returns false on
  no-new-frame, and a wrong assumption about the counter could break gaze
  entirely. Left as is.
