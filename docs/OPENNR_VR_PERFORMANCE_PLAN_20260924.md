# OpenNR VR performance pass — 2026-09-24

Target for the next version: reduce delivered VR frame time while preserving
native Feature 18 depth, motion vectors, stereo isolation, and temporal quality.
The current working tree calls itself 2.16.0; it is not committed as a release.

## Key constraint

OpenNR receives the rendered image and engine guide buffers. It can reconstruct
detail and stabilize some noise, but cannot reliably invent missing GI,
reflections, volumetric light, shadows, geometry, or material response. NVIDIA's
Ray Reconstruction performance argument concerns replacing ray-tracing
denoisers in a renderer that exposes the relevant signals. It does not imply
that disabling Open Shaders lighting passes is visually free in this fork.

## Ranked experiments (one change at a time)

| Rank | Current source default | A/B candidate | Expected tradeoff |
| --- | --- | --- | --- |
| 1 | VR SSGI: GI off, AO on, half resolution, 3 slices / 6 steps, temporal denoiser and blur on (`ScreenSpaceGI.h`) | AO 2 slices / 4 steps, then quarter resolution separately | Lower AO march cost; watch halos, stereo disagreement, shimmer, and depth edges. Do not disable the denoiser as a presumed NR replacement. |
| 2 | Skylighting: probe grid quality 2, incremental and reduced-frequency updates off (`Skylighting.h`) | First enable incremental updates, then two-frame occlusion/probe intervals in a separate run | Lower update cost if this pass is expensive; watch delayed shadows, head-motion lag, and eye mismatch. |
| 3 | VR VRS disabled (`VRS.h`) | Enable default ring preset on supported NVIDIA hardware | Saves peripheral pixel shading, not necessarily full-screen NR inference. Inspect per-eye artifacts at ring boundaries and gaze changes. |
| 4 | Grass optimization: culling and mid/far LOD on, mesh LOD off (`GrassOptimizations.h`) | Test mesh LOD and modest distance/density adjustments independently | Potential raster and draw-cost savings; NR cannot reconstruct omitted grass silhouettes. |
| 5 | Volumetric exterior/interior quality 2 (`VolumetricLighting.h`) | One quality step lower for each separately | May save pass time; atmospheric structure can disappear. |
| 6 | Dynamic cubemap SSR on (`DynamicCubemaps.h`) | Test SSR off only in reflection-heavy scenes | May save reflection work; NR cannot recreate missing reflections. VR change may require restart. |

Also measure screen-space shadows, subsurface scattering, fog, cloud shadows,
and water passes before changing them. Their cost is scene-dependent and their
visual contribution is not a neural-denoising substitute.

## Measurement and promotion gate

Capture the same interior and exterior path with fixed weather, gaze route,
render scale, DLSS mode, NR mode, and SteamVR settings. Record per-pass GPU
timings, CPU frame time, delivered frames/reprojection, both eyes, and total
GPU memory. Compare baseline, each single change, and the combined winner.
Inspect motion, disocclusions, transparencies, fine grass, AO edges, and
reflections in the HMD. Reject a candidate that saves an isolated pass but
increases overall frame time or harms temporal/stereo appearance. A default
change and package upversion require this evidence plus a clean release tree.

## Source references

- Local defaults: `runtime/open-shaders/src/Features/ScreenSpaceGI.h`,
  `Skylighting.h`, `VRS.h`, `GrassOptimizations.h`, `VolumetricLighting.h`,
  and `DynamicCubemaps.h` in the same directory.
- [NVIDIA on Ray Reconstruction and denoiser replacement](https://blogs.nvidia.com/blog/ai-decoded-ray-reconstruction/).
- [Microsoft DirectX VRS specification](https://github.com/microsoft/DirectX-Specs/blob/master/d3d/VariableRateShading.md).
- [Open Shaders API and live feature controls](https://github.com/alandtse/open-shaders/blob/dev/API.md).
