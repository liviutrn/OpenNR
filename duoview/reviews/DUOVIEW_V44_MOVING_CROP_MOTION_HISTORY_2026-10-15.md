# DuoView v44: moving crop and motion history

Status: Windows candidate build requested; headset validation is pending.

## Finding

The OpenNR correction and DuoView need different treatment because the crop is applied at a different stage. OpenNR crops an already-rendered image, so its motion vectors do not contain the crop-origin change. Its current-to-previous crop-local contribution is

```text
delta_local = (current_crop_origin - previous_crop_origin) / crop_extent
delta_source_pixels = delta_local * foveal_source_size
```

DuoView changes the foveal projection before Unreal renders the view. With a persistent, dedicated Unreal `ViewState` for that source view, Unreal's previous clip transform should contain both the old and new crop projections and generate this contribution itself. Adding OpenNR's delta again would double-count the crop motion. The final compositor maps fovea-local samples back through the current crop origin, so a stationary world point remains at the same full-view UV while its fovea-buffer coordinate changes.

This is the key v44 distinction: the fovea buffer has crop-induced motion; the reconstructed output has no motion from the crop alone. Real head motion remains handled by Unreal's normal view transform.

## Changes

- Replaced v43 gaze-camera steering and its shader homography with a gaze-dependent off-axis crop projection. Both source views retain the same head pose; only the selected foveal projection and ROI move.
- Added `DuoViewCropMotion.hpp` for the expected current-to-previous crop vector. It rejects frame gaps, generation changes, crop-size changes, and view-selector changes. This is an audit/test calculation, not an injected motion-vector offset.
- Added an eye-tracked composition gate. The two source `ViewState` identities must be distinct and persist across adjacent producer frames; the foveal source, atlas dimensions, crop extent, and fovea-buffer dimensions must also remain compatible. A state change or frame gap blocks the candidate frame and follows the existing ID6 quarantine fallback.
- Changed the PSVR2 reader to return its original host-arrival time with a cached gaze sample. Both the reader and crop stability honor that same 50 ms arrival-time limit; repeated reads do not renew it, and a blink or invalid packet clears the crop immediately.
- Kept the final-color compositor free of manual crop-vector shifting. A separate offset would be a second correction if Unreal's per-view history already contains the crop.
- Updated UI and logs to report fixed head pose, gaze crop movement, prior-frame continuity, `ViewState` identity, crop-layout stability, history-gate result, and expected static-world fovea-buffer vector.

## Verification

Local GCC checks passed for geometry, gaze, frame, config, state, probe, and the randomized foveal temporal oracle. The oracle covered 17,280 deterministic projection pairs, including asymmetric projections, moving crops, head poses, source resolutions, and densities. It also checks the vector sign and scale, rejects missing previous projections and frame gaps, and detects double correction. CMake is unavailable in this environment, so the Windows production/WARP, pinned Joey backend, and package audit are delegated to the v44 Actions build.

The Windows candidate must still establish whether the actual game render path keeps distinct persistent foveal/peripheral `ViewState` objects and whether the active temporal upscaler consumes the generated previous-projection vectors. The source gate checks necessary identity/layout conditions; it is not proof of TSR behavior. No private Unreal history memory or guessed SDK fields are modified. Physical STALKER 2 / PSVR2 validation remains required.

## Test focus

1. Enable the v44 temporal audit and confirm `separateStates`, `persistentStates`, `stableCropLayout`, and `historyGate` remain valid while gaze moves and the head stays still.
2. Confirm the logged fovea-buffer vector changes with gaze while static scene detail remains fixed in the final view.
3. Watch for the history gate to block and ID6 to fall back if the game changes `ViewState` identity or drops a producer frame.
4. Compare temporal ghosting/shimmer during stationary fixation and deliberate saccades with the previous build. The audit log is evidence of prerequisites, not a direct readback of TSR's velocity input.
