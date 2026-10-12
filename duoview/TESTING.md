# DuoView Mono experimental injector — STALKER 2 / PSVR2

This build uses publicly accessible UEVR and UESDK sources with Joey Hodge's calibrated Mono policy ported into the backend. It adds a separate DuoView Mono mode. Compilation and WARP GPU tests do not establish game compatibility or a performance gain.

## Start

1. Extract the complete injector artifact into a separate folder. Keep the original working Joey injector available.
2. Start SteamVR and PSVR2 Toolkit, start STALKER 2, and inject with OpenXR.
3. Select **Mono (Experimental)** first. Confirm the ordinary Mono image, head rotation and head translation. Mono is DX12/OpenXR in this experimental public backend.
4. Leave Extreme Compatibility, SceneView compatibility, split-screen, 2D Screen and Stereo Emulation off. Native Fix and Ghost Fix are bypassed by Mono without changing their saved values.
5. Select **DuoView Mono (Experimental)**. Open **VR → Unreal → DuoView Mono**.
6. First disable **PSVR2 Toolkit gaze**, enable **Debug border**, and use crop width/height 0.50, peripheral scale 0.20, density 1.00. Confirm a sharp center over a continuous low-resolution full-FOV picture.
7. Turn on gaze. Move your eyes, then your head, then translate your head. Both UE views should use the same pose; the crop should move without a smoothing/deadzone setting.
8. Try width/height 0.30 and source view 1. After validating density 1, density 3 with a 30% crop renders the fovea at 2700×2700 for a 3000×3000 output; it uses 7.65 million view pixels including the 600×600 periphery. This increases render sampling; the final output and headset still limit visible detail. Source-view swapping may change lighting quality; it is not a guaranteed Lumen fix.

## What to record

Compare the same save, camera, scene, game settings and final output resolution:

| Mode | Suggested settings |
|---|---|
| Original Mono | 3000×3000 final Mono output |
| DuoView 50% | width/height .50, density 1, periphery .20 |
| DuoView 30% | width/height .30, density 1, periphery .20 |

Record GPU/CPU frametime, final output resolution, logged fovea/periphery sizes, gaze status, lighting/exposure seams, flicker, ghosting and 6DoF behavior. The menu's view-pixel budget is a calculation, not measured GPU savings. A GPU capture is required to verify that material and screen-space passes actually use smaller rectangles.

If the headset remains blank, the backend may be rejecting an incomplete frame or unsupported resource layout. Return to Original Mono and preserve `UEVR.log`, the build's `BUILD_SOURCE.txt`, and a screenshot of the settings. Do not interpret a rejected frame as a validated foveated render.

Toolkit is loaded through its existing CAPI DLL and published path; this package does not replace the driver. Missing or invalid gaze uses fixed center. Reads are nonblocking with up to 50 ms validity caching; there is no spatial smoothing or deadzone.

## Limits

This public-backend port is not a byte-for-byte Joey release. Joey's newer private-SDK game-specific hooks and DIBR modes are excluded; serialized IDs 3/4 remain reserved. Original Mono ID 5 and DuoView ID 6 remain separate. Unreal temporal history, Lumen/exposure consistency, actual pixel savings, and RTX 5070 compositor timing must be tested in game.
