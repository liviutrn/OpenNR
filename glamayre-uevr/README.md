# Glamarye Sharpen for UEVR — OpenXR API Layer v0.1 (experimental)

This version has **two distinct DLLs**, based on the architecture of Cheeky's separate OpenXR layer and UEVR plugin:

- `layer/GlamaryeOpenXRLayer.dll` — genuine Khronos implicit OpenXR API layer, loaded through the application's OpenXR loader (including Joey's statically linked loader).
- `plugins/GlamaryeSharpenUEVR.dll` — a game-local UEVR C++ plugin implementing Glamarye Intelligent Sharpen in D3D12 and receiving the Lua controls from `scripts/glamayre_sharpen.lua`.

**Previous v0.1–v0.4 used a broken external `openxr_loader.dll` hook and did not sharpen the scene.** This version no longer hooks any loader exports. The API layer observes `xrCreateSession`, `xrCreateSwapchain`, `xrAcquireSwapchainImage`, `xrEndFrame`, `xrReleaseSwapchainImage`, and destruction through the supported Khronos chain. It identifies headset scene images from **projection layers**, not texture dimensions or UI. Once recognized, it records the existing Glamarye GPU shader into the projection image after UEVR's DX12 copy and before the real OpenXR release on the same queue. It does not change Joey or its DLSS code.

## Install

1. Close STALKER 2 and UEVR.
2. Extract the package into the game's UEVR persistent folder, normally `%APPDATA%\UnrealVRMod\Stalker2-Win64-Shipping\`, preserving the `plugins\`, `scripts\`, and `layer\` directories, plus `install-layer.ps1` and `uninstall-layer.ps1` at the root.
3. Open PowerShell and run **from this extracted folder**:
   `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-layer.ps1`
   It registers the manifest under **HKCU** for the current Windows user, matching the official Khronos loader's non-elevated user-hive support. Administrative access is not required. Avoid running STALKER 2 elevated; the Khronos loader can omit HKCU layers for high-integrity processes.
4. Keep any existing **Cheeky** OpenXR API layer installed. Both layers have distinct names and are intended to coexist; this implementation does not change Cheeky registry values or binaries.
5. Run Joey UEVR in **OpenXR + DX12** mode. Open LuaLoader -> **Glamarye Sharpen**. Enable the effect. Start with Strength 0.4, Bigger ON, Jagged Edges Less ON, Max Change 0.10.
6. Check the panel: **Khronos OpenXR API layer: ACTIVE**. `Processed scene images` should increase while the game is rendering. Enable **Diagnostics -> TEST ONLY red grid** temporarily: the red grid should appear in both headset eyes if the pass reaches real XR projection image(s). Turn it off after testing.
7. To disable the system-wide implicit registration: close the game, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\uninstall-layer.ps1`, and restart your OpenXR applications. This removes **only** the Glamarye registry value.

Do not copy the API-layer DLL into the game executable folder or replace `openxr_loader.dll`. The DLL stays beside its JSON manifest in the extracted `layer\` folder.

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
