# DuoView Mono — v02: unequal UE view rectangles + compositor shader

**Source-validation status:** PASS (pinned Joey UEVR; Stage 1 + Stage 2 strict-anchor
patch; C++ policy and 50%/30% geometry/projection tests).

**Standalone Windows status:** PASS (MSVC compiles and runs DuoView geometry
tests, Windows SDK FXC compiles `DuoViewComposite.hlsl` for DX12 compute).

**Full UEVR Windows backend:** NOT BUILT — source checkout requires the
restricted `joeyhodge/UESDK` submodule. A compilable shader is not a working
headset renderer. Composition is NOT YET called from UEVR.

**Headset and performance:** NOT VALIDATED. No FPS or image-quality improvement
has yet been demonstrated.

## Pinned sources

- Joey backend: `joeyhodge/UEVR`, commit
  `db6729dd9f5745705b1cdec2ec6f51bdc9570983`
- Joey frontend: `joeyhodge/uevr-frontend`, commit
  `60be4b0f9a646109fd9fdf448bacd41477234091`
- UESDK gitlink: `2ad9fefa67eb69634b9a1252f4b99876f5333671`
- Intended runtime: STALKER 2, DX12, PSVR2, SteamVR OpenXR.

## What's implemented

- Retains historical rendering IDs, original Mono ID 5 and all other original
  fallback modes; diagnostic DuoView ID 6.
- Keeps Joey's retirement-safe mode transition for new mode 6.
- In mode 6, Unreal is requested to create two native scene views.
- Both UE views are passed the same centered Mono camera pose, no IPD offset.
- Actual UE **viewport rectangles** are unequal, packed into the original
  double-wide allocation:
  - Foveal: default 50% of output each axis, baseline-equivalent sampling.
  - Peripheral: default 20% of output each axis, full-FOV projection.
  - 3000² example: 1500×1500 + 600×600 = 2.61M render-view pixels.
  - 30% geometry path: 900×900 + 600×600 = 1.17M pixels.
- Computes gaze-centered off-axis projection crop in clip space, independent of
  reversed-Z depth convention; default currently center fixed.
- Includes portable math to produce 30% and 50% gaze positions and UV
  feathering, with tests for both.
- Includes a DX12 compute shader composing high-resolution ROI into the low-res
  full-FOV frame, with per-viewport texture-coordinate clamping.
- Existing Mono OpenXR submission and auxiliary modes retain their source
  behavior. **The compositor shader is built but NOT integrated with them.**

## What remains before a useful headset build

1. Gain legitimate access to Joey's exact pinned UESDK gitlink commit.
2. Compile Joey's full backend with both source patches; fix any SDK/API drifts.
3. Dispatch the DX12 composite shader with a valid per-frame descriptor set,
   resource transitions, correctly separated source/output resources and
   GPU fence retirement, *before* existing Mono eye copies.
4. Verify that UE shading/G-buffer/Lumen actually processes the smaller view
   rectangles (rather than full-size intermediate render passes).
5. Hook PSVR2 gaze, map the **combined calibrated** direction into the shared
   Mono optic frame, use one per-render-frame sample for both projections and
   both rectangles, handle 50ms gaze staleness without resetting history.
6. Stable temporal states: TAA/TSR, Lumen, exposure, object motion vectors,
   depth and source-view selection. Profile equivalent frames on headset.

The uncomposited DuoView mode is explicitly named "Atlas Diagnostic -
Uncomposited" in-game: rendering into a packed atlas is *not* the final
headset image. Keep using original Mono until actual compositing is connected.

## Current CI workflows

`.github/workflows/duoview-stage2.yml`:

- `source-validation`: checks pinned repo out **without** private UESDK,
  applies patches with verified anchors, runs portable C++ tests.
- `shader-and-tools`: compiles both standalone C++ diagnostics and
  `DuoViewComposite.hlsl` with MSVC/Windows SDK, uploads an Actions artifact.
  This artifact is **not the UEVR injector**.
- `build-stage1`: complete UEVR/aux DLLs/frontend packaging, intentionally
  gated with `DUOVIEW_FULL_BUILD=1` until exact UESDK access works.

To authorize the full build, use GitHub account access approved by Epic/Joey
for `joeyhodge/UESDK` and set a repository Actions secret called
`UEVR_SOURCE_TOKEN` to an appropriately scoped read-only PAT. Only after
verifying the authenticated account can read the exact pinned source, set the
repository Actions variable `DUOVIEW_FULL_BUILD` to `1`, and start the
workflow. Never commit credentials into this public branch.

We evaluated publicly available `Aeyth8/UESDK` (last updated in 2024);
the main renderer source from Joey's September 2026 commit references at least
10 missing SDK headers. Treat it as unsuitable for direct substitution.
