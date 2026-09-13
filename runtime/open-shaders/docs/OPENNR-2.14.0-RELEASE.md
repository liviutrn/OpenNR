# OpenNR 2.14.0

OpenNR is a Neural Rendering-focused Open Shaders fork with future support for
custom Neural Rendering DLSS models.

## Concise changelog from 0.5.7

- Unified the former OpenNR and OpenNR Capture variants into one `OpenNR 2.14.0`
  package. Capture is compiled and shipped, but its master gate is off by
  default and installation never enables it.
- Renamed the visible `DLSS 5 NR` settings page to **Neural Rendering** while
  preserving internal `DLSSNR` IDs and saved-setting compatibility.
- Promoted the audited Open Shaders VR grass/per-eye/Hi-Z work from PR #630,
  carried opt-in dynamic near clip from PR #615, and kept foveated writeback
  fail-closed on stretch/blend failure.
- Added an in-menu OpenNR Capture guide covering purpose, safety, exact Feature
  18 depth/motion guides, pre/post-NR stages, per-eye output, previews,
  full-resolution cost, and authoritative `frames.jsonl` metadata. Capture
  never records the desktop, headset compositor, or presented swap chain.
- Audited package growth and removed optional RenderDoc, OpenXR, textures,
  meshes, particle-light assets, StreamlineDX12, FidelityFX, PDBs, and personal
  settings from the lean archive. Signed native runtime companions,
  ImGuiVRHelper, and TerrainHelper remain validated.
- Evaluated Cheeky Foveated DLSS 0.3.2, OptiScaler, ReShade, Community Shaders,
  and Streamline. Eye-gaze decoupling, resolution hysteresis, submit-stage
  foveation, wind experiments, and newer runtime swaps remain isolated research
  items until trusted live VR/temporal evidence exists.

## Package and compatibility

The canonical archive is `OpenNR 2.14.0.7z`. It uses the upstream-compatible
`CommunityShaders.dll` filename and SKSE layout intentionally; changing that
runtime identity would break existing loaders and profiles. The package is an
authorized internal test artifact and does not redistribute proprietary NVIDIA
runtime files outside the permitted context.

OpenNR Capture is intended for aligned Feature 18 training/validation data. It
must be enabled deliberately from its own settings page, should use a dedicated
output directory, and can consume substantial disk space. Capture artifacts do
not prove headset, temporal, image-quality, or frame-budget acceptance.

Build and package validation are separate from live Skyrim VR acceptance. Test
native Feature 18 resource binding, both eyes, eye-gaze/foveation behavior,
temporal stability, and repeatable VR frame time on a copied profile before
promoting a future package.
