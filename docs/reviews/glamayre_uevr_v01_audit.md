# Independent implementation audit — Glamarye Sharpen UEVR v0.1
**Date:** 2026-10-13
**Audited source commit:** `30270eaf6b07d56fb18d02010c7558d5f4797438`
**Audited artifact:** GitHub Actions run `38388784790`, artifact `11807770314`, `Glamarye-Sharpen-UEVR-v01.zip`
**Result: FAIL — scene-image integration; PARTIAL — shader fidelity; PASS — standalone DLL packaging and synthetic DX12 smoke test.**

## Critical finding: wrong texture

In public UEVR `src/Framework.cpp`, `Framework::on_frame_d3d12` first renders ImGui into `m_d3d12.get_rt(D3D12::RTV::IMGUI)`, then invokes `mod->on_post_render_vr_framework_dx12(cmd_list, m_d3d12.get_rt(D3D12::RTV::IMGUI).Get(), &rts[0])`.
See: https://github.com/praydog/UEVR/blob/master/src/Framework.cpp

The v0.1 plugin binds this callback as `onPostDX12` in `glamayre-uevr/src/plugin.cpp` and copies/sharpens **the resource provided by that callback**. Therefore it targets UEVR's GUI render target, **not** the STALKER 2 scene image on stock/public UEVR. Whether a particular proprietary Joey fork alters this callback has not been verified. The plugin must not be claimed to sharpen the headset's scene.

The synthetic WARP test calls `g_render(cmd, artificialRenderTarget, rtv)` directly, substituting a scene-like texture. It **cannot** test which texture real UEVR actually supplies, and its successful result does not validate VR scene interception.

## Cheeky architecture mismatch

Cheeky UEVR adapter registers `on_present`, `on_device_reset`, and `on_custom_event`, **not** `on_post_render_vr_framework_dx12`. The actual Cheeky runtime also intercepts NVIDIA NGX (`NVSDK_NGX_D3D12_EvaluateFeature`) and related evaluation/resource paths in `src/hooks.cpp`. Its UEVR adapter's GPU device/queue discovery and Lua menu **do not mean** that ordinary UEVR post-render hooks see game pixels.

Reference: https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/master/uevr/plugin.cpp
Reference: https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/master/src/hooks.cpp

## Glamarye shader fidelity

Core formulas largely preserved:
- Four diagonal neighbors at offsets 0.5 / 1.4 pixels and far edge neighbors at 3.5.
- Same luminance weights, median/outlier-based sharpness, adaptive min/max bounds, smooth limit, and FXAA edge-strength suppression.
- The full FXAA smoothing pass and unrelated DOF, AO, GI were intentionally omitted.

Not equivalent to original Glamarye:
- **Color-space conversion absent.** Glamarye samples a color-corrected linear backbuffer and converts results to output encoding (hardware sRGB for SDR 8-bit, transfer functions for HDR variants). v0.1 samples using the view format and outputs unchanged encoding with **no corresponding explicit conversion**, which changes brightness-dependent sharpening and can affect colors/shimmer.
- Float HDR image normalization and `getMaxColour()` logic are not reproduced; v0.1 uses guessed max = 16 for several float formats, whereas Glamarye derives limits from HDR transfer/white level.
- v0.1 clamps output with `max(0,c+change)` and clamps FXAA ratio with `saturate`; original uses `c += sharp_diff` and `max(2*score-1,0)`. These are generally small but demonstrate it is not mathematically identical at every input.
- Different sampling bounds and assumed layout; no confirmation of view texture layout or correct stereo separation in real VR.

Original: https://github.com/rj200/Glamarye_Fast_Effects_for_ReShade/blob/main/Shaders/Glamayre_Fast_Effects.fx
Our shader: `glamayre-uevr/src/shader.hpp`

## Loader/packaging checks

- ZIP inspected: `plugins/GlamaryeSharpenUEVR.dll`, `scripts/glamayre_sharpen.lua`, README, MIT license.
- DLL is x64 PE and exports exactly `uevr_plugin_initialize` and `uevr_plugin_required_version`; these match UEVR's public ABI.
- Paths and API event names follow actual public `PluginLoader`/`LuaLoader` conventions; UEVR should be able to discover the DLL and panel if matching UEVR API version is installed.
- Real Joey runtime loader execution has NOT been tested.
- Build and HLSL compile tests passed. The WARP smoke test ran with `big=0` and `edges=0`, so it did not validate either requested feature's GPU execution; it tested a synthetic image, not actual VR scene.

## Engineering decision

**Do not ask the user to test v0.1 as a VR sharpening plugin.** The correct next step is to:
1. Select a verified **game-scene** image access path in the actual Joey/UEVR build: ideally safe access to the final OpenXR projection-layer color swapchain before submission, or an identified scene target and render-thread hook that guarantees resource state, queue ordering, and timing. The public UEVR framework UI render callback is not suitable.
2. Preserve Glamarye's color-space transfer for SDR and HDR. Match hardware sRGB behavior or equivalent decode/encode in shader; don't infer color space from only the DXGI resource format.
3. Provide golden-image numerical pixel comparisons against a ReShade Glamarye reference using matched sampler parameters, including normal and Bigger Sharpen, edge protection, brightness extremes, and SDR/HDR.
4. Add tests for native mono, Native Stereo, per-eye image arrays, side-by-side layouts, callbacks, resize/reset, descriptor reuse, and frame concurrency.
5. Preserve VR rendering quality/frametime and avoid sharpening the UI unless requested; verify in-headset only after the above.

**Conclusion:** The v0.1 binary exists and is a compilable DX12 UEVR DLL, but cannot responsibly be called a working Glamarye sharpening plugin for STALKER 2 VR.
