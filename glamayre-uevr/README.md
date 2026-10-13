# Glamarye Intelligent Sharpen for UEVR — experimental v0.1

Standalone native DX12 sharpening plugin for UEVR 2.39+, inspired by Cheeky Foveated DLSS's public UEVR adapter. Adapts only the MIT-licensed Glamarye Intelligent Sharpen calculation and FXAA edge-detection mask (no FXAA smoothing pass, AO, GI or DOF). No ReShade, motion vectors, eye tracking, OpenXR API layer, or UEVR backend modifications are required.

Status: experimental. Must validate headset behavior in Joey UEVR STALKER 2. Windows Actions compile success proves binary validity, not runtime operation or visual quality.

## Installation

1. Close STALKER 2 and UEVR.
2. Extract the artifact to the game's UEVR persistent profile directory:
   %APPDATA%\UnrealVRMod\<Stalker2-game-exe-name>\
   The archive must produce plugins\GlamaryeSharpenUEVR.dll and scripts\glamayre_sharpen.lua.
3. Inject the existing Joey UEVR build with OpenXR and DX12 as usual.
4. Open UEVR -> LuaLoader -> Glamarye Sharpen. Enable Intelligent Sharpen.
5. Set the game's built-in sharpen to 0 for comparisons. Start with strength 0.4, Bigger on, Edge protection on, max change 0.10.
6. To remove, close the game and remove only the two Glamarye files. No Joey, Cheeky or other plugins are modified.

If the UI says "Waiting for GlamaryeSharpenUEVR.dll", inspect UEVR.log and the DLL's plugin location.

## Runtime and safety details

- Uses the public UEVR DX12 post-render callback, where source is documented as in D3D12_RESOURCE_STATE_RENDER_TARGET.
- Copies full source into one default GPU texture per size/format, then draws a fullscreen triangle into the current headset render target.
- One post-process draw per array slice, if image represented as a texture array.
- UEVR's RTV handle is used when available for non-array targets, ensuring rotating swapchain buffers aren't mistaken for one another. Array RTVs are immutable per target.
- Doesn't modify game's DLSS or Joey's mono/stereo renderer.
- Supports common 8-bit SDR, 10-bit, and 16-bit floating formats. Doesn't process multisampled targets or >2 image arrays. Unsupported formats bypassed.
- Side-by-side eye layout checkbox clamps samples within each eye. Leave off for mono or separate eye textures.
- Shader colorspace follows DX12 view format; HDR float images use a 16.0 max-color limit. No full Glamarye HDR transfer-function implementation.
- Settings saved to GlamaryeUEVR.ini in UEVR profile.

## Known limitations

- Final headset verification required for Joey's fork. Public API availability does not prove callback execution in every mono mode.
- Plugin doesn't detect or force VR texture layout or order between post-processing plugins.
- Initial activation may cause one-time shader and PSO compilation hitch; no recurring GPU readbacks or CPU waits.
- Sharpening cannot remove shimmer already introduced by DLSS.
- DX12 only; assumptions follow UEVR 2.39 documented resource state.
- If GPU error appears, disable plugin and inspect UEVR.log.

## Credits

Glamarye Fast Effects: Robert Jessop, MIT, see LICENSE-GLAMARYE.txt. UEVR 2.39 API.h: praydog, MIT. Cheeky Foveated DLSS was consulted for architecture, not redistributed.
