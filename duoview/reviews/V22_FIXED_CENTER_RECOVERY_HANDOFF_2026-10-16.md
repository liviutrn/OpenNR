# Joey DuoView v22 — fixed-center recovery checkpoint (2026-10-16)

This branch is **EXPERIMENTAL / NOT READY FOR HEADSET RELEASE**. Do not replace verified Joey Build 3. No performance, quality, startup or runtime-stability claims are made until STALKER 2 tests prove them.

## Exact source lineage
- Repository: `liviutrn/OpenNR`
- Base branch: `experiments/duoview-temporal-shading-v22`; isolated recovery branch: `experiments/duoview-joey-v22-fixed-center-recovery`
- Windows Actions workflow: `.github/workflows/duoview-joey-stage234.yml`
- Original pinned Joey backend: `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`
- Authorized unchanged SDK: `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`
- Matching frontend: `joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091`
- User-verified 30-minute original Joey Mono reference: Build 3 / Actions run `38453012351`. Preserve it untouched.

## Changes committed in recovery branch
1. `DuoViewConfig.hpp`: fixed-center mode default; finite in-range vertical center `fixed_center_v` (0–1), immutable per-frame configuration.
2. `DuoViewState.hpp`: fixed-center gaze bypasses reader entirely and uses `UV{.5f, fixed_center_v}`.
3. `apply_stage234.py`: persistent vertical slider; hidden eye tracking UI; hard production `eye_tracked=false`; independent primary-shading constructor override disabled; original source modes 0/5 unchanged. One-shot STALKER2 DX12/OpenXR request for mode 6 on first ready engine tick. Subsequent user mode selections honored.
4. `verify_stage234.py`: source policy requires no live gaze producer and no experimental primary-shading constructor adaptation.
5. `ProductionContractTests.cpp`: fixed-center must not invoke gaze provider, must latch correct vertical value, must reject out-of-bounds control.
6. `stage10_state_tests.cpp`: legacy gaze/smoothing helper tests explicitly opt in to eye tracking, while shipping DuoView remains fixed-only.
7. Isolated Windows workflow runs; first run #110 failed solely because a legacy independent test expected gaze on by default; patched test on branch, later CI runs supersede #110.

## Critical blockers — not yet solved
1. **Native Stereo Fix parity**. Joey's `VR::is_native_stereo_fix_enabled()` on pinned source uses `RenderingMethod::NATIVE_STEREO`, not DuoView ID6, so enabling the standalone experimental primary-pass override would not reproduce Native Fix. Pinned hook `FFakeStereoRenderingHook.cpp` FSceneView constructor logic (approximately lines 23191–23275) conditionally requires **generation-valid native scene-capture target** and coordinates secondary-pass identity, same-pass relabeling and FSceneViewFamily list masking. Native Fix itself forces same pass for validated STALKER2 (VR.cpp near line 3994). Blindly changing one pass flag or making `is_native_stereo_fix_enabled()` true globally is unsafe: many renderer/copy/submit paths depend on that predicate. A dedicated source-pair Native Fix transaction, distinct from output submission, must be designed and audited.
2. **Unwanted Mono fallback**. `duoview_abort()` currently quarantines the two-view renderer, and the D3D12 XR-copy callback has an emergency original-Mono copy when a frame pair is incomplete. This violates the user's explicit no-automatic-fallback requirement. Do not simply delete the safety copy or quarantine: first fix frame/view-family readiness so complete current-frame pairs are reliably produced; then design a safe deterministic error frame policy that does not silently switch methods or submit stale images.
3. **OpenVR**. Current DuoView mode6 is gated by OpenXR, and the DX12 compositor is wired into the OpenXR double-wide copy. Generic Mono policy itself is OpenXR-only. Native SteamVR/OpenVR requires a real corresponding source registration and compositing/presentation implementation, not just removing the OpenXR gate.
4. **Startup**. Recovery now requests ID6 once after DX12/OpenXR becomes ready and does not override subsequent manual selections; this has not been proven to happen before unsafe native-stereo high-resolution allocation. User mentioned optional temporary 10% screen percentage then restore. Implement only with safe CVar snapshot/revert and a render-thread-safe startup state machine; do not write r.ScreenPercentage in a hot XR copy callback.
5. **Crash/stability**. Audit texture/command-context lifetimes, per-frame source-key ordering, view-family construction, swaps/reset/recreate, XR layer behavior and 6DoF head pose against known STALKER2 injection/head-locked failures. Windows compilation and WARP tests cannot substitute for headset validation.

## Required release gates
- Check *latest* workflow run for branch and first failing step; keep original Joey source, matching frontend and private UESDK pins intact.
- Dedicated static tests for mode-6 autostart/manual override, no gaze reader calls, immutable crop, Native Fix *actual* secondary source path, correct two-view pairing under render-target resize, absence of Mono fallback and OpenVR mode transition.
- Pass full pinned Windows backend/frontend compilation, original Joey compatibility tests, independent Direct3D12 WARP tests, and source/package hash audit.
- Real STALKER2 DX12 OpenXR and OpenVR headset tests for proper 6DoF, native-fix-level Lumen/shadow equivalence, no room takeovers, 30-minute stability and performance. Mark releases as unverified until that happens.

## CI
- Recovery workflow: https://github.com/liviutrn/OpenNR/actions/workflows/duoview-joey-stage234.yml
- Run #110: https://github.com/liviutrn/OpenNR/actions/runs/38888304642 (independent legacy default-gaze unit test failure; fixed in later commits)
- Run #113: https://github.com/liviutrn/OpenNR/actions/runs/38888693890 (check completion and artifact before claiming success)


## Recovery implementation update — October 16, 2026, later checkpoint

**Source integration:** Recovery source HEAD before this documentation update: `feeb8f88dc10516887a44eb26e9ed88e8824a786`. Pinned Windows run #127: https://github.com/liviutrn/OpenNR/actions/runs/38893275956 (status requires independent check).

### Committed work after first recovery checkpoint
- `DuoViewState.hpp`: `can_native_fix_secondary_source` demands exact frame key, camera, both view rectangles and projections, distinct non-null source ViewStates and no consumed/invalid frame.
- `apply_stage234.py`: temporary SECONDARY->PRIMARY constructor pass relabeling **plus temporary mask of existing UE view-family singleton**, restored using Joey's existing constructor cleanup and guard. This models the **source-construction** part of Joey Native Stereo Fix without globally enabling Native Fix's capture/copy/submit path. It is NOT proven visually equivalent; further in-headset Lumen/shadow comparison is mandatory.
- `apply_stage234.py`: removed internal DuoView quarantine and emergency original-Mono copy. Incomplete frame now remains ID6 and does not send a falsely labeled current-frame Mono scene. This can visibly interrupt VR if source pairs remain invalid; diagnostics are critical. No assertion of uninterrupted runtime is made.
- OpenVR integration: mode6-specific capability override, automatic selection after the SteamVR runtime is ready, OpenVR-specific source-frame gate and DX12 composer feeding both SteamVR pose-aware per-eye textures. Original Joey ID0 and ID5 modes retain their normal paths.
- OpenVR optical calibration: `src/mods/vr/runtimes/OpenVR.cpp` computes a binocular common Mono perspective with `uevr::mono::geometry`, including canted-eye rotations and per-eye view bounds. Safe rendering-mode transactions invalidate OpenVR projection caches to switch between regular stereo and shared Mono frustum.
- OpenVR output lifetime: explicit DX12 command-context/source-user retirement before reallocating and releasing compositor output.
- Source verifiers and independent pinned tests check fixed vertical center, no live gaze consumption, dedicated constructor validity, optical union geometry and source-code integration.

### Remaining verification requirements
1. Verify #127 full Windows build passes. Earlier #113 succeeded **before** these later runtime changes, so it is not evidence of #127 correctness.
2. Audit the final injector package SHA and whether the OpenVR optical projection is correctly applied on first injection/transition, followed by 6DoF and dual-view actual current-frame compositing.
3. Confirm whether the temporary view-family singleton mask actually restores Native Stereo Fix-equivalent Lumen/shadow behavior in STALKER 2; source-contract tests cannot prove rendering parity.
4. Test missing-frame behavior, level transitions, DLSS changes, resolution changes, repeated injections and device/swapchain reset. No silent fallback is guaranteed by source logic, but consecutive missed frames may suppress VR scene submissions.
5. Test native SteamVR/OpenVR separately from SteamVR OpenXR: original Joey Mono only supported OpenXR, so this new branch is a substantial new integration and has not yet been user-tested. Validate runtime bounds, pose-space, IPD, canted eye and visual stitching against both-eye headset observation.
6. Do not overwrite or replace proven Build 3. Never label this candidate production stable until test observations justify it.

### Links
- [Recovery branch](https://github.com/liviutrn/OpenNR/tree/experiments/duoview-joey-v22-fixed-center-recovery)
- [Latest Windows workflow](https://github.com/liviutrn/OpenNR/actions/workflows/duoview-joey-stage234.yml)
- [Full run #127](https://github.com/liviutrn/OpenNR/actions/runs/38893275956)
