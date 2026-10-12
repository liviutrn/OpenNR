# DuoView Mono — integration handoff (v05)

## What is actually complete

These components are implementation code with reproducible Windows tests,
not yet a usable VR injector:

- Joey UEVR patch Stage 1/2 on a pinned upstream commit; new method ID 6,
  two engine views with same centered pose, unequal foveal/peripheral
  rectangles, clipped off-axis projection for foveal view.
- `DuoViewGeometry.hpp`: frame layout, crop and tangent-plane math.
- `DuoViewGaze.hpp`: optical gaze-ray mapping, no position smoothing, 50ms
  validity cache (actual PSVR2 API wiring is pending).
- `DuoViewConfig.hpp`: settings/gaze snapshot latched once per frame.
- `DuoViewFrame.hpp`: paired render-view and GPU-fence validity gating.
- `DuoViewComposite.hlsl`: standalone compute compositor.
- `DuoViewCompositeRaster.hlsl`: fullscreen raster compositor,
  RGBA/BGRA texture reads, BGRA8 render-target writes.
- `DuoViewMonoCopyD3D12.hpp`: takes *single-eye-width* BGRA8 source and
  copies it to BOTH halves of a *double-wide* BGRA8 destination.
- `DuoViewWarpTest.cpp`: DX12 WARP rendering, shader dispatch and GPU
  readback; fully separate from UEVR/UESDK.

No VR headset validation, no game frametime measurements, and **no full
UEVR binary build yet**. Neither shader has been wired into Joey's
production DX12 submission callback.

## Frozen upstream and access blocker

Backend: `joeyhodge/UEVR` at
`db6729dd9f5745705b1cdec2ec6f51bdc9570983`.

Backend references `joeyhodge/UESDK` gitlink
`2ad9fefa67eb69634b9a1252f4b99876f5333671`.
The signed-in GitHub app cannot access that submodule; the public 2024
Aeyth8 UESDK is missing numerous Joey-required SDK headers.

Workflow `.github/workflows/duoview-stage5.yml` source and graphics tests
run without restricted files. Its UEVR binary build remains deliberately
gated by the Actions repo variable `DUOVIEW_FULL_BUILD=1` and requires
authorized access via repo secret `UEVR_SOURCE_TOKEN`.

## Exact source integration seams

1. **Engine view generation:**
   `src/mods/vr/FFakeStereoRenderingHook.cpp`:
   `get_desired_number_of_views_hook` and `adjust_view_rect` allocate
   two views and their actual foveal/peripheral rectangles.
   `calculate_stereo_view_offset` retains zero IPD; the projection
   hook applies off-axis crop only for foveal view.

2. **Freeze one snapshot:** Acquire a `ConfigLatch::for_frame` snapshot
   once *before* the first `CalculateStereoProjectionMatrix` call.
   Reuse that EXACT snapshot for the second UE pass, the compositor shader
   constants and the frame's OpenXR presentation. Do not read or change
   gaze separately for each stage; that caused DLSS5 regeneration in previous
   experiments. Current Stage-2 hook still recalculates a fixed-center
   layout, so this wiring is outstanding.

3. **Pair actual completed renders:** `DuoViewFrame.hpp` must receive
   genuinely completed UE views, NOT just `GetDesiredNumberOfViews`,
   `AdjustViewRect`, or view-family construction notifications.
   Two scene completions alone do not prove reduced shading cost:
   verify the G-buffer, HZB, Lumen, shadow and postprocessing passes on GPU.

4. **Composer placement:** `src/mods/vr/D3D12Component.cpp`, near
   lines 5003–5018 at the pinned commit, currently dispatches
   `uevr::mono::dx12::copy_scene` inside the OpenXR double-wide copy
   command-list callback. That is the intended seam for DuoView, but the
   *existing original Mono branch must remain exactly unchanged*.

5. **Color/present contract:** The original `MonoD3D12::copy_scene`
   accepts a **double-wide source** the same width as the OpenXR destination
   and both source/destination in BGRA8. Our compositor produces a complete
   **single-width** BGRA8 image. After drawing the full-screen triangle to
   a dedicated single-width BGRA8 RTV, the additional
   `duoview::dx12::copy_composite_to_stereo` takes the image and duplicates
   it into each eye region. It validates same D3D12 device, resource flags,
   sample count, BGRA8 layout and dimensions. The original Mono copier is
   not modified.

6. **D3D12 lifetime and sync:** The atlas may be RENDER_TARGET state when
   handed off, but do not assume it universally. Query/use Joey's
   `scene_source_state` observation. Transition atlas to
   PIXEL_SHADER_RESOURCE, raster output to RENDER_TARGET, then restore
   states according to the owning command-list and resource-manager contract.
   Only mark the `FrameCoordinator` composite ready when the true GPU fence
   signals; retain atlas, composite RTV and destination until their consumers
   retire. Do not read from and draw to the same resource.

7. **OpenXR gating:** On invalid source, missing view, invalid projection,
   lack of shader/RTV, failed resources, stale gaze, or stage teardown,
   submit an empty/waiting frame with diagnostic status rather than copying
   a previous frame. Guard fast transition ID 5 <-> ID 6.
   Ensure `note_mono_copy` and `has_mono_frame` validate the new
   two-view compositor and do not mistake view-family count for completion.

8. **PSVR2 gaze:** The user's proven native PSVR2 Toolkit CAPI bridge is
   stored in `liviutrn/OpenNR` branch `experiments/cheeky-psvr2-r10`,
   file `CheekyPort/overrides/openxr_layer/psvr2_native_gaze.hpp`.
   Port only with verified transformation from headset-calibrated gaze
   orientation into Joey Mono's common left-optical frustum; then
   `ray_to_uv` and `ConfigLatch`. False CAPI reads may mean 'unchanged'
   (re-use up to 50 ms), not lost tracking. Do not guess display pixel FOV.

9. **Gameplay quality:** Two UE render views with different resolutions
   might not produce equivalent exposure, TAA/TSR history, fog, Lumen,
   shadows or particle temporal stability. GPU and HMD captures must
   validate both views before marking the renderer usable. Disable/fail
   closed if auxiliary view counts or unsupported engine paths are detected.

## Current test coverage

- Source patch strict-anchor application; historical ID 0–5 regression.
- C++ 50% and 30% crop calculations, off-axis projection, feather weights.
- Head-tracked gaze-to-Mono-frustum coordinates and stale-frame policy.
- Immutable settings/gaze/frame consistency and GPU-fence submit gates.
- Windows MSVC compilation and tests.
- DX12 WARP compute output and BGRA8 RTV raster output readback:
  center red [255,0,0], corner blue [0,0,255], feather [43,0,212].
- DX12 WARP single-width-to-double-wide stereo-copy duplicate and actual
  pixel comparison, with the same resource format as Joey's Mono path.

**Do not claim rendering or headset performance gains until a full
UEVR Windows DLL is built and instrumented inside STALKER 2.**
