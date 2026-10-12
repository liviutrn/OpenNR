# DuoView Mono — UEVR experimental implementation (v05)

This experimental branch adds a **second same-camera Unreal rendering view**,
a high-density cropped fovea plus lower-density full-FOV periphery, and
independently validated color-compositing code for monoscopic OpenXR output.

**Current status: SDK-independent C++/DX12 WARP tests PASS. Full Joey UEVR
backend NOT compiled, and the real UEVR DX12 compositor dispatch is NOT YET
integrated. Do NOT install this artifact in STALKER 2 as a working DuoView
injector. No verified gameplay FPS or PPD improvement is claimed.**

## Code

| Stage | Component | Result |
|---|---|---|
| 1 | `apply_stage1.py` | Method 6 and guarded Mono transitions, pinned-source patch tests PASS |
| 2 | `apply_stage2.py`, `DuoViewGeometry.hpp` | Two Unreal view rectangles + off-axis crop, source tests PASS |
| 3 | `DuoViewComposite.hlsl` | Compute compositor, shader compile + DX12 WARP dispatch PASS |
| 4 | `DuoViewGaze.hpp` | Optical gaze coordinates + 50ms stale-frame cache, unit tests PASS |
| 5 | `DuoViewFrame.hpp` | Pose/view-generation + GPU-fence validity coordinator, unit tests PASS |
| 6 | `DuoViewWarpTest.cpp` | True GPU composite/readback, red fovea/blue periphery/seam PASS |
| 7 | `DuoViewCompositeRaster.hlsl` | BGRA8 RTV full-screen raster alternative, GPU readback PASS |
| 8 | `DuoViewConfig.hpp` | Per-frame immutable settings/gaze snapshot, unit tests PASS |
| 9 | `DuoViewMonoCopyD3D12.hpp` | Single BGRA8 composite -> double-wide BGRA8 eye copies, GPU pixels PASS |

## Stage 9 WARP evidence

Windows runner compiled with Visual Studio 2022 and the Windows SDK. The
shader and GPU command list executed on DirectX 12 WARP, not a fake CPU
simulation:

- Compute center RGB **255,0,0**, periphery **0,0,255**, feather **43,0,212**.
- BGRA8 render-target raster path outputs exactly the same sample colors.
- Full stereo copy duplicates **1,024 source pixels**, all four color
  channels, to two adjacent OpenXR-surrogate eye regions; **0 mismatches**.
- Cross-frame, missing-view, stale-pose, GPU fence and inconsistent settings
  checks pass independently.

Successful test workflow:
https://github.com/liviutrn/OpenNR/actions/runs/38307862007

## Crop budgets (scene-view pixels only, not proven GPU timings)

At baseline 3000x3000 Mono, periphery 20% width/height and foveal density 1:

- **50% crop:** 1500x1500 fovea + 600x600 periphery = 2.61M view pixels,
  71.0% fewer than baseline.
- **30% crop:** 900x900 fovea + 600x600 periphery = 1.17M view pixels,
  87.0% fewer than baseline.

The original renderer can still incur full-screen UE passes, shadows, Lumen,
frame scheduling, and extra second-view CPU costs. These are **not FPS gains**.

## Still outstanding

1. Access the exact UESDK gitlink required by Joey's pinned backend commit
   `db6729dd9f5745705b1cdec2ec6f51bdc9570983`. Current connected
   GitHub account receives 404 for `joeyhodge/UESDK`.
2. Compile full UEVR with the source patches and resolve any interface/ABI
   problems. The disabled full backend CI only builds the current
   **uncomposited atlas diagnostic**, not a game-ready DuoView.
3. Wire frame snapshot, actual completion of both UE rendering views,
   DX12 raster compositor/RTV and single-width-to-double-wide OpenXR
   copy inside `D3D12Component.cpp`. Respect GPU states and fences.
4. Integrate tested PSVR2 Toolkit CAPI gaze reader with correct coordinate
   mapping to Joey's Mono optic basis and zero smoothing/deadzone.
5. Add in-game foveal/peripheral density and crop controls; preserve the
   original Mono mode and all other legacy rendering methods.
6. Test on STALKER 2 DX12 with PSVR2: view alignment, TAA/TSR/Lumen,
   seam quality, gaze movement, frame-pacing, actual GPU costs.

Read **UEVR_INTEGRATION.md** for exact UEVR renderer and OpenXR insertion
points, resource states, contract checks and transition requirements.

## Build/test instructions

Full available test workflow:
`.github/workflows/duoview-stage5.yml` (source + Windows DX12 WARP).

The SDK-dependent full backend is gated by
`DUOVIEW_FULL_BUILD=1` and requires a read-only, **authorized** credential
stored as the GitHub Actions secret `UEVR_SOURCE_TOKEN`. Never place tokens
in the repository or in this conversation.

This development workspace lives in a separate OpenNR branch only because
Joey's UEVR repository is read-only for the connected GitHub account. The
OpenNR main branch and the user's existing working UEVR installation have
not been modified.
