# OpenNR 2.20.1-v06-r10 Stable

OpenNR combines DLSS Super Resolution with DLSS 5 Neural Rendering, gaze-tracked foveation and automatic GPU-frametime management for Skyrim VR. Neural processing is concentrated in a configurable region around your gaze, with full NR sampling resolution inside the active crop.

**[Release page](https://github.com/liviutrn/OpenNR/releases/tag/opennr-2.20.1-v06-r10-stable)** · **[Download the complete mod archive](https://github.com/liviutrn/OpenNR/releases/download/opennr-2.20.1-v06-r10-stable/OpenNR-2.20.1-v06-r10-stable.7z)**

## Rendering

- **DLSS SR followed by DLSS 5 NR:** Super Resolution supplies the image used by the neural-rendering stage.
- **Single stereo-atlas evaluation:** both eye regions share one NR evaluation, with separate eye placement, depth/motion guides and atlas guards.
- **Full-resolution NR:** active NR stages use 100% model resolution for their crop. SR quality and engine render scale are separate controls.
- **Natural visual style and Matched Residual reconstruction:** fixed rendering choices with configurable native NR tuning and optional result shaping.
- **Coordinated crop transitions:** resident resources, matching input/history data and residual handoffs support crop-size changes.
- **Runtime recovery:** NR status, failure diagnostics and Reset Neural Rendering are available.

## Gaze-tracked crops and edge blending

- Native **SteamVR/OpenVR gaze tracking**, with a static selected-crop fallback when valid gaze is unavailable.
- Full Eye, centered and nasal-convergence crop presets, plus editable crop regions.
- Gaze smoothing from **0–250 ms**; zero adds no optional gaze filtering.
- Optional crop movement quantization from **0–64 input pixels**, and a fixed-crop comparison mode.
- **Oval or Rectangle** composite edges with inner dither blending. Oval changes the composite shape; NR evaluates its rectangular bounding region.
- Point periphery reconstruction, optional motion-reprojected temporal periphery smoothing and region visualization.
- Eye-tracking diagnostics for provider, validity, crop position, fallback and history-reset state.

Crop percentages describe **width and height per eye**. A 50% × 50% rectangular crop covers 25% of the eye image, before alignment and guards.

## Adaptive Performance

The six-stage controller uses SteamVR application GPU frametime to adjust crop coverage. It supports **Auto** and **Force stage 1–6**.

| Stage | Crop relative to your selected crop, per axis | NR |
|---|---:|---|
| 1 | 100% | On, 100% resolution |
| 2 | 90% default, configurable | On, 100% resolution |
| 3 | 80% default, configurable | On, 100% resolution |
| 4 | 70% default, configurable | On, 100% resolution |
| 5 | 60% default, configurable | On, 100% resolution |
| 6 | 100% — selected crop restored | Off |

Stages 2–5 each have an independent in-game dropdown: **60–100% in 5-point increments**, in descending order. Equal stage percentages are allowed.

For a selected 50% crop, the default active sizes are **50/45/40/35/30%** of each eye's width and height. Stage 6 restores the selected 50% crop while bypassing NR.

| Control | Range / choices | First-run default |
|---|---|---:|
| Controller | On / Off | On |
| Mode | Auto / Force stage 1–6 | Auto |
| GPU budget | 10–30 ms | 20 ms |
| Recovery headroom | 0.5–5 ms | 1 ms |
| Disable NR above — stage 5 only | 10–50 ms | 24 ms |
| Re-enable NR below — stage 6 only | 1–50 ms | 14 ms |
| Frametime smoothing | 0–1000 ms | 250 ms |
| Decrease hold | 0–2500 ms | 350 ms |
| Increase hold | 0–5000 ms | 1200 ms |
| Cooldown | 0–5000 ms | 1000 ms |
| NR transition smoothing | 0–500 ms | 150 ms |

The controller coordinates crop commits, holds, cooldown and NR resume transitions. Re-enable must be lower than Disable. Returning from stage 6 waits for the active crop to commit, resets stale NR history and fades the correction back in. Force mode uses the same transitions as Auto.

## Neural Rendering controls

Native model controls are separate from image-space Result Shaping.

| Native control | Range / choices |
|---|---|
| Intensity | 0–2 |
| Local Tone | 0–2 |
| Local Structure | 0–2 |
| Skin Structure | −1–2 |
| Automatic Mask | On / Off |
| UI Correction | On / Off |

Optional **NR Result Shaping** provides edit-strength, brightening, color, highlights, brightening/darkening limits, color-change limits, large-scale tone and fine-detail controls.

**Near-black protection** reduces positive neural lifting in originally near-black pixels inside the NR region. Strength, dark threshold and positive-lift onset are configurable. It works independently of Result Shaping, and display protection is applied after raw neural history is recorded.

## Upscaling and settings

- DLSS SR quality options: Native AA, Quality, Balanced, Performance and Ultra Performance.
- SR model-preset selection, engine render scale and optional DLSS sharpening up to 3.
- Shared upscaling backend selection; NR uses the compatible DLSS route.
- Load, save and reset settings.
- Runtime profiling, status displays and optional Remote Control/DevBench diagnostics.

Saved settings determine your active configuration. Feature availability depends on the supported runtime, loaded libraries and installed profile.

## Included rendering modules

The package includes Open Shaders rendering and utility modules. Inclusion does not mean every module is enabled simultaneously.

| Area | Included modules |
|---|---|
| Upscaling, VR and display | Upscaling, VR, VRS, HDR Display, Post Processing, Performance Overlay, OpenNR Capture |
| Lighting and atmosphere | Cloud Relight, Cloud Shadows, Dynamic Cubemaps, Exponential Height Fog, Image Based Lighting, Interior Sun, Inverse Square Lighting, Light Limit Fix, Linear Lighting, Procedural Sun, Screen Space GI, Screen Space Shadows, Skylighting, Sky Sync, Volumetric Lighting, Volumetric Shadows |
| Materials and characters | Extended Materials, Extended Translucency, Hair Specular, Skin, Subsurface Scattering, TruePBR, Vanilla Fresnel |
| Terrain and vegetation | Foliage Lighting, Grass Collision, Grass Lighting, Grass Optimizations, Horizon Fix, LOD Blending, Terrain Blending, Terrain Helper, Terrain Shadows, Terrain Variation, Wind |
| Water and weather surfaces | Unified Water, Water Effects, Wetness Effects |
| Tools and integration | CS Editor, CS Utility, Effects11, Feature Overwrites, Remote Control, Scene Manager, Screenshot, Weather Picker |

## Compatibility and package contents

The custom gaze/controller route targets **Skyrim VR with SteamVR/OpenVR**. Gaze following requires a compatible native eye-tracking provider. NR requires compatible NVIDIA hardware, driver and `nvngx_dlssnr.dll`, with the DLSS route active. The VR NR route requires the engine-resolution hook; Frame Generation must be disabled.

The archive contains the plugin, helpers, shaders, configurations, menu assets and bundled SR/backend libraries. **`nvngx_dlssnr.dll` is supplied separately**, at `Data/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll`. Skyrim, SKSE and the appropriate Address Library are prerequisites.

This is a custom fork with upstream lineage in [Open Shaders](https://github.com/alandtse/open-shaders) and [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders). The runtime retains the `CommunityShaders.dll` name. Bundled licenses and attribution accompany their assets.
