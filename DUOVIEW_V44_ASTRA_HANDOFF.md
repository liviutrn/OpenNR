# DuoView v44 handoff for independent Astra review

**Review request:** independently verify the v44 moving-crop / temporal-motion reasoning and implementation. Do not assume the implementation is correct because its tests pass. Review the source and challenge the engine-history assumptions. Please report concrete defects, unsupported claims, and any safe correction that can be verified from the available source. Do not modify the branch.

## User’s problem

The eye-gaze crop moves while the head and world stay still. The final full-view image should therefore have no crop-only motion: a stationary world feature stays at the same output-screen position. The high-resolution fovea buffer is different: because its crop origin moved, that same feature lands at a different local texel. Temporal reconstruction needs a correct current-to-previous relationship in that source buffer. This is the distinction v44 is meant to handle.

For a crop with normalized full-view origin `origin` and extent `cropExtent`, a stationary point’s expected crop-local current-to-previous displacement is:

```text
localUV(current → previous) = (currentOrigin - previousOrigin) / cropExtent
sourcePixels = localUV * foveaSourceDimensions
```

The direction is positive when the crop origin moves right/down. This is a crop-local buffer contribution, not apparent movement in the final full-view raster. Check the direction against the actual UE velocity convention and account for viewport scale, jitter, and temporal upscaler units before calling it a production motion vector.

## What changed in v44

- Reverted v43’s gaze-as-camera-rotation/homography path. Both UE views keep the canonical head pose; the gaze moves the foveal projection crop at the view-construction hook.
- Removed the compositor’s experimental post-render RGB/sample shift. Current foveal color is mapped back through the current crop origin, so a crop move alone should keep a static world point fixed in output space.
- Added `duoview/DuoViewCropMotion.hpp` to calculate the expected crop-local vector for diagnostics and tests. **It does not write or modify Unreal motion-vector buffers.**
- Added frame-history checks in `duoview/DuoViewState.hpp`: both views need distinct per-frame state identities, and the foveal state/selector/layout and adjacent frame history must be compatible before eye-tracked composition is accepted. The new `composition_ready` latch also prevents a frame rejected by that gate from later being marked as an accepted XR copy.
- Added gaze sample arrival/validity metadata. Reader cache reuse no longer renews sample age; explicit invalidation clears the crop target immediately.
- Updated the UI/log audit fields and package test scripts to call this v44 and report the expected crop-local vector separately from final-screen motion.

## Main unresolved question — please focus here

The current theory is that a persistent, dedicated UE `ViewState` for the foveal view sees the previous and current crop projections and that Unreal then emits the needed crop-local velocity itself. v44 deliberately does not write private Unreal previous-matrix/history memory or add an OpenNR-style crop delta on top, since that could double-correct if UE already owns the projection change.

That theory is **not yet demonstrated**. The pinned UESDK exposes current projection setup and a `ViewState` identity, but the current source audit has not established which previous clip transform, jitter, viewport, and velocity units STALKER 2’s active TSR/DLSS/Lumen paths actually consume. A stable pointer and a successful render hook do not prove correct previous projection or vector generation. Please assess whether the crop projection is changed early enough for the engine to persist it as previous-view state, or whether a later renderer-owned hook/API is required. If the source cannot prove that, say so plainly; do not suggest guessed offsets or an unsafe extra correction.

## OpenNR reference and why it is limited

The v43 review found that OpenNR r10’s `NativeOpenVRGaze.cpp` controls its own reconstruction history: it caches/fixes gaze and resets its owned SR/NR histories when the crop origin changes. `CameraReprojection.h` computes current/previous transforms inside that pipeline. This is a useful general example of keeping crop and reconstruction history coherent, but it is not a portable Unreal previous-projection repair: OpenNR owns those histories, DuoView does not.

## Regression context from v43 review

Read `duoview/reviews/V43_ADVERSARIAL_REVIEW_2026-10-15.md` and `duoview/reviews/DUOVIEW_V43_GAZE_CAMERA_ENGINEERING_2026-10-15.md` along with the changed source. The adversarial review called v43 plausible but unproven, and identified (a) off-center fixation-density loss from rotating the foveal camera, (b) up-to-100-ms composed gaze caching, and (c) temporal diagnostics that did not reflect actual foveal camera motion. V44 reverts camera steering and carries the original gaze sample age. It does not establish that these were the user’s root cause.

## Current source and builds

- Branch: `experiments/duoview-gaze-motion-vectors-v44`
- Current code commit: `bde264fa58e71a32d0e50285d7d661076f4bfa6a`
- Windows run #72: https://github.com/liviutrn/OpenNR/actions/runs/38695937854
- As of this handoff, the pinned production geometry/history contracts, DX12/WARP tests, and original compatibility stage passed. The full matching backend build step was still running. No v44 test ZIP had been produced yet.
- Earlier run #70 exposed an over-tight float-only assertion tolerance; run #71 exposed that a gate-rejected frame could still be accepted by `accept_composite`. Both were corrected before run #72.
- Local GCC checks passed, including the independent foveal temporal oracle over 17,280 deterministic projection pairs. The local production-contract executable was also run with a temporary shim only for its separate Mono bootstrap contract; run #72 is the authoritative Windows/pinned-backend check.

## Files to inspect first

1. `duoview/DuoViewState.hpp` — moving projection-history gate and composition acceptance state.
2. `duoview/DuoViewCropMotion.hpp` and `duoview/tests/FovealTemporalOracle.cpp` — crop-local sign/scale oracle and limitations.
3. `duoview/joey_stage1/apply_stage234.py` — actual generated hook points and current projection mutation timing.
4. `duoview/joey_stage1/ProductionContractTests.cpp` and `ProductionWarpPinned.cpp` — what Windows tests do and do not establish.
5. `duoview/reviews/DUOVIEW_V44_MOVING_CROP_MOTION_HISTORY_2026-10-15.md` — implementation rationale and explicit limitations.

Please distinguish four outcomes in your review: mathematical crop-vector correctness, source-hook correctness, actual Unreal temporal-history behavior, and physical headset/game validation. The first two have test coverage; the latter two remain unverified until runtime evidence exists.
