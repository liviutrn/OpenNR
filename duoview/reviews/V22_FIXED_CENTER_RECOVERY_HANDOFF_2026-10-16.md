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
