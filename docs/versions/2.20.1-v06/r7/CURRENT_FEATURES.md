# OpenNR 2.20.1-v06-r7

This package provides the current OpenNR runtime, shaders, feature configurations and assets. Its main VR path is DLSS Super Resolution followed by one stereo-atlas Neural Rendering evaluation, with Natural style and Matched Residual reconstruction.

The foveated crop follows compatible native OpenVR gaze, with shared sampling-grid/motion-guide alignment, configurable gaze smoothing and movement quantization, static-crop comparison and diagnostics. The adaptive GPU-frametime controller uses six quality stages, configurable 10/15/20-point crop drops, Auto or forced-stage selection, separate stage-5/stage-6 NR disable/restore thresholds and coordinated crop/history handoffs.

Native NR tuning exposes intensity, local tone, local structure, skin structure, automatic masking and UI correction. Near-black protection acts inside the NR crop; optional result shaping adjusts the neural correction's strength, brightening, color, highlights, change limits, broad tone and fine detail. The crop edge uses an internal dither blend with rectangle/oval selection. The periphery has Point reconstruction and optional motion-reprojected temporal smoothing.

Shared Upscaling controls provide SR quality/model presets, VR engine render scale, sharpening and supported backend controls. The archive also includes the Open Shaders rendering modules, helper plugin, menu assets, translations and Terrain Helper asset. Feature activation is governed by the installed configuration and runtime support.

See **README.md** for the complete current feature inventory, settings ranges, installation, recommended PSVR2/RTX 5070 setup and short usage guide. See **OpenNR-EyeTracking.md** for gaze-provider behavior and diagnostics.

The NVIDIA NR carrier **nvngx_dlssnr.dll** is intentionally excluded. Supply your compatible copy at **Data/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll**. Skyrim, SKSE and the Address Library appropriate to the game remain external prerequisites.
