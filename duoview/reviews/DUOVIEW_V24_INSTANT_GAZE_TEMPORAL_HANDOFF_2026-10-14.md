# DuoView v24 — Instant Gaze / Projection Coherence / Temporal Diagnostics

## Purpose
The user headset-tested v23 Build32 and rejected smoothing: the crop followed eyes too slowly, and the image inside the moving fovea still visibly jumped. Fixed center remains stable. This is a *rendering/temporal reprojection investigation*, not a request to hide the problem by slowing gaze.

## Exact source
Repository: https://github.com/liviutrn/OpenNR
Branch: `experiments/duoview-v24-instant-gaze-temporal-audit`
**Binary source commit (CI run 33): `d6b0a2bcd416073c41475f717aac03265c9687fd`.**
Production CI: https://github.com/liviutrn/OpenNR/actions/runs/38575997437
The precise binary backend source is pinned Joey `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`, original restricted SDK `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`, matching frontend `joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091` plus exact DuoView patches. **Never modify original stable Joey Build3 ID5 / native stereo ID0.** Experiment runs only ID6, STALKER2 DX12 SteamVR OpenXR.

## Implemented on v24
1. `duoview/DuoViewCropStability.hpp`: valid fresh eye samples are returned directly each producer frame, **without a deadzone, smoothing, max speed, quantization, or time lag**. A no-new-sample gap holds the last UV for at most 50ms, then returns center. This is an instantaneous filter rather than a temporal smooth. The immutable per-frame packet is still shared by both UE source views and the DX12 compositor.
2. `duoview/joey_stage1/apply_stage234.py`: original v23 persisted control values are explicitly forced to guard=0 and smoothing=0 and no longer shown as active. Added opt-in `DuoViewTemporalAudit` control. When the constructor for the actual main UE `FSceneView` runs, v24 compares its known, typed `FSceneViewInitOptionsUE5/UE50To53` projection to the frozen source frame. If mismatched, it reconciles the *current* constructor projection before UE constructs the view. Requires DX12 DuoView ID6, active main view and double-precision engine context. No guessed offsets, no global CVar, no direct private temporal writes. Rect mismatch is observed/logged, not forcibly changed.
3. `duoview/DuoViewState.hpp`: optional temporal diagnostic compares consecutive successfully composited game source frames, confirms whether the two actual constructor ViewState identities are distinct and stable, checks whether world camera pose matches exactly, and computes expected cropped-viewport static-point displacement from projection movement in source pixels. A shared ViewState or a changing source ViewState is reported as suspect. This observation does not claim to measure actual GPU velocity textures.
4. `duoview/joey_stage1/ProductionContractTests.cpp` and `duoview/stage10_state_tests.cpp`: regression assertions require instant 0.5->0.9 gaze jumps on consecutive frames, bypass of persisted 250 ms/25% settings, missing-sample state transitions, and stable-versus-shared/stale ViewStates. `verify_stage234.py` asserts UI/control and constructor hook source identity.

## What is not verified or fixed
UE's previous-frame view-projection history, TSR/Lumen temporal accumulation internals, per-pixel motion vectors, or camera-cut metadata are engine-owned and not exposed through a reliable public source-validated hook in this patch. **v24 should not be marketed as a proven total motion-vector/history fix.** CPU/WARP tests validate the specified contracts only; headset behavior is unknown.

## Diagnosis procedure
- Extract the entire v24 Windows injector in an independent test directory. Confirm true original Mono ID5 unchanged.
- Use STALKER2 DX12, SteamVR OpenXR, PSVR2 Toolkit CAPI, select experimental ID6, eye tracking ON. Keep independent shading OFF for initial test.
- Move eyes quickly left/right while keeping head still, then fixate a stationary detail and rotate head. Compare eye tracking OFF fixed center, gaze ON, and source diagnostic 2 (fovea only).
- Enable `Diagnostic: projection/history continuity` only during reproduction. Capture relevant `[DuoView][TemporalAudit]` log lines. Important fields: corrected constructor projections, unexpected view rectangles, `separateStates`, `persistentStates`, `samePose`, expected crop pixel shift.
- If actual crop follows instantaneously but interior still jumps, the remaining source of instability is likely the engine temporal reconstruction / previous projection or mismatched render frame provenance. Do not add more gaze smoothing.
- To isolate TSR where safely supported by game controls, compare temporal AA/TSR ON and OFF; restore original settings afterwards. Avoid custom patches to private UE previous-frame structures without first verifying source and a controlled test.

## Validation status
CI run 33 initially triggered from commit above and began compiling. This document is updated separately (docs-only commit) and intentionally does not re-trigger the binary build. Check CI run for final result and binary artifact.
