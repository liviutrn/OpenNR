# DuoView Mono — Joey backend recovery experiment

This package keeps Joey's **official Mono injector/backend binaries unchanged** and adds a separately compiled plugin. It replaces the failed old-public-backend experiment. It is an experimental recovery build, **not yet validated in STALKER 2 or PSVR2**.

## Install and test

1. Extract the complete package to a separate folder. Close STALKER 2.
2. Run `powershell -ExecutionPolicy Bypass -File .\Install-DuoView.ps1 -Mode 0` from that extracted folder, or copy `Plugin/DuoViewJoey.dll` to `%APPDATA%/UnrealVRMod/Stalker2-Win64-Shipping/plugins/` and `Plugin/DuoViewJoey.ini` to its parent folder.
3. Disable Cheeky's and ReShade's **OpenXR API layers** for this isolated test. The installer moves Cheeky's profile plugins to a timestamped backup outside the plugins directory. It does not edit system layer registration.
4. Start the game and inject using `JoeyOriginal/UEVRInjector.exe`. Select ordinary **Mono** for mode 0. This tests the unchanged official Joey package plus diagnostic logging.
5. If stable, close the game, run the installer with `-Mode 1`, and select **Native Stereo**. Keep Native Fix, Extreme Compatibility, SceneView Compatibility, 2D Screen and Stereo Emulation **off**, and Frame Delay Compensation at **0**. This stage renders two full views with one camera pose and a common Mono projection.
6. After that succeeds, test `-Mode 2` (fixed foveal crop) and then `-Mode 3` (PSVR2 gaze). These are separate startup stages, not extra per-frame passes. Keep the game on Native Stereo while testing these stages. Restart the game after changing configuration or rendering mode.
7. Send `UEVR.log` from the game's `%APPDATA%/UnrealVRMod/Stalker2-Win64-Shipping/` folder after a failed or successful test. Logs include `[DuoViewJoey]` rejection reasons and backend SHA256. The Unreal game log alone does not identify the failed injection stage.

Remove `plugins/DuoViewJoey.dll` to return to Joey's original behavior. Existing Mono remains available with the plugin in mode 0. Restore any moved Cheeky files from `DuoViewBackup-*` when finished testing.

## Controls

`DuoViewJoey.ini` is read once at plugin startup. `CropWidth` and `CropHeight` are fractions of the full Mono image; 0.50 means half the width and half the height. `PeripheralScale` scales both peripheral dimensions. `FovealDensity` controls pixels per full-frustum unit inside the fovea. Settings that exceed the existing double-wide allocation are rejected. `DebugBorder=1` outlines the fovea. PSVR2 tracking uses the preserved native Toolkit bridge, a 50 ms missed-sample cache and no spatial smoothing/deadzone.

## Implementation and validation boundary

The plugin intercepts the exact released Joey rectangle/projection callbacks, uses Native Stereo's two real UE views with a shared centered pose, and reuses the existing DuoView DX12 compositor. `VR_FrameDelayCompensation` must remain 0. Frame packets are associated with the actual discovered UE family FrameNumber, checked again at the render-thread family callback, and matched to the OpenXR consumer frame before composition. Queue resources/descriptors are fence-retired. OpenXR projection submissions use Joey's common optical geometry and integer per-eye subimage crops, including optical rotations. Incomplete or projection-mismatched scene layers are withheld rather than displaying an old atlas.

The supported backend is the unmodified `DIBRMONOUEVR.zip` asset from Joey release `101226HELLRAISERp1`. Backend SHA256: `19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966`. Other backends stay in diagnostics mode. The package does **not** assume this is the exact user's previously installed Joey version. Runtime changes currently support STALKER 2 DX12/OpenXR with a BGRA8 double-wide scene target; other formats are rejected. A rejected active renderer frame can leave the scene blank while the original UI still submits.

Windows compilation, binary contract checks, portable policy tests and production WARP compositor readback cannot establish game compatibility, the correctness of the complete frame handoff, gaze behavior, temporal/Lumen histories, or GPU savings. Those require the staged game test. No measured FPS gain is claimed.

GPL-3.0 applies to the UEVR-derived implementation; see `UEVR-LICENSE.txt`. Public plugin API headers are separately MIT licensed. The original official Joey binaries remain byte-for-byte identical and retain their original licensing.
