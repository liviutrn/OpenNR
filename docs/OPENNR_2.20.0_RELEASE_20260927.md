# OpenNR 2.20.0 local release

Date: 2026-09-27. Scope: the native Feature 18 OpenNR line. The V5 / Turbo replacement graph and the research scripts are on separate branches and are not part of this package.

## What changed

The user-facing changes are in `runtime/open-shaders/package/OPENNR-2.20.0-CHANGELOG.md`. The reasoning is in `docs/OPENNR_2.19.1_AUDIT_AND_OPTIMIZATION_20260927.md`, including the addendum on what was implemented, withdrawn or rejected.

- **NR Coverage.** Centered NR-only region at 100% model resolution; DLSS stays full eye.
  - Guides are cropped from the full-eye per-eye intermediates with region copies. There is no extra pass.
  - The edge is blended with the Edge Blend settings, and Hard Copy is upgraded to Feather.
  - Motion scale stays in full-eye guide pixels.
  - The feature disables itself (with a log line) for non-R32 depth guides, dynamic gaze or adaptive crop.
- **Stagger eyes** for N2 temporal reuse. One native eye per frame; the other eye reuses its previous-frame residual.
- **Full-resolution lock.** `kFullResolutionNeuralRenderingOnly` normalizes model resolution to 100% and turns off adaptive NR, adaptive crop and pre-upscale NR. It applies both at settings load and at the runtime tuning boundary.
- **Performance Overlay removed** via the `OPENNR_PERFORMANCE_OVERLAY=OFF` CMake option (the default).
- **Fixes:** pre-upscale MV scale; guide→color motion scale for temporal reuse and the Motion stabilizer; the stabilizer's shaped/unshaped domain mix.
- **Optimizations:**
  - stabilizer history ping-pong;
  - R32 depth-guide region copy instead of a conversion dispatch;
  - NGX path-proxy scope only on feature creation;
  - LTCG release build.

## Build and verification

| Check | Result |
|---|---|
| Build | `E:/OpenNR_Builds/2.20.0`, MSVC 19.44, VS CMake, `CMAKE_INTERPROCEDURAL_OPTIMIZATION=ON`, same dependency snapshot as 2.19.1 |
| Dependency note | The shared `C:/OpenNR/Dependencies/runtime-2.16.0/vcpkg_installed` tree was regenerated at 16:48 on Sep 27 outside this work and no longer contains the header-only `devbench-api` port. The build uses a private copy staged at `E:/OpenNR_Builds/2.20.0-deps/devbench-api`, taken from the runtime-2.15.0 snapshot (port 1.5.0). The shared dependency folder was not modified. |
| DLL | `CommunityShaders.dll` file version 2.20.0.0, SHA-256 `73C09692EAB1E64C326BBE68005701FA80C3AC5883CD0EC33B52246D2FEB9C78` |
| Native tests | 238 cases, 9,702 assertions passed, including 8 new `[nr][policy]` cases (motion-scale conversion, coverage rectangles, stagger, full-resolution lock) |
| Shaders | `ResultShapingCS`, all three `TemporalReuseCS` entry points and `CopyDepthGuideCS` compile with `fxc cs_5_0` |
| Source contracts / AIO manifest | `Validate-OpenNR-Source` and `Validate-OpenNR-AIO` passed |
| Archive | `E:/OpenNR_Builds/2.20.0/dist/OpenNR 2.20.0.7z`, 228,808,844 bytes, SHA-256 `43B910922E5E3E00AD981D4CAE43030CE87E9777375C644F2D52A8BFA13160E3`; `7z t` passed, 522 files |

## Local installation

- Mod `E:/MGO-RC3-fresh/mods/OpenNR 2.20.0`, extracted from the verified archive (522 files).
- Profile `MGO NSFW - OpenNR 2.20.0`, cloned from the 2.19.1 profile with 2.20.0 enabled and 2.19.1 disabled. Only one enabled mod provides `CommunityShaders.dll`.
- The selected MO2 profile was **not** changed.
- **Grass Optimizations** was enabled at boot in the shared `overwrite/SKSE/Plugins/CommunityShaders/SettingsUser.json`: the `Disable at Boot → GrassOptimizations` flag was set to false and nothing else changed. This file is shared by every profile.
  - The original was backed up to `E:/MGO-RC3-fresh/_OpenNR_Pilot_Backups/2.20.0-install-20260927/SettingsUser.json` (SHA-256 `247EBCAB…6D6B41`).
  - To roll back, copy that file back, or re-check Grass Optimizations under Disable at Boot.

## Not yet established

There has been no headset run. Before changing any defaults, measure in the same scene and settings, alternating 60 s blocks:

- NR Coverage at 100%, 85% and 80%: frame time, reprojection rate, and whether the blended NR edge is visible;
- Grass Optimizations on vs off in a dense exterior;
- Stagger eyes (N2), checked for left/right differences during fast head motion.
