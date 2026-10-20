# v186.1 — Integrated Glamarye Fovea Sharpen (default 1.0)

This release is an **experimental enhancement of the stable DuoView Build 182**, adding **Glamarye Intelligent Sharpen** directly to the existing DuoView D3D12 compositor. The preserved v182 release and source baseline remain unchanged.

## What's new

- **Fovea-only sharpening:** Glamarye runs on the high-detail, gaze-tracked foveal image. The lower-resolution periphery is left unsharpened.
- **Integrated in the existing composition pass:** no separate OpenXR sharpening layer, fullscreen sharpening pass, external texture-copy pass, or new per-frame command submission.
- **Bigger Sharpen:** original Glamarye 1.4-pixel diagonal sampling radius, with jagged-edge protection, maximum-change limiter **0.10**, and FXAA edge bias **0.02**.
- **Configurable strength:** DuoView's **Glamarye fovea strength** slider ranges from **0.0 to 2.0**. This release defaults to **1.0** on fresh profiles; **0.0 disables sharpening**. Existing saved profiles may retain their previously saved strength.
- **After game-side upscaling:** sampling offsets use the final monoscopic output pixel scale after DLSS. The blended Mono image is submitted to both OpenXR eyes.
- **Performance-focused:** sharpening the fovea avoids most of the full-frame work required by the original standalone OpenXR layer. The actual GPU cost depends on resolution and configuration; there is no claimed FPS uplift from sharpening.
- **Original DuoView pipeline retained:** Native Stereo Fix-backed two-view rendering, the eye-tracking/gaze stabilization fixes, and the v182 delivery/hold logic are unchanged.

## Compatibility and testing

- Tested by the project owner in **S.T.A.L.K.E.R. 2, DX12 / OpenXR with PSVR2**, after disabling **NVIDIA Smooth Motion**. Integrated sharpening was functional, and GPU overhead was reported as minimal.
- The project owner reported that the game's UI was functioning correctly in the working Build 186 session. This release changes the **fresh-install sharpening default only**; it does not incorporate any subsequent experimental v187 UI/output-path changes.
- Windows CI includes pinned Joey/UESDK backend/frontend builds, DXBC HLSL compilation, WARP GPU tests, and the original compatibility tests. CI cannot prove complete game/headset compatibility.

## Installation and notes

1. Download the ZIP attached to this release, extract into a **separate** installation directory, and follow its `READ_FIRST.txt` instructions.
2. Select **DuoView / ID 6** in UEVR.
3. Open **DuoView Mono — quality and diagnostics**. The **Glamarye fovea strength** slider is **1.0 by default on fresh profiles**; use **0.0** to disable the effect or adjust to taste.
4. **Disable/unregister the old external Glamarye OpenXR API layer** when using this integrated version; otherwise sharpening could be applied twice.
5. For the previously verified smooth configuration, leave **NVIDIA Smooth Motion disabled**. HAGS was not established as a root cause.

**This is DuoView Mono, not a true four-view stereo renderer.** It composites two Unreal views into one monoscopic output for both headset eyes.

## Attribution

The Glamarye sharpening algorithm originates from **Robert Jessop's Glamarye Fast Effects for ReShade (MIT)** and is adapted here for UEVR/D3D12:
- https://github.com/rj200/Glamarye_Fast_Effects_for_ReShade
- https://github.com/joeyhodge/UEVR
- https://github.com/praydog/UEVR

The pinned Build 182 source and separate baseline release remain available at `build-182` and `v182`.
