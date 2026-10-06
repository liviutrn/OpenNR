# OpenNR 2.20.1-v06-r5 — targeted outside seam correction

Build and package audit pending. GPU timing and headset quality require an in-game comparison.

## Changes from r4

r5 adds a **Targeted seam curve** mode to the existing outside NR tone transfer.
It uses the completed NR output already available; it adds no neural
evaluation, second NR instance, or enlarged NR crop.

- Fit a local curved RGB correction as a function of original brightness.
  Separate the average tone shift, contrast response, and shadow/highlight
  curvature instead of applying one gain/offset response across every tone.
- Estimate from paired original and completed pre-feather NR samples close
  to the actual rectangle/oval boundary. Sample focus preferentially weights
  the nearest inward samples; no distant inset is required.
- Fit confidence suppresses poorly explained edits; low-variance patches
  fall back toward an additive tone correction. Flat black can still receive
  a shadow lift when near-black protection is zero.
- Interpolate/smooth coefficients in a common polynomial basis, avoiding
  brightness errors caused by mixing curves with different local origins.
  Smoothing affects only a 16 × 16 map, never the scene image.
- Hold the outside correction before its final fade. Contrast reach can fade
  the contrast/curvature contribution sooner than the average brightness/color
  contribution, reducing a pronounced outer ring.
- Optional near-black protection attenuates positive luminance transfer onto
  near-black pixels. It is outside-only and off by default; enabling it can
  reduce desired NR shadow lifting too.
- Compact the outside application into one dispatch that skips a protected
  interior rectangle. Oval crops skip a conservative inscribed rectangle;
  the exact existing mask test still protects every interior pixel.
- Preserve the r3/r4 estimator shaders byte-for-byte for live A/B comparison.
  The crop interior, inner feather, NR renderer, result shaping/stabilization,
  r2 gaze/motion/grid fixes and FPS-controller policy are unchanged.

## In-game controls

Open **Foveated / Edge Blend → Outside NR tone transfer**, then press
**Use targeted seam defaults**. This enables mode 2 and a starting preset:
brightness 1.0, color 0.65, width 160 px, no dither, boundary ramp 8 px,
sample width 32 px, smoothing 0.35, hold 0.35, contrast/curve 1.0,
contrast reach 0.5, sample focus 0.5, edge and near-black protection zero.
Old saved estimator selections remain selected until you choose the new mode.

| New control | Range | Purpose |
|---|---:|---|
| Tone estimator | 0 / 1 / 2 | r3 legacy / r4 affine / r5 targeted curve |
| Outside contrast transfer | 0–1 | Strength of brightness-dependent contrast change |
| Shadow / highlight curve | 0–1 | Nonlinear tonal change |
| Contrast reach | 0–1 | Fraction of outside width retained before contrast fades; 1 retains the full response |
| Hold before outside fade | 0–0.8 | Fraction of width held before the final fade |
| Outside near-black protection | 0–1 | Limit positive brightness transfer onto near-black pixels |
| Prefer near-boundary samples | 0–1 | Weight the nearest valid inward samples more strongly |

Existing brightness/color strengths, sample width, offset/tone limits, fade
width/falloff, boundary ramp, map smoothing, edge protection and static dither
remain live, configurable and persistent.

If the seam remains weakly corrected, raise color toward 1 and check the
offset/tone limits. If the outside looks like a ring, reduce hold or strengthen
the final falloff; compare contrast reach 0.3–0.7. Increase edge protection
only when correction appears to cross onto differently colored surfaces.
For gray lift in dark regions, try near-black protection; it does not repair
grain or haze inside the NR crop.

## Performance and integration

The new mode uses the same **two passes**, or **three with optional map
smoothing**, per eye as r4. The two reusable coefficient textures total
32 KiB of texel payload. There are no full-image copies, CPU readbacks,
temporal correction history, gaze deadzones, or native history resets.

For a 1000 × 1000 rectangular crop with a 128 px outside width, the compact
dispatch launches approximately 0.582 million content threads instead of
1.578 million. This is a work-count comparison, not a measured speedup.
Map estimation still takes at most 64 sample pairs per 256 cells per eye.

**Measure outside tone GPU cost** shows the summed steady-state cost for both
eyes. Enable runtime profiling first; turn capture off after tuning.
The requested maximum is **0.3–0.4 ms**, but this is not a verified cap.
Fade width, output resolution and GPU matter. First-use shader compilation
and allocation are excluded from the displayed pass timings.

The existing geometry and pre-feather output routing continue to cover moving
gaze, rectangle/oval masks, controller crop transitions, supported atlas and
compact multipass routes, and final neural tuning/result-shaping output.
Full-eye/off routes retain their existing bypass behavior. Unsupported inputs
skip the optional correction without changing the NR recovery state.

## Verification and limits

Exact r4 source contract and independent patch replay; retained r2 critical
file hashes; legacy estimator/renderer identity; twelve CPU/HLSL buffer
layouts; affine and curved tone fixtures; bounded finite corrections; compact
dispatch coverage; existing gaze/grid/controller/outside-mask suites.

Windows compilation, complete source contracts and package comparison are
required build gates. Native NR/headset runtime is unavailable here. No
universal invisible-seam claim: unseen peripheral objects can need different
neural lighting, and this method estimates their appearance from nearby crop
samples. It operates in the existing LDR buffer representation.

## Earlier version pages

[r4](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r4) ·
[r3](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r3) ·
[r2](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r2)

OpenNR is a fork with upstream lineage from
[Open Shaders](https://github.com/alandtse/open-shaders) and
[Community Shaders](https://github.com/community-shaders/skyrim-community-shaders).

## Earlier project documentation

The following notes describe earlier versions.

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

