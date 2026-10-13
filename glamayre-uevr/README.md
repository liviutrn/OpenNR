# Glamarye Intelligent Sharpen for UEVR — experimental v0.3 (Joey OpenXR/DX12)

**Status:** Windows GPU tests are automated; **actual STALKER 2 + Joey + PSVR2 runtime is unverified**. This is a new OpenXR game-scene integration, not a proven in-headset release.

## What changed since v0.2

- Based on the real STALKER 2/Joey UEVR log of 2026-10-13, which confirms plugin loading but no visible sharpening in headset.
- Adds a fail-closed identification of the headset scene color swapchain by the exact UEVR hmd eye dimensions when projection layers cannot be observed. Rejects unknown formats and all UI/depth extent mismatches.
- If no loader-export xrReleaseSwapchainImage calls occur for four seconds, also attempts to hook function pointers obtained from xrGetInstanceProcAddr for Joey builds that may use cached runtime dispatch; the two hook paths suppress nested duplicate callbacks.
- Adds counters for native menu settings, loader and runtime hooks, Acquire, Release, EndFrame, projection detection, dimension detection, eligible copies, and recorded rendering. Native logs report these every ten seconds.
- Adds a TEST ONLY red grid checkbox under Diagnostics, disabled by default. The red grid must be visible inside the PSVR2 if the image submitted to the headset is modified.

## What changed since v0.1

The previous `on_post_render_vr_framework_dx12` callback affects **UEVR's ImGui/UI layer, not the headset scene**. v0.2 removes that callback entirely.

The new integration tracks actual **OpenXR projection-layer color swapchains** by observing `xrEndFrame` composition layers. It hooks `xrAcquireSwapchainImage`, `xrReleaseSwapchainImage`, `xrEndFrame` and `xrDestroySwapchain` on the OpenXR loader exports using UEVR's public inline-hook API.

In the public UEVR DX12 implementation, `D3D12Component::OpenXR::copy` submits scene color to the headset's swapchain on the application's D3D12 graphics queue, then calls `xrReleaseSwapchainImage`. In its release hook, this plugin schedules a **separate DX12 draw** to sharpen that exact projection image on the **same graphics queue** before forwarding to the real OpenXR release function. Ordered queue submission avoids GPU fence stalls in normal frame processing.

**Caveat:** runtime dispatch via cached `xrGetInstanceProcAddr` pointers, alternate UEVR forks, or other OpenXR API layers may bypass the loader export detours. The menu reports whether hooks are installed and counts processed scene images, but genuine headset content must still be visually verified. It intentionally does nothing when the route cannot be established.

## Installation

1. Close STALKER 2 and UEVR.
2. Remove the old **v0.2** `plugins/GlamaryeSharpenUEVR.dll` and `scripts/glamayre_sharpen.lua` first.
3. Extract the new ZIP to the game's UEVR profile: `%APPDATA%\UnrealVRMod\<game-executable-name>\`.
4. Keep folders: `plugins/GlamaryeSharpenUEVR.dll`, `scripts/glamayre_sharpen.lua`.
5. Start STALKER 2, choose **UEVR OpenXR + DX12** with your Joey build, and inject.
6. Open **LuaLoader → Glamarye Sharpen**. Check the OpenXR hook diagnostic, then enable. Suggested: strength `0.4`, Bigger Sharpen on, "Sharpen jagged edges less" on, limit `0.10`.
7. A nonzero "Processed scene images" counter shows recorded/scheduled GPU draws, not necessarily confirmed visual improvement. Turn sharpening off immediately for unexpected image artifacts or hitching.

This plugin changes neither Joey's mono/native stereo rendering method nor DLSS's NGX hooks; it should be installed **alongside** existing Cheeky components, not as a replacement.

## Preserved Glamarye features

- Original 4-diagonal Intelligent Sharpen median/outlier formula.
- Bigger Sharpen offsets `0.5` and `1.4`, with corresponding weighted neighborhood.
- Original FXAA-derived edge detector with `3.5`-pixel distant samples; edge attenuation only, **no full FXAA smoothing**.
- Reinhard-like adaptive sharpness bounds and configurable maximum change, plus bias control.
- SDR linearization/encoding via hardware for DXGI sRGB render-target views; explicit accurate sRGB conversion for UNORM inputs; scRGB scaling uses Glamarye's 203-nit diffuse white reference. HDR10 PQ/HLG **not currently supported** and does not activate on their native DXGI formats.
- Preserves source image alpha and keeps the sharpening samples within separate eye regions for double-wide composition layers.

The shader adaptation doesn't include AO, Fake GI, DOF or full FXAA because they are outside the requested sharpening-only functionality.

## Safety and supported formats

- **OpenXR/D3D12 only.** OpenVR not supported by the new swapchain route.
- Only two-view **projection layer** images identified at a prior OpenXR `xrEndFrame` are processed. UI quad layers, arbitrary color textures and depth buffers are skipped.
- May take one additional frame to identify projection swapchains. Dynamic view changes may take effect on the next frame.
- Supports BGRA8/RGBA8 sRGB or UNORM and RGBA16_FLOAT projection images. Unsupported formats fail closed.
- Uses a separate GPU allocator/list/fence per swapchain image. If previous GPU work isn't finished, it skips rather than blocking. On swapchain teardown, it may wait up to 5 seconds to drain work.
- UEVR's scene copy and sharpening both submit to the same command queue to preserve ordering. The plugin assumes UEVR's DX12 projection images are `D3D12_RESOURCE_STATE_RENDER_TARGET` at release, as verified from the public UEVR source.
- Registers hooks transactionally and rolls back partial installations when possible.
- No CPU readbacks, no per-frame mutex waits on GPU fences, no eye tracking or motion vectors.
- Settings saved to `GlamaryeUEVR.ini` in the game's UEVR profile.

## What testing does and doesn't prove

Windows CI compiles the DLL, compiles the embedded HLSL with FXC warnings-as-errors, and uses Microsoft WARP to execute a real DX12 shader pass with Bigger Sharpen and edge protection turned on.

**These tests do not actually launch UEVR or verify headset frames.** The OpenXR hook will need testing against Joey's actual build and SteamVR OpenXR runtime. Important checkpoints: nonzero scene image counter, sharpening visible in both eyes, correct relative image positions, no duplicate/frozen images, and stable frametime.

## Attribution

Main source: [Glamayre Fast Effects](https://github.com/rj200/Glamarye_Fast_Effects_for_ReShade) by Robert Jessop (MIT, license included). The C API `vendor/uevr/API.h` is from praydog UEVR (MIT). Cheeky Foveated DLSS inspired the UEVR plugin and Lua integration patterns; no Cheeky binaries or source code are redistributed.

## How to interpret the diagnostic log

Search the newest UEVR log for `[Glamarye v03]` lines. `settings=0` even after toggling controls indicates the Lua-to-native event path failed. `xrRelease=0` and `xrAcquire=0` means no hooked swapchain callbacks are firing; check `xrResolved` to see whether the cached runtime fallback attached. Nonzero Acquire/Release but zero `xrSize` and `xrProj` means the OpenXR projection images were not recognized. Nonzero `xrEligible` but `xrFrames=0` means command-list submission or GPU setup refused. If `xrFrames` increases but the red grid does not appear, the processed color image may not be the final display image or the GPU work may be overwritten. This is an experimental test, not a verified headset release.

The attached test log also showed unrelated DuoView mode switching and intermittent OpenXR time errors; those are not proof that Glamarye caused them. Avoid changing Joey's rendering mode while doing a controlled sharpening A/B test.
