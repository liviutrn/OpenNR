# DuoView Joey clean integration — Stage 1 and next renderer contract
Date: 2026-10-13
Status: Stage 1 submitted to Windows CI; **not** a working DuoView renderer.

## Baseline gate closed by user
The exact Build 3 (Actions run 38453012351; commit 64432d0...) was tested by Liviu in STALKER 2 on the current setup. Original Mono ID 5 injected normally and ran **30 minutes without hitches, black screen or interruptions**. No game/runtime/Joey configuration changes were reported. This is real headset evidence for the clean control; it is not proof of any modified mode's stability.

Original baseline branch: experiments/duoview-joey-current-clean-v1 at c97c889f66835c4b3b155ea52127fbcd72610ba4.
Feature branch: experiments/duoview-joey-safe-stage1-v1 (created from that exact head).
Backend pin: joeyhodge/UEVR 5ac7edc207866569334175e4ed8a7517971547f6.
Original authorized SDK pin: joeyhodge/UESDK 3cffbc82429b6165ceec2714f0f0d9ae48f55596.
Frontend pin: joeyhodge/uevr-frontend 60be4b0f9a646109fd9fdf448bacd41477234091.

## Code-grounded integration findings
Read these exact pinned Joey files, not older UEVR forks or the public diagnostic SDK:
* src/mods/vr/MonoRenderingPolicy.hpp: method ID 5; Mono Selection defers entry, exit and startup until GPU consumers retire and the game frame commits. The common geometry represents both OpenXR eyes in one union Mono view.
* src/mods/VR.hpp lines 490–510: is_using_mono(), Mono transition readiness and generation gates; Mono-only rendering constraints and related flags.
* src/mods/VR.cpp lines 13308–13365: Mono transition present/game-thread protocol; source mode changes require coordinated retirement.
* src/mods/vr/FFakeStereoRenderingHook.cpp lines 30831–31062: GetDesiredNumberOfViews returns **one** Unreal view for Mono; GetViewPassForIndex maps actual engine passes. Lines 29863+, 29941+ and 30651+ control rect, view offset, projection matrix.
* src/mods/vr/FFakeStereoRenderingHook.cpp lines 26798–26812: Mono main-family acceptance currently requires exactly **one** view, which a future two-view mode will need to check explicitly without altering ID 5.
* src/mods/vr/D3D12Component.cpp lines 5252–5270: original Mono copies the current left scene into both OpenXR eyes through the established OpenXR copy context; this is the proven submission boundary. A true DuoView must composite a current-frame Mono result before this step, not submit peripheral and foveal views as left/right stereo images.
* src/mods/vr/CompatibilityPolicy.hpp: old serialized method enum and AFR behavior; mode 6 must explicitly remain non-AFR.
* src/mods/vr/runtimes/OpenXR.cpp: existing Mono frame, projection-history and submission gates must not be bypassed.

### Why adding ID 6 alone is insufficient
It is unsafe to treat an unrecognized ID 6 as a stereo rendering mode; that skips the Mono transition and current-frame protections. Stage 1 explicitly enrolls the new ID in the *Mono family*, preserving the original one-view path for both IDs 5 and 6. ID 6 has distinct selection/serialization/UI, but intentionally renders original Mono pixels. It is a regression-control milestone, not a performance test or visual DuoView implementation.

## Stage 1 files
* duoview/joey_stage1/apply_stage1.py — exact-anchor modifications to original checked-out Joey backend/frontend; fails if a pin or anchor changes.
* duoview/joey_stage1/verify_stage1.py — verifies the allowed changed-file set, source hashes before/after build, original SDK pin and clean SDK.
* .github/workflows/duoview-joey-stage1.yml — dedicated Windows workflow, exact SDK credential and source checkout, 41-test original suite, frontend ID tests, backend/frontend/aux DLL compile, package/evidence artifact.
* **No restricted SDK content** is stored in OpenNR; checkout is limited to CI with the configured authorized credential.
* Do not modify the baseline workflow/branch or overwrite user installations.

## Next: true fixed-center, two-Unreal-view mode (not implemented)
1. Introduce a distinct **renderer activation gate** available only for ID 6, initially disabled. Keep fallback to the proven Mono producer/submit when the new renderer is not fully initialized.
2. At a known game-frame boundary, produce one immutable snapshot of shared Mono pose, eye-union projection, current frame number/generation and render configuration.
3. Prove UE can create two *actual scene views*: peripheral full-FOV low-resolution, foveal narrower off-axis, both from the *same Mono camera pose*. Merely reinterpreting left/right stereo textures is invalid. Do not change ID 5's view count or camera offsets.
4. Validate actual view rectangles, render target extents and stereo-view pass indexing. The foveal view's projection is not simply the left eye; it must be an off-axis subfrustum in the same common basis as the peripheral view.
5. Pair both scene views by **same generation/frame/pose/config**, then compose into a single current-frame head-tracked Mono image. Verify producer completion and D3D12 resource state/ownership, command submission and fence retirement before OpenXR copy; never infer success from a queued command.
6. Preserve Joey's original OpenXR frame cadence, projection layer, reset/resize/mode-switch and post-present resource housekeeping. **Never** submit an empty XR projection frame just because the DuoView pair is incomplete.
7. First enable **fixed-center** 0.3 x 0.3 fovea; expose additional density/crop only after validating target dimensions. 0.5 x 0.5 crop at 3x linear density already implies 1.5x full-frame dimensions per axis for that cropped view, so an unchanged 1x atlas would be invalid.
8. Add PSVR2 Toolkit gaze only after paired fixed-center output and frame timing are proven. Sample validity once per frame, freeze head pose and gaze in the same reference/time basis. Invalid/stale gaze uses a predefined center fallback, not prior-frame pixels.
9. Gate CI on original 41 tests, frontend tests, mode transitions, view geometry/rect bounds, pair-frame identity, GPU-copy proof (WARP where possible), resize/reset/retirement and artifact integrity. CI is not proof of runtime stability.

## Acceptance
Original ID 0 and ID 5 unregressed; ID 6 shows two actual UE scenes with shared Mono pose; current-frame foveal/peripheral composition; gaze tracks without flicker after enabled; no 1–2 second SteamVR-room takeovers. Compare head-tracked quality/perf to Build 3 at matched output resolution and test for 10–15 minutes through a scene change.

**Handoff rule:** Keep the mode-selection milestone and the actual two-view compositor milestone clearly separate. Do not label the Stage 1 package as true DuoView.
