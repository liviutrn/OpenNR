# DuoView Mono on exact Joey — Quality recovery roadmap, 2026-10-14

## Actual user headset results: Build 19 is a PROOF OF CONCEPT
- Tested by user on PSVR2/SteamVR/OpenXR/STALKER2 on October 14, 2026.
- **Positive:** two-view rendering works, fovea moves with PSVR2 eye gaze, no periodic 1–2 second hitches were observed.
- **Failing quality:** fovea moves noticeably twitchily; peripheral image seems darker/different shading or shadows; only hard-coded quality controls, no old interface.
- No measured GPU frame-time, exact gaze age histogram, headset duration, or root-cause GPU capture was provided. Never invent these.
- **Preserve proven source:** GitHub run https://github.com/liviutrn/OpenNR/actions/runs/38525471273, source `ce9c9abc67ec0dafa48634ae7a3a443377616de5`; artifact ID `11876218971`. The older standalone original Joey Build3 is also preserved, run 38453012351, user 30-minute stable ID5.
- **Quality work branch** `experiments/duoview-joey-quality-v20`. Never rewrite proven Build19 artifact or the Build3 branch.

## Reference comparison: older (high-quality, hitching) v13/v14
- Older source is `experiments/duoview-proven-frame-pacing-v14`, plus `experiments/duoview-working-prototype-stability-v13`; its exact original source is a *different and mixed* UEVR/UESDK provenance. **DO NOT PORT ITS CORE ENGINE HOOKS**.
- Legacy source `duoview/apply_public_duoview.py` contained persisted controls for crop width/height, peripheral resolution scale, foveal pixel density, feather, PSVR2 gaze enable, debug border, foveal source view 0/1, and compositor GPU milliseconds.
- Legacy `DuoViewCompositeRaster.hlsl` is identical in principle to new Joey raster compositor; this makes "missing shader effects" a weak explanation for dark periphery.
- Legacy defaults: 50% width/height, 20% peripheral linear scale, 1.0x focal density. These defaults are NOT necessarily the user's actual old quality tuning; do not claim otherwise. New Build19 hard-coded .30/.30 crop, .25 peripheral linear, 2.5x foveal density. A smaller moving ROI makes edges more noticeable.
- Legacy CAPI used `read_orientation` and rotated gaze through `inverse(mat3(get_eye_transform(0)))` before using Mono frustum. New raw CAPI gaze uses a calibrated-native X sign mapping and frozen left Mono projection. This coordinate-basis difference requires an explicit headset alignment/calibration test; do not guess it away.
- Both old and new use temporal Unreal *different view indices* for fovea and peripheral. Independent Lumen screen traces, exposure, TAA/TSR histories, shadow culling and screen-space source resolution are plausible sources of view disagreement, not yet proven causes.
- Epic's current Lumen technical documentation says screen traces use screen depth and color and cause view-dependent GI; probe downsample and temporal accumulation are resolution sensitive. This supports targeted isolation, not blind global CVar changes.

## Quality v20 first source commit and test (in progress)
- Source commit `4450770925a6d37074b06aa26755089b935f96fd`: persisted per-profile crop width/height, peripheral linear scale, focal density, feather, gaze toggle, border toggle, and debug source 0/1/2. The main-family UE scene views remain view0 full-FOV periphery, view1 fovea; this is deliberate.
- `diagnostic_view` is latched to `FrameConfig.settings`, stored in the same 80-byte HLSL constants block. 0=original color compositor, 1=peripheral-only full FOV, 2=fovea-only high density with dark outside ROI. Both compute and raster HLSL branches have matching behavior.
- UI never directly changes the XR callback; only `State::configure` changes values for subsequent frame snapshot. An illegal atlas layout is rejected rather than partially applied. Diagnostic view allows comparing matched world locations inside ROI between view0 and view1 with no gamma patch.
- Do not expose old `fovea source view (0 or 1)` control yet because current Joey camera-producer/view-index assumptions are fixed to view0 periphery and view1 fovea; a superficial old-style control would be unsafe and nonfunctional.
- First CI #38534997678 failed early in the **old verifier** because it expected a hard-coded `.eye_tracked=true` token; the source patch applied correctly. Exact fix `80b0012102f3243f3fa0652a7ec5a5e9eabbb28c` updated the verifier to assert actual persistent UI -> frame-gaze wiring. Current CI should be queried, not presumed green.
- Be careful: a compiling build with the new controls **is not** image-quality parity. The user explicitly demands real quality engineering, independent verification and no return of periodic hitches.

## Remaining quality milestones — prioritized, no speculative all-at-once rollout

### Q1 — Correct rendering controls + fair comparison baseline
- Confirm source whitelist, UI saving/loading, all crop/density constraints, frame snapshot immutability and WARP debug-view pixel readback for 0/1/2 (new targeted tests REQUIRED).
- Confirm shader constants size/packing, no new heap or PSO allocation in XR copy callback, no change to regular Joey modes ID0/ID5.
- Runtime comparison: with tracking OFF/fixed crop, same exact scene and world-space location, switch 0 Blend / 1 Peripheral / 2 Fovea to confirm whether darkness exists in producer view, or arises at compositor seam. No global brightness/color compensation until that answer.
- Assess foveal output quality separately at matched foveal pixels; compare 0.30, 0.50 fractions and peripheral .25/.35/.45 scales while matching the game's baseline 3000x3000 or user's current SteamVR resolution.
- Verify no setting change launches resource recreation loops or invalidates current XR frame.

### Q2 — Diagnose gaze twitch, preserve responsiveness
- Current `DuoViewPSVR2Gaze.hpp`: false CAPI read is normal between hardware samples, cached sample is reused up to **50ms**, after which `read_uv` returns null. `State::begin` converts null to fixed center **in one frame**. Repeated 50ms sample-age boundary crossings could cause visible center↔eye jumps. This is a specific plausible source path, not proven without instrumentation.
- Quantify counts/age of fresh/held/invalid/blink/expired samples using atomic counters, read ONLY on diagnostic display. Don't log once per game frame.
- Verify Toolkit/native gaze coordinate transform against Joey's actual Mono optic basis and old `get_eye_transform(0)` conversion; test gaze movement independently of head movement and headset rotation.
- Prior user preference: no forced smoothing or deadzone. First fix age/cadence/coordinate bugs. If still twitchy, optionally expose bounded gaze stabilization with an explicit OFF setting, no mandatory smoothing, minimal latency, fast saccade response, and testable behavior. Avoid simply increasing stale timeout beyond 50ms without reason.
- Verify that both views and compositor use the same filtered gaze snapshot, with no new source sampling inside the OpenXR copy.

### Q3 — Real peripheral shadow/exposure parity
- Use debug-source mode to isolate fovea vs periphery for same world fragment under fixed gaze and fixed camera.
- Correlate with Unreal's per-view Lumen screen probes, screen traces, TSR/TAA temporal histories, motion vectors, VSM/shadow mask paths, fog, auto exposure and texture filtering. A low-resolution full-FOV pass may reconstruct dark GI differently.
- Compare exposure and postprocess view states. Prefer sharing coherent scene exposure/history where the UE public hook safely supports it, or aligning Unreal's per-view settings *before* render. Do not silently apply ungrounded gamma or brightness correction to the final composite.
- If necessary, investigate mode-specific conservative Lumen options in isolated experiments, with controlled A/B and performance results; no hidden global game CVar changes.
- Check source color format / sRGB semantics, RGBE/FP16 intermediate, interpolation and feathering, particularly in shadows and dark near-black. WARP constant-color tests alone cannot detect per-view shading divergence.

### Q4 — Image-quality and performance hardening
- Upsample periphery with clean sampler / optional edge-aware spatial logic only when justified; test boundary, temporal shimmer, alpha and color space.
- Actual GPU scope: cost of two Unreal views, Lumen and composite separately. Optional GPU timing, *disabled by default*, avoid polling/fences/CPU reads in live render path.
- Source completion ordering and fallback fault-frame behavior remain unproven; validate GPU resource lifetime and exposure/TSR history across crop changes.
- Never add a blocking render-thread log/file write, heavyweight shader compilation, OpenXR frame waits, or per-frame resource creation.

### Q5 — User-facing parity and release acceptance
- Restore fully functional old controls, helpful labels, valid ranges, effective resolution/pixel count and gaze state, profile persistence, meaningful feedback on rejected values; no false source-view switch.
- Run pinned production C++/WARP, independent tests, original Joey 41, complete Windows backend/frontend packaging with verified SHA and source pins.
- Then controlled headset proof: ID5 regression, ID6 0/1/2 diagnostics, twitch with eye vs head movements, bright/dark Lumen/shadows, scene changes, 30+ min no hitching. Call it quality-validated only after comparable headset evidence, not CI alone.

## Immediate source constraints
- Stage1 exact Joey backend pin `5ac7edc207866569334175e4ed8a7517971547f6`; SDK `3cffbc82429b6165ceec2714f0f0d9ae48f55596`; frontend `60be4b0f9a646109fd9fdf448bacd41477234091`.
- Use `duoview/joey_stage1/apply_stage234.py` guarded patch. Never move the old mixed backend source into the production build.
- Do not declare Q2/Q3 solved because user said first working fovea. Maintain a clear split among user-verified, CI-verified, source-reviewed, theory/unknown.
