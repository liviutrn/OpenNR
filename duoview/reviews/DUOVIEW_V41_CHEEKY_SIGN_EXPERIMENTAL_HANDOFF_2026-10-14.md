# DuoView v41 — Experimental Cheeky-Sign Foveal Source Motion Correction

**Date:** 2026-10-14. **STATUS: source committed, final Windows/package/headset status must be determined from latest dedicated GitHub Actions.** This is a concrete switchable rendering change, not a claim that STALKER 2 Unreal TSR motion vectors have been patched.

## Problem and implementation decision
- Fixed-center DuoView is user-verified stable; moving eye gaze moves the off-axis high-resolution UE foveal frustum and the user's scene appears to move with the crop.
- Previous Build33/37 reconciled **current** Unreal constructor projection but did not establish how active UE temporal passes consume the **previous** projection.
- Native NGX interception caused earlier injection CTDs and is excluded.
- v41 instead compensates **AFTER** Unreal's render/temporal passes, on the genuine high-resolution fovea atlas source via the existing **precompiled raster compositor**. The periphery source and instantaneous eye tracking are untouched.
- This is a source-backed experiment based on Cheeky's crop-origin delta sign, **not** an exact Unreal motion-vector fix. If UE temporal output is already world-locked, this adjustment would introduce additional movement. In-game A/B must determine its benefit.

## Exact new calculation
For `oldOrigin = old.u0`, `newOrigin = now.u0`, ROI width `s=now.crop_width`:
```
shiftLocalUV.x = gain * (now.u0 - old.u0) / now.crop_width
shiftLocalUV.y = gain * (now.v0 - old.v0) / now.crop_height
newFoveaTextureSampleLocal = (outputFullUV - currentROIOrigin) / ROIExtent + shiftLocalUV
```
This moves the *sampling coordinate* in the high-res foveal atlas, not the crop. Example 3000² output, 30% crop, density2.5 => 2250² UE fovea source; +0.02 full UV => +150 source pixels in sampling, for gain1. It is the current-to-previous sign used by Cheeky `src/crop_motion.hpp`.

## Lifecycle safety and fallback
- `State::consume` only computes candidate history offset from last accepted adjacent XR copy. 
- `State::accept_composite` is called only after both `m_openxr.copy` and the DuoView GPU recording callback return success. **Copy acceptance is NOT a fence or Unreal temporal commit; do not infer either.**
- No offset when baseline fixed center, eye tracking disabled or invalid, missing consecutive accepted source frames, change in source index, source fovea size/atlas, change in crop extents or >25% foveal-width saccade.
- High-density atlas still originates from separately rendered UE fovea view; no low-res periphery is enlarged.
- GPU HLSL samples only inside valid fovea rectangle via existing bounded `AtlasSampleUV`. At new exposed border samples feather to peripheral source instead of stretching clamped edge texels. Zero offset is the previous exact shader path.
- No NVAPI/NGX hook, unknown Unreal offset, global motion-vector write, memory search, new render-time shader compilation, per-frame allocations or render-thread logging.
- UI **Experimental gaze image motion correction**: ON by default in new v41 UI; **strength 0** or **OFF** immediately restores unshifted previous sampling on the next frame. Independent primary shading remains OFF at mode reset.

## Source touched (diff against frozen v40)
- `DuoViewHistoryCorrection.hpp`: pure current→previous bounded offset function.
- `DuoViewConfig.hpp`: latched A/B bool, 0–1 strength, per-frame source local shift.
- `DuoViewState.hpp`: strict previous accepted frame, one-shot offset creation.
- `DuoViewComposite.hlsl`, `DuoViewCompositeRaster.hlsl`: GPU sampling shift and source-validity feather.
- `DuoViewD3D12.hpp`: root constant structure 80→88 bytes, root signature resized, no new shader compile in live XR.
- `joey_stage1/apply_stage234.py`: added control/UI/packaging of helper and `accept_composite` call.
- `joey_stage1/apply_native_lowres_bootstrap.py`: exact anchor updated to keep existing post-compose Native0 resolution restore.
- `joey_stage1/ProductionContractTests.cpp`: sign/gap/saccade/cut controls, gain, fixed-center.
- `joey_stage1/ProductionWarpPinned.cpp`: actual GPU pixel gradient source delta plus two-eye parity.
- `joey_stage1/verify_stage234.py`: locks new generated code/paths.
- `joey_stage1/audit_v41_package.py`: independent archive unzip roundtrip and DLL x64 checks.
- Dedicated `.github/workflows/duoview-joey-stage234.yml` branch + v41 artifact naming + experimental READ_FIRST warnings.

## Mandatory acceptance / remaining uncertainty
1. Verify pinned exact SDK/backend/frontend and Build3 controls, Python patch order, generated backend diff.
2. Verify Windows pinned C++ contracts, gaze CAPI tests, WARP gradient DXBC/HLSL, full original Joey compatibility tests, Windows backend/frontend, ZIP SHA/PE audit.
3. Independently check exact produced artifact contents and report full commit + artifact ID/hash. No headset link before complete gates.
4. Headset A/B: **fixed center** baseline, then tracked gaze with correction OFF→ON (strength 1 and if needed 0.5), fixation while rotating head, small pursuit and saccades, blink tracking loss, compare frame pacing and high-res fovea. Turning correction OFF remains exact fallback.
5. Genuine UE previous temporal matrices, motion vectors and TSR history are STILL unobserved. Even a strong A/B headset outcome does not magically verify UE internals. If ON overcorrects, do not double it; root cause must be investigated using validated engine instrumentation.

**No claim of success without headset acceptance.**

## Independent audit amendment
- After initial v41 CI, `apply_native_lowres_bootstrap.py` failed its strict D3D12 anchor because the new accepted-copy call was inserted between two old anchor lines. **Fixed** by updating that exact replacement to preserve Build37's `note_duoview_bootstrap_composite()` after the new accepted-copy call. This was a patch generation fault; no headset binary from that run.
- New `DuoViewState.hpp` compatibility gate additionally requires SAME NONZERO foveal `FSceneViewStateInterface*` identity and rejects per-axis camera rotation discontinuities >45 degrees or position jumps >500 Unreal units. New pinned tests explicitly check changed ViewState and camera teleports disable the optional correction.
- v41 full source/build ZIP belongs to dedicated workflow `.github/workflows/duoview-joey-stage234.yml` (renamed per-branch) and must be checked against its own exact commit before distribution. Older v39/v40 successful CI or Build37 artifacts are not a v41 validation.

## Actual regression caught by Windows CI and corrected
- Run `38636491648` caught **two genuine test failures** in v41 prior to release: the new `FrameConfig.history_sample_offset{}` inherited `UV`'s gaze-centered default `(0.5,0.5)`, so **every** frame was shifted half a fovea even without a compatible prior. The source contract test failed "First copy must be unshifted"; WARP's original red/blue compositor pixel test failed "Production compositor pixels wrong".
- Commit `0da733a67d05571dd17600aeef2a0a6411b9354a` explicitly changed the offset initializer to `UV history_sample_offset{0.f,0.f}`. The corrected pinned CPU and actual D3D12 WARP tests passed in dedicated run `38636899230` at this checkpoint. Its broader original Joey build and final package audit remained pending when these findings were recorded.
- Do not revert that explicit initializer or replace it with `UV{}`. This is a dangerous type-specific regression trap for any future sampling-offset field.
