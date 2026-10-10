# OpenNR 2.20.1-v06-r10 Stable

DLSS Super Resolution and DLSS 5 Neural Rendering for Skyrim VR, with gaze-tracked foveation and automatic GPU-frametime management.

## Features

- **One stereo-atlas NR evaluation** for both eyes, with matching depth/motion guides.
- **Native SteamVR/OpenVR gaze tracking**, configurable crop regions, optional gaze smoothing and movement quantization.
- **Full-resolution NR inside the active crop**, with Natural style and Matched Residual reconstruction.
- **Six-stage Adaptive Performance:** 100/90/80/70/60% relative crop defaults, then NR off with your selected crop restored. Stages 2–5 are independently configurable; Auto and Force stage 1–6 are available.
- **GPU budget and recovery controls**, separate stage-5 disable/stage-6 re-enable thresholds, transition holds and cooldown.
- **Native NR tuning:** intensity, local tone, local structure, skin structure, automatic masking and UI correction.
- **Near-black protection** and optional NR result shaping.
- **Oval/Rectangle inner edge blending**, point periphery reconstruction and optional temporal periphery smoothing.
- **DLSS SR quality/model options, engine render scale and sharpening.**
- Bundled **Open Shaders lighting, materials, terrain, vegetation, water and utility modules**.

Crop percentages describe dimensions per eye and are relative to your selected crop. NR resolution is 100% in every active stage.

**[Complete feature guide and controls](https://github.com/liviutrn/OpenNR/blob/release/2.20.1-v06-r10-stable/README.md)**

Download **OpenNR-2.20.1-v06-r10-stable.7z** below. The NVIDIA NR library **`nvngx_dlssnr.dll` is supplied separately** at `Data/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll`. Compatible NVIDIA hardware/driver, Skyrim, SKSE and the appropriate Address Library are required; gaze following requires a compatible native eye-tracking provider.

Custom fork with upstream lineage in [Open Shaders](https://github.com/alandtse/open-shaders) and [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders).
