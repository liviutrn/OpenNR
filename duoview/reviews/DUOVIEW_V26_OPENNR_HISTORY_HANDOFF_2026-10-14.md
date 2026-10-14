# DuoView v26 — OpenNR controls and DLSS history protection

Branch: `experiments/duoview-v25-gaze-camera-always-on`. Windows build pending.
The user approved the fixes and building and requested the last OpenNR stabilization controls plus a fix for gaze-dependent jitter and jelly-like settling.

## Source-backed changes

Exact reference: OpenNR r10 `3a403d6fea9cc73818b1cdd7473bd6fd9cb5cb98`, `runtime/open-shaders/src/Features/Upscaling/GazeCropPolicy.h`, `NativeOpenVRGaze.h/.cpp`, `FoveatedRender.cpp` and `FoveatedRender/Modes.cpp`.

The reference has stabilization through a central guard `min(2% full view,5% crop)`, fixation smoothing only for <=2 input-pixel changes, larger movements immediately bypassed, and quantization 0–64 input pixels (default8). Default smoothing is zero. These real controls are ported, with a toggle and restore-defaults button. Quantization scales to the observed foveal DLSS input size when a known foveal evaluation is matched. No continuous delayed crop following or speed cap.

The v25 gaze-directed camera and matching ray compositor remain. Crop position is frozen per producer frame. Tests verify instant deliberate movements, held fixation and zero position drift after movement stops. Tracking loss retains the coordinate while rendering fresh scene color.

New NGX hook uses official pinned NVIDIA headers `NVIDIA/DLSS@374959484e79a640feaba44c93ac8cfb0a03f5b5`. Header files are checked out in CI, never redistributed or substituted into Joey's restricted SDK.

Only known SuperSampling feature handles whose output dimensions uniquely match the current foveal source can receive a temporary Reset flag. The render-frame key comes from the existing protected OpenXR RHI assignment, not the latest game-thread gaze. Unknown, peripheral, equal-size ambiguous, unavailable-frame and non-DLSS features are passed through. The NGX parameter is restored after evaluation, and the game's own reset is preserved. Input dimensions inform pixel quantization.

History protection defaults ON, is toggleable, resets on a changed crop and its first stationary successor, then stops resetting on stable fixation. This protects against incompatible history continuing to slide after gaze stops, without feature/resource recreation. It is a containment strategy, not a claim that private Unreal velocity textures have been repaired. API hook status, matched evaluations and actual forced resets are visible in-game.

Runtime lifetime is protected with an atomic shared runtime snapshot, avoiding an added VR-lock dependency in DLSS evaluation. Device reset retains that snapshot while retiring frame history; runtime recreation clears it and publishes the new runtime. Hook targets are pinned; callbacks are installed disabled before enabling.

## Preserved behavior

ID6 only from startup and runtime recreation, direct constructor-hook initialization, compact engine atlas and full-size XR output, fixed-center off-axis mode when tracking OFF, optional primary-shading toggle, and original Joey/SDK/frontend pins. User-confirmed Joey Build3 is untouched. See the v25 handoff for full architecture and startup details.

## Validation and remaining uncertainty

Local CPU suites pass, including 8100 ray round-trips, instant quantized saccades, no stopped-crop drift, one-frame settling protection, fixed-crop history preservation, peripheral exclusion, NGX signed/unsigned Reset parameter handling, authored-reset preservation and restoration.

Final local check reran all nine CPU executables with assertions enabled after reapplying the latest patch to the exact backend/frontend pins: geometry, gaze, frame, config, state, gaze camera, temporal stability, pinned production contracts, and official NGX parameters. All passed. The patch scripts also compile and `git diff --check` is clean. Windows NGX tests explicitly retain assertions in Release builds. Local application excludes Windows shader embedding and cannot replace the Windows build or GPU WARP tests.

Windows CI must compile all changes, exercise WARP compositor mapping/slot reuse and official-SDK parameter contracts, run all original Joey compatibility tests, build the exact backend and matching frontend, and inspect package hashes.

No STALKER2 GPU capture or PSVR2 execution is available here. The jelly symptom is consistent with temporal mismatch but its actual game root cause is not proven. Direct NGX protection does not patch TSR, Lumen or Ray Reconstruction private histories, and hook installation alone does not prove the game's feature/frame matching. Do not claim headset jitter fixed solely from CI. Final artifact identity and CI results will be appended after verification.

## Build publication status

An earlier automatic review rejected publication as insufficiently authorized. The user subsequently gave full authorization to publish and build this experimental branch. Shell Git has no configured GitHub credentials here; publication uses the connected GitHub API and must preserve the exact tested source tree. Windows validation remains pending until the resulting workflow succeeds.
