# OpenNR 2.20.1-v06-r7

Complete OpenNR mod package for the current stereo-atlas Neural Rendering build. The main Skyrim VR path uses **DLSS SR → one stereo-atlas NR evaluation**, with **Natural** style and **Matched Residual** reconstruction.

## Current features

- Native OpenVR gaze-tracked crops, shared guide/motion alignment, zero-smoothing operation, optional pixel quantization, fixed-crop comparison and diagnostics.
- Six-stage adaptive GPU-frametime controller: two relative crop reductions, NR resolution 85% and 70%, then NR off with the selected crop restored. Auto and Force stage 1–6 modes; 10/15/20-point crop drops.
- Separate stage-5 disable and stage-6 re-enable thresholds, timing smoothing, holds, cooldown and coordinated crop/history transitions.
- Native NR intensity, local tone/structure, skin structure, automatic masking and UI correction.
- Near-black protection inside the NR region and optional neural-result tone/color/detail shaping.
- Point periphery reconstruction, optional temporal periphery smoothing, fixed inner Dither blend and Oval/Rectangle edge selection.
- Shared Upscaling quality/model presets, engine render-scale control, sharpening and backend controls, plus the bundled Open Shaders rendering/utility modules.

## Download and use

Download **OpenNR-2.20.1-v06-r7.7z**, not the automatically generated source-code archive. Install it as an OpenNR mod through your mod manager. The archive contains the plugin, helpers, shaders, configuration/assets and bundled SR/backend libraries.

**Only the NVIDIA NR carrier `nvngx_dlssnr.dll` is excluded.** Supply your compatible copy at **`Data/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll`**. Skyrim, SKSE and the appropriate Address Library remain prerequisites.

For the usual PSVR2/RTX 5070 setup: use SteamVR/OpenVR with working PSVR2 Toolkit eye tracking; DLSS Performance (0.5 per axis), Auto VR render scale, Center 50% crop, NR On, adaptive Auto mode, gaze smoothing 0 and optional quantization 0. Start at a 20 ms GPU budget, 1 ms recovery headroom and 20-point crop drops. Keep the near-black settings you already like; strength 1, threshold 0.035 and onset 0.001 are a fresh-profile starting point. Save and restart when the menu requests it.

For FPS comparisons, select a forced stage, close the menu and let the transition settle before measuring. Return to Auto afterward.

**[Complete current-version README and settings guide](https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r7/README.md)**

## Package verification

The runtime is taken from the successful r7 Windows build and remains byte-identical. The release checks every payload against that build's manifest, updates only the current documentation, tests archive CRC and extraction round-trip, verifies the x64 plugin/controls and confirms the NR carrier is absent. **SHA256SUMS.txt**, **release-package-audit.json** and **release-manifest.json** accompany the download. Headset visual acceptance and hardware GPU timings require in-game testing.

Custom fork with upstream lineage in [Open Shaders](https://github.com/alandtse/open-shaders) and [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders); not an official upstream release.
