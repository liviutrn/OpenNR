# OpenNR 2.20.1-v06-r2 — gaze crop geometry and sampling stability

[r1 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r1) · [r2 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r2) · [r3 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r3)

r2 fixes the disagreement between crop placement, reconstructed image coordinates, and retained NR history that was exposed by the initial gaze-history fix. It targets image shaking and trembling without requiring an added gaze deadzone or smoothing filter.

**Headset feedback:** the tester reported no image shaking or trembling and a substantial improvement, with possible slight residual flickering. This is the user-confirmed stability baseline for r3.

Revision: [fc649f6](https://github.com/liviutrn/OpenNR/commit/fc649f65666137047035c644fca010bfcaf05a6d).

## What was wrong

Original OpenNR regenerated/flickered while gaze moved, but did not exhibit the later trembling. Keeping temporal history through gaze movement removed much of that regeneration and exposed inconsistent image-coordinate placement.

The local SR and NR paths independently rounded input/render and output/display crop rectangles. With DLSS Performance at **0.5 × 0.5 input resolution**, an output crop origin could advance one display pixel while the input crop had not moved by an input pixel. Retained NR history then compensated movement that was absent from the reconstructed local SR image.

Reduced-model sampling could also change phase as a crop moved. The same stationary scene location could therefore receive a different sampled value in successive crops. Large deadzones hid these effects by reducing crop movement, but introduced visible lag.

CPU reproductions demonstrated both geometry mismatch and sampling-phase sensitivity. They do not prove that these were the only possible causes of every native DLSS artifact.

## Changes from r1

### Derive display placement from the actual input crop

Default-mode SR now uses one crop plan: its output rectangle is derived from the input pixels actually rendered.

At Performance's exact 2:1 output/input ratio, the color and guide alignment maps are identity. **This path adds no extra resampling pass.** Other ratios align color in the existing writeback shader and conditionally align depth/motion guides to the same display positions.

### Use the current and previous cropped camera geometry

Cropped SR camera transforms now describe the actual current and previous cropped frusta. Ordinary same-size gaze movement keeps history. Engine TAA jitter stays separate from camera geometry, and the existing native motion-vector flags and scale contracts remain.

Camera history advances only after successful stereo SR, so a failed or incomplete frame cannot become the next frame's reference.

### Correct legacy NR crop displacement

Legacy NR crop compensation removes an extra model-resolution factor. A given physical crop displacement must describe the same motion at 100%, 85%, and 70% NR resolution.

This host reprojection correction retains r1's native guide-unit conversion.

### Anchor reduced one-pass atlas sampling

For a configured moving crop on the strict one-pass atlas route, reduced-model sampling is anchored to a fixed full-image lattice.

Downsampling, depth/motion packing, history reprojection, and output resolve now share the same pitch and phase. Previous model dimensions, valid eye-local overlap, and the right eye's changing packed origin remain part of correspondence and rejection.

### Reproject the optional result stabilizer

When gaze cropping can move, the optional same-pixel result stabilizer uses motion reprojection instead of assuming the previous pixel describes the same scene point.

Zero stabilization still adds no continuous filter. The existing configurable ladder-transition bridge can still operate during crop/model handoffs.

## Systems preserved

- FPS controller decisions, pass counts, GPU budget, hold/cooldown/retry policy, and crop tiers remain unchanged.
- Neural fine tuning, sequential-pass tuning, shaping controls, and inner crop feather remain unchanged.
- Ordinary same-size gaze movement does not request native DLSS resource recreation or a global history reset.
- Real tracking loss, scene cuts, frame gaps, and incompatible resource contracts still invalidate temporal state.
- Crop-transition mask bounds and resource-envelope rules are retained.
- Faster-mode placement and full-eye/flat nominal model resizing retain their existing paths.
- Pre-SR was left outside this revision's scope.

No new deadzone, pixel quantization, or gaze smoothing is used to conceal the coordinate problem.

## Quality and regression evidence

The [independent r2 review](https://github.com/liviutrn/OpenNR/blob/6439e8287d8427ff64cecafc473b8476205b95e6/experiments/gaze-stability-2026-10-04/verification-r2/verification-r2.md) recorded source replay, controller/gaze/history tests, CPU image and camera oracles, six buffer-layout checks, six shader compilations, full Windows compilation, and a shipped-package audit. That review predates the positive headset feedback above.

| Check | Result |
|---|---|
| Old Performance crop geometry | 4,566 coordinate mismatches reproduced |
| 210 overlapping moving-crop image cases | Maximum interior difference below 7.08e-7 on a 0–1 signal |
| 2,000 cropped-camera reprojection cases | Maximum NDC error below 1.29e-7 |
| 3,240 stereo atlas correspondence cases | 1,620 invalid-history cases rejected; valid correspondence error below 1.14e-13 pixels |
| Package comparison against r1 | No removals; one added guide-alignment shader; DLL and three existing shaders changed |

These are CPU/source/package checks, not native-network image measurements. The image oracle excludes a four-pixel edge strip and does not establish identical edge detail or seamless crop boundaries.

## Performance and remaining limitations

At exact DLSS Performance 2:1, the alignment correction adds no resampling pass. Other SR ratios may use conditional guide alignment and need their own visual and timing checks. FPS policy is unchanged; these facts do not establish a measured zero-cost or universally regression-free runtime.

The tester's positive result supports shaking/trembling improvement in the tested configuration. Possible slight flickering remains an observation, not a confirmed resolved issue. Other headsets, SR ratios, tracking discontinuities, and all tuning combinations still need runtime acceptance.

r3 builds on this geometry/history baseline and addresses the **outside crop's brightness/color seam**, not remaining temporal flicker.

---

## Project lineage

OpenNR inherits [Open Shaders](https://github.com/alandtse/open-shaders) and [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders) ([Nexus](https://www.nexusmods.com/skyrimspecialedition/mods/86492)). These are custom fork revisions.

## Earlier project documentation

The following v01 and base-project notes are preserved historical documentation. Their acceptance statements apply to those versions.

# OpenNR 2.20.1-v01 — Sequential Gaze + Stereo Atlas Experimental Build

This branch is a substantially modified experimental build of **OpenNR 2.20.1**, based on the upstream OpenNR project by **olekspa**. The upstream project and attribution remain intact; the changes below describe the custom `liviutrn/OpenNR` v01 line.

## What v01 changes

The main v01 work is focused on **DLSS5 / Feature18 in VR**, especially eye-tracked foveated rendering, sequential neural rendering, and reducing Feature18's fixed invocation cost.

v01 adds or changes:

- **2× sequential Feature18 with fixed, adaptive, and eye-tracked crops** instead of restricting sequential NR to Full Eye.
- **Relative Pass-2 coverage** at 100/90/80/70/60/50% of the current live Pass-1 crop.
- A **compact reduced Pass-2 resource**, so smaller P2 regions reduce pixel-dependent work rather than evaluating a full-size texture and masking it afterward.
- **Independent Pass-2 Feature18 tuning** for intensity, local tone, local structure, skin structure, style, AutoMask, and UI correction.
- **Independent P2 edge compositing** with Hard Copy, Feather, Dither, Rectangle/Oval masks, falloff, feather width, and dither strength.
- **Continuous gaze stabilization** replacing the old large hard crop-origin dead zone while retaining the working v00 crop-motion history compensation.
- **Eye tracking + adaptive crop coexistence**: gaze owns center/origin; adaptive control may scale crop size around the live gaze point.
- An optional **stereo-atlas mode** that packs `LEFT | replicated-edge guard | RIGHT` and can evaluate Feature18 once per stereo pair per pass.
- A **configurable atlas guard**, default 50 px, with matching color/depth/motion-vector atlas packing.
- **Dedicated atlas Feature18 history slots**, isolated from normal left/right histories.
- **Atlas/native-stereo temporal handoff safety** so toggling/fallback cannot revive stale history.
- **GPU-safe atlas failure handling**, waiting for D3D12/interop idle before retiring a potentially in-flight native Feature18 handle.
- Normal independent-eye stereo retained as the **A/B and fail-safe fallback path**.
- A reproducible GitHub Actions transformation/build/package pipeline for this experimental line.

### Important current limitations

v01 compiles and packages successfully, but some settings plumbing is intentionally ahead of renderer execution:

- independent **Pass-2 model resolution** is not yet fully implemented;
- the broader **adaptive FPS/frametime controller** still needs further work, including explicit budgeting of estimated P2 cost;
- before/after-NR **sharpening** fields exist but are not yet a finished robust implementation;
- stereo-atlas still requires real in-headset performance and image-quality validation.

## v01 technical documentation

For the complete architecture, implementation order, history rules, active transformation scripts, known limitations, build environment, artifact identity, and v02 continuation instructions, see:

**[OpenNR 2.20.1-v01 Technical README](docs/versions/2.20.1-v01/README.md)**

The original pre-implementation v01 design contract is preserved separately at:

[docs/2.20.1-v01-IMPLEMENTATION.md](docs/2.20.1-v01-IMPLEMENTATION.md)

## Validated v01 build

Known-good v01 code baseline:

`9b5e9ccffa931e3394044091be1a5c82e2486669`

Successful GitHub Actions build:

https://github.com/liviutrn/OpenNR/actions/runs/36716356725

Artifact:

`OpenNR-2.20.1-v01-carrier-excluded`

Artifact SHA-256:

`2cf53b1f7d60b54ec69d8cab03ff22cb7a47a23265bc3924c8572bbfa11ffb27`

The public artifact intentionally excludes `nvngx_dlssnr.dll`; use a validated licensed carrier from an existing legitimate OpenNR installation.

---

# Base OpenNR 2.20.1 project

OpenNR is a VR neural-rendering development project combining the native Open Shaders integration, synchronized capture, and separate model research. **2.20.1 adds an in-headset Settings Benchmark (live A/B of candidate settings against bracketing baselines, timed with the SteamVR compositor) and DLSS CNN presets E/F.** 2.20.0 added NR-only center coverage at 100% NR model resolution, eye-staggered temporal reuse, motion-vector fixes, Performance Overlay removal and the full-resolution NR lock. Saved user settings are not rewritten by the package.

The canonical source is this repository. Large data and environments live outside D:. The runtime retains the `CommunityShaders.dll` filename and asset paths for compatibility.

## Start here

- [Project map](docs/PROJECT_MAP.md): subsystem ownership and maintained entry points.
- [Consolidation audit](docs/PROJECT_CONSOLIDATION_AUDIT.md): provenance, migration, tests, recovery and limitations.
- [Setup and dependencies](docs/SETUP.md): external inputs and repeatable commands.
- [2.20.1 changes](runtime/open-shaders/package/OPENNR-2.20.1-CHANGELOG.md).
- [2.20.1 validation and local update](docs/OPENNR_2.20.1_RELEASE_20260927.md).
- [Shader and settings analysis (what NR can pick up)](docs/OPENNR_SHADER_SETTINGS_ANALYSIS_20260927.md).
- [2.20.0 validation and local update](docs/OPENNR_2.20.0_RELEASE_20260927.md).
- [2.19.1 audit and optimization plan](docs/OPENNR_2.19.1_AUDIT_AND_OPTIMIZATION_20260927.md).
- [2.18.0 validation and local update](docs/OPENNR_2.18.0_RELEASE_20260924.md).
- [Historical research status](docs/RESEARCH_STATUS_PRE_CONSOLIDATION.md): prior experiments and model-quality evidence.
- [Experiment index](experiments/README.md): archived and reproducible research.

## Build and package

From PowerShell at the repository root:

```powershell
.\tools\Build-OpenNR.ps1
.\tools\Build-OpenNR.ps1 -Targets @('CommunityShaders','cpp_tests','Package-AIO-Manual')
& 'E:\OpenNR_Builds\2.20.1\tests\cpp\Release\cpp_tests.exe'
```

The standard local archive is `E:\OpenNR_Builds\2.20.1\dist\OpenNR 2.20.1.7z`.
The build disables automatic deployment. It requires the declared external dependencies and local/private runtime inputs described in setup. This repository does not distribute NVIDIA's private carrier or recovered weights.

## Storage

`config/paths.example.json` documents the external roots. Optional machine overrides belong in ignored `config/paths.local.json`. Python path precedence is explicit CLI argument, `OPENNR_<KIND>_ROOT`, machine configuration, then default. `python tools/opennr_paths.py output` prints the resolved location.

Maintained training/cache/export writers reject destinations physically on D:, including junctions and drive aliases. Native capture and benchmark writers also resolve physical storage before recording. New capture configurations default to `C:/OpenNR/Captures`; existing saved paths remain selected and are validated before capture starts. Legacy experiment scripts are historical tools and require explicit external output paths.

## Acceptance status

2.20.0 source, build, unit-test and package evidence is recorded in the linked release note. In-headset frame time and visual acceptance of NR Coverage and eye-staggered reuse are not yet measured; compare NR Coverage 100% against 85% and 80% in the same scene. The 2.18.0 local VR acceptance (better performance, no visible problems) remains the last headset result for the native Feature 18 line.

No learned model, recovered teacher, or generated target set is promoted. Native Feature 18 resources and capture provenance remain authoritative. No remote release is published.

## Attribution

The runtime inherits Open Shaders and Community Shaders; see its [license](runtime/open-shaders/COPYING) and [branding and attributions](runtime/open-shaders/BRANDING_AND_ATTRIBUTIONS.md). Third-party source and private local artifacts retain their own ownership and terms. See [dependency boundaries](third_party/README.md).
