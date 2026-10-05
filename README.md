# OpenNR 2.20.1-v06-r3 — outside crop brightness and color transfer

[r1 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r1) · [r2 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r2) · [r3 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r3)

r3 adds an optional way to make the DLSS5/NR crop less obvious when its brightness or color differs from the surrounding image. It transfers broad tonal changes into a feathered band **outside** the crop, with configurable static dither.

It builds on r2's user-confirmed shaking/trembling fix. The inner feather and pixels inside the crop remain unchanged. **The effect defaults to off.**

Revision: [4dfcd4d](https://github.com/liviutrn/OpenNR/commit/4dfcd4d2fdc547d3d8bdc9dff713016506e9299b).

## Changes from r2

### Estimate the crop's tonal change

A coarse current-frame 16 × 16 map compares paired samples from the original crop and the completed NR composite. Each map cell uses 8 × 8 paired samples to estimate broad brightness and channel-color changes.

The estimate uses bounded log2 gains, reduces confidence near black, and guards invalid/nonfinite values. Sampling can be moved farther toward the crop center to avoid measuring mostly the existing inner feather.

The calculation uses the existing LDR buffer representation; it does not assume a scene-linear buffer or copy NR detail into the periphery.

### Apply correction only outside the crop

A second compute shader applies the estimated brightness/color correction outside the actual rectangle or oval mask. For oval crops, this includes the exterior corner regions.

Correction ramps in beyond the untouched boundary, fades outward over a configurable width, and preserves original alpha. Pixels inside the mask are protected. A bounded application region and eye-local coordinates prevent correction from leaking into the other eye.

Sampling farther inward changes only the tone estimate; it does not modify the crop interior or its existing feather.

### Add static dither to the outward feather

Small screen-space dither breaks up the fade. It does not change with a frame index, so the effect introduces no animated-noise sequence. Width, falloff, dither strength, and boundary ramp can be tuned independently.

No new temporal accumulation or history is added.

## New live controls

The foveated Edge Blend controls contain **Outside NR tone transfer**. Changes are live and use the existing settings save/load path.

| Control | Default | Range | Effect |
|---|---:|---:|---|
| Enable | Off | On/off | Toggle the outside correction |
| Brightness | 0.65 | 0–1 | Strength of luminance transfer |
| Color | 0.30 | 0–1 | Strength of chromatic transfer |
| Fade width | 128 px | 8–512 px | Reach into the surrounding image |
| Falloff | 1.00 | 0.5–2 | Shape of the outward fade |
| Static dither | 0.15 | 0–1 | Subtle breakup of the feather |
| Boundary ramp | 8 px | 0.5–64 px | Fade correction in from the protected edge |
| Tone limit | 0.50 stops | 0–1 stops | Bound estimated/applied gain magnitude |
| Sampling inset | 8% | 0–25% | Sample farther toward crop center |

Widths are output-image pixels. If correction is too weak, a 15–25% sampling inset can measure beyond more of the inner feather. If a halo appears, reduce brightness/color or widen the outside fade. The correction extrapolates tone; scene-dependent differences can still leave a visible boundary.

## Performance measurement

**Measure outside tone GPU cost** uses the existing nonblocking GPU profiler. With runtime profiling enabled, the section open, and the effect active, it shows the latest and rolling-average sum of map and application timings for **both eyes**.

These are steady-state pass timings. First-use shader compilation and resource creation are excluded. The measurement checkbox is session-only; turn it off after tuning to remove capture-query overhead. The passes also appear as `NeuralRendering::OutsideTone*` profiler events.

The requested **0.1–0.2 ms** is a target, not a measured or guaranteed maximum. Wider application bands cover more pixels and can cost more.

The implementation adds no full-frame copy or CPU pixel readback. One small map is reused sequentially for the eyes. When disabled, it adds no new GPU allocation or dispatch; zero transfer strengths or a zero tone limit also skip the new dispatches.

## Integration and failure handling

- The effect runs after successful NR compositing.
- Full-eye and pre-SR routes skip it.
- Controls do not trigger native NR recreation, gaze filtering, or history resets.
- r2 crop placement, sampling phase, guide alignment, and temporal correspondence are retained.
- FPS controller policy, neural fine tuning, sequential-pass tuning, and the existing inner feather are retained.
- Shader/resource failure or an unsupported target skips the tone effect and reports status, without latching a native NR failure.
- Shader-cache clearing allows failed initialization to be retried.

Devbench adds `configureOutsideTone` for validated live changes and `outsideToneStatus` for settings and last application frame/eye count. Configuration changes persist through the existing save action.

## Verification and remaining limits

Source replay matched all 12 changed runtime files. Eighteen critical r2 gaze/history/grid/controller/compositor files remained byte-identical. Existing r2 policy, geometry, and image-oracle checks were rerun.

New checks covered 1.2 million outside-policy points and 18 synthetic image cases: interior/alpha preservation, identity transfer, eye isolation, rectangle/oval bounds, fade continuity, static-noise bounds, black/nonfinite protection, and gain limits. Eight CPU/HLSL buffer-layout checks, eight FXC shader checks, full Windows compilation, and package manifest checks passed.

The independent [r3 package audit](https://github.com/liviutrn/OpenNR/actions/runs/37335672597) compared both archives: r3 adds exactly two tone-transfer shaders, changes the DLL, removes no files, and leaves all existing shader/other payloads unchanged.

Actual VR seam quality, GPU cost, and coexistence across all runtime combinations remain unmeasured in this environment. No claim of a universal 0.2 ms ceiling or complete visual acceptance is made. Possible slight residual flickering reported with r2 is not addressed by this tonal correction.

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
