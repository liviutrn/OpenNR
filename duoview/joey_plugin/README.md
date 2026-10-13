# DuoView Mono — Joey-preserving plugin with UEVR in-game control panel

This branch is an **engineering integration candidate**, not a headset-validated product. The original Joey Mono binaries from `101226HELLRAISERp1` are reproduced and verified byte-for-byte. DuoView is provided only by an optional profile plugin.

## In-game UI

The installer copies `DuoViewJoey.dll` to `<UEVR game profile>/plugins/` and `DuoViewJoeyUI.lua` to `<UEVR game profile>/scripts/`. Open Joey's usual in-game UEVR interface, then its **Scripts** section. Expand **DuoView Mono - Joey original backend**.

The panel shows the applied mode, whether native hooks installed, a refusal/activation reason, engine-tick callbacks, XR LocateViews calls, completed UE family pair candidates, rendering callbacks, consumer matches, queued GPU composites, XR frame submits, modified projection layers and XR acceptance/error counts. **A loaded DLL is not proof that two views rendered.** Counters are independent signals.

Mode (0 original Joey, 1 shared-pose reference, 2 fixed fovea, 3 PSVR2 eye-tracked fovea), crop sizes, peripheral scale, foveal density, feather and border are configurable in this UI. **Save and restart the game to apply changes** in this cautious integration revision; there is no unsafe mid-frame hook installation or split-view parameter change. The UI reads native status only while expanded and requests an update on demand. The plugin does not periodically write status files during normal gameplay.

## Validation boundary

Automated Windows CI checks the official Joey ZIP/backend SHA256 and exact ABI signatures, compiles the unchanged-backend plugin, executes seven C++/WARP tests, validates native DLL exports, parses the Lua UI, and installs the ZIP into a disposable UEVR profile. These tests **do not** verify that STALKER 2 honors the cropped view rectangles in heavy UE5 passes, that DX12 work arrives on the expected graphics queue, or that PSVR2 image content, gaze alignment, frame timing and throughput are correct.

No further end-user tests are necessary merely to investigate "nothing happens": the new panel must show the exact stage of activation first. When runtime integration is sufficiently reviewed, one purposeful game/headset validation should compare current Joey Mono against DuoView mode 2, then optionally mode 3; do not cycle through many diagnostic builds.

## Install, preserve and restore

1. Close STALKER 2, extract the complete ZIP to a separate folder.
2. From PowerShell in that folder, run `powershell -ExecutionPolicy Bypass -File .\Install-DuoView.ps1 -Mode 2`. The installer does not alter other profile plugins; it backs up only older DuoView files.
3. Launch STALKER 2 and inject using `JoeyOriginal/UEVRInjector.exe`. In UEVR use **OpenXR and Native Stereo (ID 0)**, not Mono; leave Native Fix, Extreme Compatibility, SceneView Compatibility, 2D Screen, Stereo Emulation off and Frame Delay Compensation at 0. In active DuoView modes, temporarily disable conflicting Cheeky/ReShade modules/layers yourself; the installer does not remove them.
4. Open the in-game UEVR Scripts panel to inspect actual activation status; save adjusted settings there and restart to apply.
5. Delete `plugins/DuoViewJoey.dll` and `scripts/DuoViewJoeyUI.lua` to restore the unchanged Joey backend. Original Joey Mono mode ID 5 remains available without the plugin.

**Do not interpret successful compilation or "Hooks=active" alone as proof of foveated rendering.** The distinct pairing, composition and OpenXR counters must advance. The v11 source preserves the old v08 exact-binary adapter until actual in-game rendering is established.
