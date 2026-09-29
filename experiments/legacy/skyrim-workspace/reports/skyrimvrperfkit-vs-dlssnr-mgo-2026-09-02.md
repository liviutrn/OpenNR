# SkyrimVRPerfKIT 0.1.1 vs. DLSSNR-MGO-VR 0.3.2

Investigation date: 2026-09-02  
Nexus item: [SkyrimVRPerfKIT Custom-Region DLSS5 Neural Rendering](https://www.nexusmods.com/skyrimspecialedition/mods/182089)  
Compared package: `D:\.CODEX_Projects\DLSS_5_SKYRIM\dist\DLSSNR-MGO-VR-0.3.2-mgo-vr.4-private-dev-PRIVATE-DLSSNR-ONLY-MO2.zip`

## Executive conclusion

Do not replace the current MGO DLSSNR implementation with SkyrimVRPerfKIT, and do not install both stacks together. The Nexus build is a separate, experimental SkyrimVRPerfKIT/Streamline stack whose own page warns against using it with Community Shaders/Open Shaders, ENB, or ReShade. It is not a drop-in update to the current package.

The best feature to investigate for selective adoption is its NVAPI Variable Rate Shading (VRS) path: concentric eye-accuracy regions, directional shading rates, boundary dithering, and automatic suspension around UI/terrain-sensitive passes. That is materially different from the current `VRStereoOptimizations` feature, which is stereo reprojection/G-buffer reuse rather than NVAPI VRS. Port the idea at source level as an optional, default-off Open Shaders feature only after a measured baseline.

The Nexus performance claim is not yet demonstrated. The page supplies no reproducible FPS/frame-time table, test scene, headset refresh rate, driver protocol, or before/after capture. The author also describes DLSSNR as having significant overhead/issues in the discussion, and a user reported NR dropping out until a game restart. Treat the claimed improvement as a hypothesis, not an established result.

Our current branch already contains the main render-resolution innovation presented as “DLSSperf,” plus more explicit VR-specific DLSSNR work: per-eye isolation, Full Eye mode, 50/75/100% model-cost processing with full-resolution display output, temporal-history reset handling, failure latching, and stereo synchronization. These are still not live-acceptance proof: the final audit found a correctly injected SkyrimVR process with `CommunityShaders.dll` loaded, but no `CommunityShaders.log`, Feature 18 create/evaluate marker, two-eye visual confirmation, or headset frame-time measurement.

## Scope and instruction separation

The user request was to investigate the Nexus build, compare its features with the latest local DLSS5/MGO implementation, identify transferable improvements, and produce a recommendation.

The attached package documents (`README-PRIVATE-FULL.txt`, `CHANGELOG.md`, and `DLSSNR-private-dlssnr-only-manifest.json`) were treated as implementation evidence and caveats only. Their installation, launch, rollback, and tuning text was not treated as a new user instruction and was not executed as part of this report. No source, MO2 profile, game installation, or package was modified.

## Evidence reviewed

- Nexus description and file metadata: [main page](https://www.nexusmods.com/skyrimspecialedition/mods/182089), [files tab](https://www.nexusmods.com/skyrimspecialedition/mods/182089?tab=files), and [posts](https://www.nexusmods.com/skyrimspecialedition/mods/182089?tab=posts).
- Author source fork and the public feature branches: [DLSSNR-VR](https://github.com/YtzyFvra/skyrim-community-shaders/tree/feature/dlssnr-vr), [DLSS Enhancer](https://github.com/YtzyFvra/skyrim-community-shaders/tree/feature/DLSSenhancer), [VRS](https://github.com/YtzyFvra/skyrim-community-shaders/tree/feature/VRS), [DeepDVC](https://github.com/YtzyFvra/skyrim-community-shaders/tree/feature/dvc), and [Screenshot](https://github.com/YtzyFvra/skyrim-community-shaders/tree/feature/Screenshot).
- Local source repository: `D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d`.
- Current package documentation, manifest, archive inventory, hashes, and FOMOD structure.
- Active MO2 state under `E:\MGO-RC3-fresh`, profile `Mad God Overhaul - NSFW`, plus a read-only process/module/log check.

## What the Nexus build actually is

The current Nexus file is SkyrimVRPerfKIT 0.1.1, updated 29 August 2026. The file page lists one approximately 1.9 MB archive. The small archive is not equivalent to a self-contained DLSSNR runtime: the page says DLSSNR 310.8 must be supplied separately, and it describes stock 310.8 as Blackwell/SM120-only while directing RTX40 users toward an unofficial Ada-patched runtime.

The page presents these feature groups:

| Nexus feature | Public status/evidence | Practical interpretation |
|---|---|---|
| Custom-region DLSS / DLSS Enhancer | Early PR/experimental language | Per-eye or subrect DLSS plus a render-resolution/performance path. |
| VRS | Early PR/experimental language; separate public VRS branch | NVAPI variable-rate shading around eye-accuracy regions. |
| DeepDVC | Early PR; page explicitly notes performance cost | Optional neural post-filter for image quality, not a performance feature. |
| Screenshot | Early PR; lossless/asynchronous/custom left-eye crop claim | Useful VR capture workflow. |
| EasyPost, Atmosphere, Character Lighting | In progress and described as conflicting with ENB/ReShade/CS/OS | A separate visual replacement stack, not a safe MGO add-on. |
| Environment-aware grading | In progress | A potentially useful control-system idea, but not a finished acceptance-ready feature. |

The author’s public fork exposes these as separate branch lines rather than one clean, merged Open Shaders implementation. In particular, `feature/dlssnr-vr` does not contain the named DLSS Enhancer, NVAPI VRS, or DeepDVC modules. Therefore, the Nexus page should not be read as proof that every branch feature is present, mature, or mutually compatible in the released archive.

The discussion is also important evidence. A user reported that DLSSNR could drop out under performance pressure and could not be restarted without restarting the game; the author said they would reproduce and improve reset behavior. Other posts warn against mixing KIT with Open Shaders and mention visual/UI problems in earlier runs. These are anecdotal reports, not a benchmark, but they lower confidence in adopting the stack wholesale.

## Current local implementation snapshot

The compared package is `DLSSNR-MGO-VR 0.3.2-mgo-vr.4-private-dev`.

- Archive SHA-256: `883187FCD7B56C2C2532E8BFD39FE2630296EE773D20659B6A3F1ED050299A6A`.
- Source commit recorded by the manifest: `3bd930002a96135cff5b092a7e55e11cf28bc912`.
- Source branch: `feature/dlssnr-vr`.
- Manifest state: `SourceDirty=true`; the repository is one commit ahead of its remote and has local modifications in the DLSSNR, foveated-render, performance-mode, and synchronization files. This is a development package, not a frozen reproducible release.
- Runtime: stock signed RTX50-oriented `nvngx_dlssnr.dll` 310.8, `nvngx_dlss.dll` 310.7, Streamline 2.12 files, and rebuilt `CommunityShaders.dll` 2.10.1.0.
- Packaging: one MO2/FOMOD package with no Feeder, RenoDX, ReShade wrapper, root proxy, or frame-generation DLLs in the selected profile.

The relevant implementation is visible in:

- `src\Features\Upscaling\PerfMode.*`: engine render targets at a smaller RenderRes while DLSS/DLSSNR writes to a private full DisplayRes texture; post, menu, viewport, depth, refraction, and fade paths are guarded against the usual partial-screen/downscaled-menu failures.
- `src\Features\Upscaling\FoveatedRender.*`: per-eye subrect routing, Full Eye no-crop mode, stretch and edge-blend modes, and current Default/Faster DLSS routes.
- `src\Features\Upscaling\NeuralRendering\Renderer.*`: per-eye and stereo application, shared D3D12 synchronization, 50/75/100 model-cost selection, scaled guides/motion vectors, full-resolution resolve, reset, and failure-latch state.
- `src\Features\Upscaling\NeuralRendering\Integration.*` and `src\Features\Upscaling.cpp`: overlay/menu, loading, scene, and temporal-history reset handling.
- `src\Features\ScreenshotFeature.*`: asynchronous lossless screenshot capture with VR crop/eye handling.
- `src\Features\VRStereoOptimizations.*`: optional stencil/depth/G-buffer stereo reprojection. This is not NVAPI VRS and should not be counted as the Nexus VRS feature.

The active profile audit found `+DLSSNR` enabled in `E:\MGO-RC3-fresh\profiles\Mad God Overhaul - NSFW\modlist.txt`, with CSX and the Community Shaders VR cache disabled for the isolated path. A final read-only process check found SkyrimVR running via USVFS with `CommunityShaders.dll`, `openvr_api.dll`, `sksevr_steam_loader.dll`, and `usvfs_x64.dll` loaded. That proves the modded process boundary, not Feature 18 output or headset acceptance.

## Capability comparison

| Capability | Nexus KIT 0.1.1 | Current DLSSNR-MGO-VR | Recommendation |
|---|---|---|---|
| Full render-resolution/performance path | Called DLSSperf; shrinks engine RTs and keeps a full-resolution DLSS output | Already implemented in `PerfMode`, including post/menu/viewport/depth safety work | Keep and validate. This is not a missing Nexus feature. |
| DLSSNR core | Separate KIT stack; runtime is supplied separately | Direct Open Shaders/Community Shaders route with selected signed runtime | Keep current stack; do not mix binaries. |
| Stereo safety | Claims custom left-eye/subrect handling and multiple modes | Default per-eye isolation, Full Eye no-crop, stereo batching and D3D12 fence-ring synchronization | Current implementation is more explicit; accept only after real two-eye testing. |
| Foveation/subrect | DLSS sub-region plus VRS foveal region | Foveated subrect, per-eye UV handling, stretch/Feather/Dither/Hard blend, Full Eye | Reuse the shared region model for VRS; no wholesale port needed. |
| DLSS model cost | No equivalent public 50/75/100 model-cost feature identified | 100/75/50 model processing with full-resolution display/resolve; 75% is the current recommended cost point | Keep; benchmark quality and frame time. |
| NVAPI VRS | Separate branch with concentric rings, directional rates, dithering, UI/terrain suspension, diagnostics | Not present. Existing `VRStereoOptimizations` is a different reprojection optimization | Highest-value selective port candidate. Default off and fail closed. |
| DLSS Enhancer modes | Default/Faster/Extreme; Extreme combines regions into one evaluation and is marked not recommended | Current PerfMode + foveated Default/Faster paths already cover the useful architecture | Borrow UX/latching/resource-recreation ideas only; reject Extreme for now. |
| DeepDVC | Optional neural post filter; page says it costs performance and needs extra Streamline payload | Not included | Low priority; only a separate visual-quality experiment. |
| Screenshot | Async lossless custom-region/eye capture | Screenshot feature and `Screenshot.ini` already present | No port needed; compare final-composite behavior later if desired. |
| Post/atmosphere/skin lighting | KIT replacement shaders and environment-aware grading; explicitly conflict-prone and in progress | Open Shaders already has post/color grading, fog/atmosphere, skin/SSS, weather and related shader features | Do not replace current MGO visual stack. Consider only environment-aware control logic. |
| Runtime reset | Public discussion exposes restart-required NR dropout reports | Current reset history, overlay/menu suppression, scene/loading reset, and failure latch/status UI exist | Preserve current design; add explicit manual reset/diagnostic telemetry if useful. |
| Compatibility/packaging | Standalone experimental stack; page warns against CS/OS/ENB/ReShade mixing | Isolated MO2/FOMOD DLSSNR-only package | Keep one controlled stack. Never install KIT beside it. |

## Innovations worth taking

### 1. NVAPI VRS, conditional recommendation

This is the only major performance mechanism in the Nexus source that is genuinely absent from the current DLSSNR branch. The public VRS branch builds a shading-rate surface from concentric elliptical regions, supports directional 2x1/1x2 and 4x2/2x4 rates, dithers ring boundaries, shares the foveal subrect state, and disables or suspends VRS around UI and terrain-sensitive work.

That could complement the current pipeline: DLSSNR reduces reconstruction/model cost while VRS reduces peripheral pixel-shader cost. The benefit is workload-dependent and may be small if the MGO bottleneck is CPU, geometry, transparency, or post-processing. It must not be advertised as an improvement until GPU frame time and reprojection/drop statistics show one.

Safe integration shape:

1. Forward-port the source-level VRS controller to the current Open Shaders hooks and APIs; do not copy KIT DLLs or install its archive.
2. Reuse the current Full Eye/foveated UV state so the DLSS region and VRS region cannot disagree.
3. Make it restart-gated, default-off, and fail closed to 1x1 shading if NVAPI or the rate surface is unavailable.
4. Suspend it for menus/UI, terrain blending, particles/transparency, and any pass where artifacts are observed.
5. Add a visible diagnostic state and counters for active rate, suspension reason, NVAPI failure, and fallback.

Risk is medium-to-high: the public branch is from April 2026 and is separate from the newer local DLSSNR changes, so it should be treated as a forward-port, not a cherry-pick assumption.

### 2. Environment-aware preset interpolation

The Nexus idea of changing grading parameters from scene variables is interesting, but the KIT implementation is described as in progress. The safer adaptation is to extend the existing Open Shaders weather/time-of-day/override path with bounded, inspectable interpolation. Do not replace the current post or atmosphere shaders with KIT’s conflicting replacement stack.

This is a visual consistency feature, not a proven performance improvement. It should be evaluated separately from frame-time work.

### 3. Explicit NR reset and failure diagnostics

The Nexus dropout report reinforces the value of a user-visible reset path. The current code already resets history on overlay/loading/scene transitions and latches failures to avoid repeated unsafe evaluation. A small manual “Reset NR history” action, plus a displayed last reset/failure reason, would make recovery and testing easier without adopting KIT’s lifecycle.

This is a reliability/diagnostics improvement, not a reason to use the Nexus runtime.

## Features not recommended for adoption now

- Do not install SkyrimVRPerfKIT beside Open Shaders/Community Shaders. The Nexus page explicitly describes the stacks as conflicting.
- Do not treat the 1.9 MB archive as a complete or more reproducible DLSSNR runtime; it depends on separately sourced runtime files.
- Do not adopt the DLSS Enhancer “Extreme” combined-strip/one-evaluation mode. Its own public source marks it as not recommended because of artifact risk.
- Do not add DeepDVC to the performance profile. It is a quality post-filter with an acknowledged performance cost and extra runtime/packaging surface.
- Do not port KIT’s EasyPost/Atmosphere/Character Lighting binaries into MGO. The current package already carries Open Shaders visual systems, and the Nexus page marks these replacements as in progress and conflict-prone.
- Do not use the Nexus “Safe to use” label, forum anecdotes, DLL presence, or a successful injection as proof of VR performance or visual correctness.

## Recommended implementation roadmap

### Stage 0 — Freeze and establish the baseline

Before any VRS work, commit or otherwise freeze the current known-good source changes and rebuild with `SourceDirty=false`. Then obtain a fresh MGO launch with:

- Feature 18 create and evaluate markers;
- both-eye output with no center seam, eye swap, crop, menu shrink, or blue/UI corruption;
- 100%, 75%, and 50% model-cost results;
- GPU/CPU frame time, VRAM, headset refresh/reprojection, and dropped-frame data in a fixed scene;
- reset behavior after loading, menu open/close, and scene transition.

The current process/module check is a useful launch milestone, but the absent `CommunityShaders.log` and Feature 18 markers mean this stage is not yet complete.

### Stage 1 — Prototype NVAPI VRS

Forward-port only the VRS feature into a development branch. Test four states: VRS off, Default rings, Faster rings, and fallback after capability/error. Repeat with Full Eye and cropped foveation. Measure GPU frame time and visual artifacts in the same scene; reject it if it helps only synthetic counters but worsens headset stability or image quality.

### Stage 2 — Improve recovery UX

Add an explicit NR-history reset action and compact reason/counter telemetry. Keep the existing automatic reset and failure latch. This should be independently testable and should not require installing a second rendering stack.

### Stage 3 — Optional visual experiments

Only after performance and lifecycle are stable, evaluate environment-aware grading and DeepDVC as separate, opt-in visual branches. Record quality and performance separately so an image-quality improvement is not mistaken for an FPS improvement.

## Final recommendation

Keep the current DLSSNR-MGO-VR architecture and package as the base. Do not install the Nexus build and do not merge its visual stack. Selectively investigate the public NVAPI VRS concept as an optional source-level feature, then consider a manual NR reset/telemetry improvement. Treat all claimed performance gains as unverified until the current baseline and VRS A/B measurements are captured in the headset.

No installation, source, profile, or configuration changes were made for this report.
