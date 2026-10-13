# Glamarye Sharpen for UEVR — OpenXR v0.3 Stable Candidate

This build retains **two distinct DLLs**, based on the architecture of Cheeky's separate OpenXR layer and UEVR plugin:

- `layer/GlamaryeOpenXRLayer.dll` — genuine Khronos implicit OpenXR API layer, loaded through the application's OpenXR loader (including Joey's statically linked loader).
- `plugins/GlamaryeSharpenUEVR.dll` — a game-local UEVR C++ plugin implementing Glamarye Intelligent Sharpen in D3D12 and receiving the Lua controls from `scripts/glamayre_sharpen.lua`.

**Previous v0.1–v0.4 used a broken external `openxr_loader.dll` hook and did not sharpen the scene.** This version no longer hooks any loader exports. The API layer observes `xrCreateSession`, `xrCreateSwapchain`, `xrAcquireSwapchainImage`, `xrEndFrame`, `xrReleaseSwapchainImage`, and destruction through the supported Khronos chain. It identifies headset scene images from **projection layers**, not texture dimensions or UI. Once recognized, it records the existing Glamarye GPU shader into the projection image after UEVR's DX12 copy and before the real OpenXR release on the same queue. It does not change Joey or its DLSS code.

## v0.3: Four independent sharpening scales and opt-in GPU timing

This is based on the **working** v0.1 Khronos OpenXR API-layer architecture. No Joey backend, OpenXR loader, DLSS hooks, or injection paths have been changed.

### Sharpening controls

All radius bands have independent strengths **0 to 5**, and zero means that band performs no neighborhood sampling:

| Band | Radius | Default | Notes |
|---|---:|---:|---|
| Small | 0.5 pixels | 0 | Glamarye's original normal mode |
| Big | 1.4 pixels | 0.4 | Glamarye's original Bigger Sharpen |
| Extra Big | 2.5 pixels | 0 | Experimental, broader contrast |
| Ultra Big | 5.0 pixels | 0 | Experimental, very broad contrast and possible halos |

Bands combine in **one fullscreen GPU pass**, each reading the original, unsharpened source. Their contributions are added and bounded by the existing **Maximum sharpen change** global limiter. No sequential GPU passes or repeated DLSS reconstruction.

**Existing settings migrate automatically:** When upgrading from the working v0.1, the previous `Strength` and `Bigger` values are used to populate either Small or Big. Both new radii default to zero. The other original settings, including jagged edge protection, edge bias, maximum change, diagnostic grid and eye separation, are preserved.

**Thin-line protection** is an additional, independently adjustable 0–1 slider, default **0 (off)** to preserve the original single-radius sharpening appearance on upgrade. The original **Sharpen jagged edges less** setting stays unchanged: its FXAA-derived guard detects jagged steps, not every straight one-pixel wire. Thin-line protection uses a lightweight isolated-feature detector and attenuates all active sharpening bands around small lines. This should reduce halos around wire fences, foliage and similar geometry. Setting this control to zero restores the original guard-only behavior.

### GPU diagnostic timing

Open **Diagnostics → Measure GPU sharpening time** to opt in. **GPU timing always starts disabled on every launch, even if older versions stored an enabled option in the INI.** The timing toggle is now session-only and never saved. The layer uses D3D12 timestamp queries to time the GPU copy-and-sharpen commands. It samples one out of every **32 submitted projection images** and reports an exponentially averaged GPU duration in **milliseconds**.

The layer creates timestamp heaps and readback buffers lazily only after the option is enabled. Query commands, fence-result mapping, and timestamp readback are **never performed while it is disabled**. During normal operation there are no GPU waits or synchronized CPU readbacks. One existing fence-completion check for swapchain-image reuse remains regardless of timing.

This measures **GPU time for the sharpening pass**, not total game frame time. In a double-wide mono projection this is approximately the extra GPU time per image/frame; in two separate stereo eye images the display is the **average per projection image**, not the sum of both eyes. Timing-query and sample reporting overhead are very small but not mathematically zero when enabled.

### Upgrade from the working v0.1 / v0.2

Quit STALKER 2, UEVR, and other OpenXR apps. Back up your previously working ZIP and `GlamaryeUEVR.ini`. Replace `plugins/GlamaryeSharpenUEVR.dll`, `scripts/glamayre_sharpen.lua`, and `layer/GlamaryeOpenXRLayer.dll` with the v0.3 versions.

If the existing `glamayre_openxr.json` manifest path and folder remain unchanged, the registered OpenXR implicit layer should continue working without rerunning the installer. If installed to a **different** folder, run `install-layer.ps1` from the new folder after removing the old registration.

Reopen Joey in OpenXR/DX12. Start with Small=0, Big=your previous strength, Extra Big=0, Ultra Big=0, Thin-line protection=0; enable one wider radius at a time to evaluate performance and haloing. Larger radius means more widely spaced samples, **not** that thin lines are automatically ignored.

### Automated checks

Windows CI tests the original shader compiler, D3D12 WARP rendering across SDR/sRGB/typeless formats, stereo separation and red diagnostic grid, simulated OpenXR hook lifecycle and real Khronos negotiation, plus actual GPU pixel comparisons with all four radii, FXAA jagged edge protection and isolated thin-line protection. The OpenXR integration test also toggles GPU timing on/off and confirms a completed asynchronous GPU timestamp sample. Six additional v0.3 tests verify clean defaults, legacy Bigger On/Off INI migration, four-band settings, Lua UI events, and disabled GPU timing despite a stale saved ON value. **Real PSVR2 frametimes still require a headset test.**

---

## Install

1. Close STALKER 2 and UEVR.
2. Extract the package into the game's UEVR persistent folder, normally `%APPDATA%\UnrealVRMod\Stalker2-Win64-Shipping\`, preserving the `plugins\`, `scripts\`, and `layer\` directories, plus `install-layer.ps1` and `uninstall-layer.ps1` at the root.
3. Open PowerShell and run **from this extracted folder**:
   `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-layer.ps1`
   It registers the manifest under **HKCU** for the current Windows user, matching the official Khronos loader's non-elevated user-hive support. Administrative access is not required. Avoid running STALKER 2 elevated; the Khronos loader can omit HKCU layers for high-integrity processes.
4. Keep any existing **Cheeky** OpenXR API layer installed. Both layers have distinct names and are intended to coexist; this implementation does not change Cheeky registry values or binaries.
5. Run Joey UEVR in **OpenXR + DX12** mode. Open LuaLoader -> **Glamarye Sharpen**. Enable the effect. Start with Small 0, Big 0.4, Extra Big 0, Ultra Big 0, Thin-line protection 0, Jagged Edges Less ON, Max Change 0.10.
6. Check the panel: **Khronos OpenXR API layer: ACTIVE**. `Processed scene images` should increase while the game is rendering. Enable **Diagnostics -> TEST ONLY red grid** temporarily: the red grid should appear in both headset eyes if the pass reaches real XR projection image(s). Turn it off after testing.
7. To disable the per-user implicit registration: close the game, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\uninstall-layer.ps1`, and restart your OpenXR applications. This removes **only** the Glamarye registry value.

Do not copy the API-layer DLL into the game executable folder or replace `openxr_loader.dll`. The DLL stays beside its JSON manifest in the extracted `layer\` folder.

## Rollback

If you see new image artifacts, broken controls, or unexpected frametime, exit the game and replace the **two DLLs and Lua script** with your previously working version. Your original Joey UEVR backend and Cheeky installation never need to be replaced. If you extracted to a different path and re-registered the manifest, first run the matching `uninstall-layer.ps1`, then restore/re-register the previous path. Use the saved `GlamaryeUEVR.ini` to restore prior slider values.

The v0.3 release is *CI-verified* but has not yet been verified by a live STALKER 2 + Joey + PSVR2 headset session; only the v0.1 API-layer design has direct user confirmation.

## Verify

If controls work but **API layer not loaded** appears, confirm the layer is registered and you restarted the game. `Processed scene images: 0` means the effect isn't processing scene pixels. Under **Frame path diagnostics**, check acquired, released, EndFrame, projections and processed image counters. These values help separate loader discovery from scene classification from GPU failure.

## Build/tests and limitations

- Uses the public UEVR plugin C API for Lua controls plus official Khronos `XrApiLayerCreateInfo` negotiation for OpenXR interception.
- The layer targets DX12 OpenXR projections (BGRA/RGBA SDR + RGBA16F); skips incompatible graphics APIs, depth, UI, unsupported textures and insufficient GPU synchronization.
- Keeps GPU commands on the application's original graphics queue with fences per swapchain image. No GPU readback or GPU fence waiting per normal frame, but it may wait on swapchain teardown.
- Entire pipeline is **sharpening-only**. It retains the Glamarye four-diagonal detail extraction, original Bigger radius, edge detector and max-change limiter; unrelated ReShade modules are not included.
- It is not an OpenVR compositor plugin, so **OpenVR mode is unsupported**. OpenXR DirectX 11, Vulkan and D3D11-only games are also unsupported by this D3D12 shader bridge.
- Windows CI compiles both production DLLs, runs the HLSL compiler and WARP GPU tests, checks the registry JSON manifest, and invokes the production API-layer negotiation + projection dispatch + WARP red-grid readback with a fake downstream OpenXR runtime. **Actual Joey/PSVR2 headset compatibility still needs one in-game test.**

Sources: [Cheeky OpenXR API layer](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/tree/main/openxr_layer), [Khronos OpenXR SDK](https://github.com/KhronosGroup/OpenXR-SDK), [Glamayre Fast Effects](https://github.com/rj200/Glamarye_Fast_Effects_for_ReShade). The original shader attribution/MIT license is in `LICENSE-GLAMARYE.txt`.
