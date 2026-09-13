# OpenNR 2.15.0 — full changelog since 2.14.2

Release date: 2026-09-13
Comparison baseline: OpenNR 2.14.2 Temporal Reuse Experimental
Package type: local 2.15.0 AIO build; automatic deployment disabled

OpenNR 2.15.0 is the consolidated OpenNR-VR development runtime. It carries
the complete recovered 2.14.x VR/Neural Rendering feature chain and promotes
the adaptive Neural Rendering and adaptive Crop implementation, including
correction 20260913-B, into the main development line.

The runtime compatibility identity is intentionally unchanged: the DLL is
`CommunityShaders.dll`, the SKSE asset paths remain under
`SKSE/Plugins/CommunityShaders/`, and the stable internal menu ID remains
`DLSSNR`. The visible product identity is OpenNR. Existing settings and
feature-enable defaults are preserved; installing or building this package
does not force-enable adaptive NR, adaptive Crop, temporal reuse, capture, or
eye tracking.

## Version-by-version change record

### 2.14.2 baseline — temporal reuse experimental

The 2.14.2 package was the starting point for this comparison. It already
contained an opt-in temporal residual-reuse experiment and the initial VR
Neural Rendering/capture line:

- Added the `Temporal Stability` section and an experimental temporal residual
  reuse control.
- Added `Off`, every second frame, every third frame, and every fourth frame
  cadence choices.
- Added temporal depth and color rejection thresholds.
- Reprojected the accumulated native correction residual with exact engine
  motion vectors, with separate per-eye history, reset, and fallback state.
- Restricted reuse to the native Full Eye, 100%, single-pass normal-rendering
  route. Cropped, foveated, reduced-resolution, and pre-upscale routes stayed
  out of the experiment.
- Included the temporal-reuse and temporal-reprojection shader support.
- Included the then-current VR-focused menu work, OpenNR Capture registration,
  capture metadata path, and optional eye-tracking scaffolding.
- Kept Neural Rendering enabled, Full Eye at 100%, multi-pass and pre-upscale
  disabled, temporal reuse off (`cadence=0`), and capture off in the active
  profile.

The changes below are the cumulative fixes and features carried forward into
2.15.0.

### 2.14.3 — restore identity, carrier, and package gates

- Restored OpenNR and Neural Rendering branding in the menu, settings,
  translations, feature descriptions, and package metadata while retaining
  the compatibility-facing `CommunityShaders.dll` identity.
- Restored the native Feature 18 carrier `nvngx_dlssnr.dll` to the AIO stage
  and made its presence an explicit package check. A plugin build can no
  longer appear healthy while silently omitting the carrier required for NR
  initialization.
- Kept temporal residual reuse opt-in and disabled by default.
- Included the current native full-eye, sequence-disjoint, reset/warm and
  state-aware capture metadata path.
- Included the current VR UI/layout work, OpenXR eye-tracking scaffolding, and
  future-contract scaffolding without promoting a learned student model.
- Added the dedicated `OpenNR-Package` configure path and package validator.
  The validator checks the plugin, carrier, temporal shaders, translations,
  capture payload, and eye-tracking payload before packaging succeeds.

### 2.14.4 — repair ordinary menus, branding, and toggle behavior

- Restored the ordinary-menu Neural Rendering route. Pause, map, and stats
  menus can use the safe post-upscale route; loading screens and the console
  remain fail-closed; entering or leaving a menu invalidates temporal history.
- Restored the OpenNR logo loader and packaged OpenNR logo/branding assets.
- Added the documented `F6` Neural Rendering toggle. Toggling the feature also
  requests a temporal-history reset.
- Preserved the OpenNR Capture route with native Feature 18 motion metadata,
  Full Eye/per-eye output, capture-start history reset, in-menu guide, and
  `frames.jsonl` metadata. Capture remains disabled by default.
- Retained temporal residual reuse under `Neural Rendering → Temporal
  Stability`, still disabled at cadence zero.
- Retained VR stereo/depth history, VRS compatibility, Effects11 DevBench
  actions, readable VR/font/panel work, menu categories/padding, background
  blur, and the DLSS RCAS-off default.
- Added source and package contracts for the ordinary-menu safety and branding
  rules so those regressions fail validation instead of returning silently.
- Established the lean archive boundary: optional OpenXR/RenderDoc payloads
  and the development PDB are excluded from the release archive.

### 2.14.5 — recover the complete known feature chain

The 2.14.5 comparison found that an older source-line swap had lost several
upstream VR features and package inputs together. Those features and repairs
are retained in 2.15.0.

#### Runtime features recovered

- VR stereo/depth history: Eye 1 geometry recovery, stereo reprojection
  blending, final-depth classification, and invalid-history rejection.
- Grass Optimizations: per-eye culling, Hi-Z/SPD occlusion, compacted indirect
  draws, dynamic-resolution handling, VR hook and eye-transform fixes, bucket
  sizing, shader-cache protection, and HMD-size handling.
- Grass diagnostics: GPU-pass profiling and vanilla-path A/B instrumentation.
- Dynamic Near Clip: opt-in VR near-plane adaptation with corrected
  translations and diagnostics.
- Skylighting early occluder rejection.
- Simple tree-material wetness response.
- Address Library compatibility floor raised to 0.264.0.
- VRS-compatible surface and guarded VR fallback handling.
- Effects11 DevBench setting actions, including preservation of current values
  when settings are re-registered.
- HDR Display: HDR10/PQ BT.2020 output, float16 HDR buffers, configurable
  paper-white/peak/UI brightness, Windows HDR detection, HDR-aware tonemapping,
  and separate scene/UI compositing with safe SDR fallback.
- OpenNR Capture unified variants, native Feature 18 guides/metadata, per-eye
  output, `frames.jsonl`, and a history reset at capture start.
- Ordinary-menu DLSS-NR operation with safe fallback guides and history resets;
  loading screens, the console, and unsafe pre-upscale menu routes remain
  blocked.
- DLSS RCAS sharpening remains disabled by default while manual controls stay
  available.
- Ten actual-resolution controls: 100, 95, 90, 85, 80, 75, 67, 60, 50, and
  33 percent. Adaptive NR uses a bounded native tier set described below.

#### UI and compatibility fixes

- Restored the visible OpenNR title, `Neural Rendering` page, localized
  identity, logos, and metadata.
- Preserved the stable internal `DLSSNR` menu ID and the loader-compatible
  `CommunityShaders` filename/path.
- Added a persisted VR font scale clamped to `1.0x–1.75x`, defaulting to
  `1.25x`, for readable in-headset text.
- Fitted the VR-sized desktop mirror into smaller desktop swapchains with
  letterboxing while leaving the VR helper panel at its native panel size.
- Kept the VR helper responsible for panel sizing, controller input, and
  overlay submission.
- Restored and staged the ImGuiVRHelper v1.7.0 runtime/config pair. The
  package default is a 1.25 m HMD-relative panel with `hmdOffsetZ=-0.95`;
  existing user-owned overwrite settings remain authoritative.
- Fixed desktop mouse ownership so wand input is forwarded only while the ray
  is on the VR panel, while desktop hover/click input remains usable off-panel.
- Kept temporal controls under `Temporal Stability` on the Neural Rendering
  page; there is no separate rebranded Upscaling page.

#### Release and regression fixes

- Enabled the Xbyak compile contract required by the integrated CommonLibSSE
  context-hook API.
- Made the native carrier mandatory in staging and size/hash checked it.
- Added the missing ImGuiVRHelper DLL and TOML with package checks.
- Corrected the active helper overwrite that forced a 1.0 m fixed-world panel.
- Expanded source/package validation so grass, Dynamic Near Clip, Skylighting,
  wetness, VRS, Effects11, Address Library, branding, capture, menu, carrier,
  and helper contracts cannot disappear together.
- Changed final archive validation to inspect the post-strip lean stage rather
  than only the complete development AIO directory.
- Protected the ten-stop selector and F6 route from source-line swaps.

### 2.14.6 — guide contracts, Skylighting scheduling, and release hardening

- Added an explicit Feature 18 guide contract for every Neural Rendering pass:
  per-eye color, depth, motion-vector, and output extents; zero-based resource
  origins for isolated eye resources; motion-vector scale metadata; and the
  native low-resolution motion-vector create flag where applicable.
- Corrected Feature 18 cascade dimensions so the first color/model input uses
  its actual dimensions instead of inheriting guide dimensions.
- Added guarded Skylighting grid-quality presets from performance through
  extreme, dynamic field sizing, reduced update frequency, and incremental
  probe-slice updates.
- Aligned Skylighting shaders and runtime through shared grid/slice constants,
  shared four-corner occlusion-frustum routing, and bounds checks.
- Deferred Skylighting resource replacement and GPU clears requested by setting
  changes to a render-safe prepass; added teardown and null-resource guards.
- Added release identity fallback so an old checkout tag cannot reintroduce a
  stale `v2.12.x` build label into the OpenNR UI.
- Retained the unified Capture payload as an explicit opt-in, the pinned native
  carrier, lean packaging, and source/package validators.

### 2.14.7 feature chain and 2.14.8 repair

The retained 2.14.8 report carries the 2.14.7 feature chain and records the
repair that made that chain package-safe.

#### Skylighting regression repair

- Qualified affected `skylightingSettings` references with `SharedData::` in
  `Skylighting.hlsli` and `UpdateProbesCS.hlsl`.
- Fixed the resulting `GetArraySize`/common-include shader compiler failures,
  which had fanned out into Water, ImageSpace, Effect, and Lighting shader
  families.
- Added exact-text checks for the qualified shader form to both the source
  validator and the final archive validator.
- Made source-contract validation a dependency of the plugin target so a
  direct DLL build cannot bypass the release contracts.
- Bumped the repaired package identity to 2.14.8 so it cannot be confused with
  the broken 2.14.7 payload.

#### Native OpenVR gaze provider

- Added the in-process, opt-in `NativeOpenVRGaze` provider compiled into the
  plugin. It borrows the already loaded game's `IVRSystem_026` interface and
  does not initialize/shut down OpenVR or take ownership of compositor,
  Streamline, or Feature 18 resources.
- Resolves left/right native eye-tracked foveation centers into per-eye UV
  regions and shares one crop/reset decision per game frame with foveated DLSS
  and Neural Rendering.
- Added smoothing in milliseconds and output-pixel crop quantization controls.
- Fails closed to the persisted static crop when VR/focus/menu/loading state,
  interface availability, gaze validity, dimensions, stereo size, or sample
  freshness is unacceptable.
- Added diagnostics for provider/API state, sample sequence and age, raw and
  filtered gaze, crop/fallback state, and history resets.
- Kept the provider disabled by default and did not bundle an OpenVR runtime,
  eye-tracking DLL, OpenXR layer, or tracker software.

## 2.15.0 adaptive runtime promotion

Adaptive NR and adaptive Crop move from an isolated experiment into the main
development runtime. They remain opt-in in the shipped settings, preserving
the established user configuration and safe fallback route.

### Adaptive budget controller

- Added a hysteretic adaptive NR controller that derives a two-to-one
  application deadline from the selected headset refresh rate. Supported
  targets are 70, 72, 80, and 90 Hz; the default target is 80 Hz.
- Added separate downshift, upshift, minimum-dwell, and reserved-headroom
  controls. The preserved defaults are four downshift frames, twelve upshift
  frames, thirty dwell frames, and 1.0 ms reserved headroom.
- Added bounded native adaptive NR tiers at 100, 95, 90, 85, 80, 75, and 70
  percent. The 70 percent adaptive floor avoids silently creating unbounded
  one-percent Feature 18 resource states; older lower manual choices remain
  compatibility inputs but are clamped by the adaptive floor.
- Added per-eye tier resources and Feature 18 slots. The automatic tier set is
  pre-warmed while adaptive mode enters the route, reducing synchronous
  resource replacement during a pressure event.
- Added requested/effective tier state, handoff progress, pressure, headroom,
  freshness, GPU time, active-submit time, and crop-held diagnostics.

### Adaptive Crop controller

- Added a coordinated adaptive Crop controller with a configurable minimum
  coverage (default 60 percent), two-frame crop downshift, twenty-four-frame
  crop upshift, sixty-frame minimum dwell, and eight-frame transition.
- Crop is the first pressure action when compatible and available; pressure
  alternates Crop → NR → Crop when both controllers can help.
- Eye-tracked foveation retains ownership of crop placement. The adaptive
  performance crop is disabled when that route owns the UV geometry.
- Capture mode and the experimental pre-upscale route bypass the adaptive
  controller and retain fixed-resolution/stage-order semantics.

### Correction 20260913-B: transition correctness

- Crop transitions render the union of outgoing and incoming regions until the
  handoff completes and animate a current-frame feather mask. The old
  completed SBS image is not composited at the NR hook, avoiding stale-image
  trails.
- NR handoffs use elapsed-time fades (120–800 ms), smoothstep progress, and
  incremental recursive weights. The 70 percent tier has explicit resolve
  parameters instead of falling through to the 100 percent defaults.
- NR history sampling uses allocation dimensions, current-neighborhood
  clamping, motion-aware current-pixel preference, depth/color validity checks,
  and invalid-history rejection. Native motion vectors remain in pixel units.
- Missing, repeated, invalid, stale, or implausible SteamVR GPU/active-submit
  timing samples hold quality. Pacing intervals are not treated as workload.
- NR restoration cannot overlap a Crop handoff. Crop restoration waits for
  stable full-quality NR plus its headroom and dwell requirements.
- The Crop route publishes the actual copied guide dimensions after a
  successful two-eye dispatch. Allocation dimensions are not reported as
  valid-region dimensions, and cropped adaptive NR requires same-frame guides.
- If a native crop resource envelope is rejected, further adaptive Crop tier
  changes are held until restart. NR may continue adapting, and the exact-size
  fallback remains available for safe rendering.
- Reset reasons, exact-cache reuse, and eviction events use normal logging;
  budget status is emitted every 300 engine frames.

### Adaptive safety and compatibility

- Preserved explicit disabled-feature routes and the existing saved settings.
- Preserved separate per-eye histories, stereo boundaries, motion-vector
  units, allocation-versus-valid-region dimensions, reset handling, and
  fail-closed invalid-input behavior.
- Preserved the existing eye-tracking ownership rule and prevents adaptive
  Crop from becoming a second crop-geometry owner.
- Kept adaptive NR/Crop as a runtime-quality and frame-budget control. No
  claim is made that a lower tier is visually equivalent to native 100 percent
  NR or that pre-warming is allocation-free.

## 2.15.0 capture, training, and native-tool fixes

- Consolidated native capture, teacher replay harnesses, texture bridge,
  training, preprocessing, validation, export, and benchmark entry points in
  one OpenNR-VR repository while preserving their working import layout.
- Added a shared path resolver with precedence: explicit CLI path, environment
  override, ignored machine-local configuration, then documented default.
- Changed new capture output defaults to `C:/OpenNR/Captures` and added guards
  that reject output physically resolving to D:, including junctions and drive
  aliases. Existing persisted output paths remain user-owned and are checked
  before recording starts.
- Applied the same external-output protection to maintained training, cache,
  inference, export, benchmark, and validation writers.
- Repaired the native teacher harnesses' old positional `Execute` call. They
  now pass an explicit Feature18GuideContract with color, depth, motion, and
  output dimensions, scales, and the current low-resolution guide policy.
- Added a native contract test for guide dimensions/scales, invalid dimensions,
  and physical output destination rejection.
- Added a CPU train/save/resume/evaluate/export smoke workflow. It checks exact
  resumed optimizer state and ONNX graph validity on a synthetic fixture.
- Kept dataset split identity, checkpoint compatibility, guide alignment,
  strict reset/warm rules, and native Feature 18 provenance separate from
  model-promotion decisions.

## 2.15.0 build, dependency, and package fixes

- Added the canonical `Build-OpenNR.ps1` wrapper. It discovers Visual Studio
  2022 C++ tools, initializes the compiler environment, uses the external E:
  build root, passes the verified external dependencies explicitly, and keeps
  automatic game deployment disabled.
- Moved large build and package output to `E:/OpenNR_Builds/2.15.0` and
  consolidated dependencies under `C:/OpenNR/Dependencies/runtime-2.15.0`.
- Recorded dependency file counts and content-tree hashes. The incompatible
  CommonLib prebuilt toolset was rejected and the matching source was compiled
  instead; no toolset mismatch was bypassed.
- Added explicit CMake output roots and 2.15.0 package descriptions for the
  supported Windows presets.
- Kept capture-enabled AIO packaging, lean exclusions, required carrier and
  helper inputs, source-contract checks, package-manifest checks, and exact
  archive-stage validation together in the package target.
- Preserved the NVIDIA-signed private carrier and helper as external local
  inputs. Private runtimes, weights, captures, checkpoints, caches, generated
  build files, and secrets are not committed or redistributed.
- Preserved the `CommunityShaders` compatibility filename and asset paths while
  using OpenNR for human-facing branding.

## 2.15.0 repository consolidation and recovery

- Established `D:/.CODEX_Projects/OpenNR-VR` as the authoritative source
  repository and imported the adaptive runtime history without squashing its
  internal ancestry.
- Preserved the original research main, adaptive source snapshot, dirty-state
  patches, bundles, legacy refs, submodule pointer backups, dependency hashes,
  and per-file migration manifests under
  `C:/OpenNR/ConsolidationBackups/20260913`.
- Reconciled nine legacy runtime trees after proving their unique source state
  was retained. Their full Git statuses, including submodules, are clean and
  their historical refs remain available under `refs/archive/legacy/*`.
- Relocated verified training inputs, generated outputs, legacy build trees,
  report applications, and the Git object database away from D:. Compatibility
  junctions preserve older paths without keeping the payload physically on D:.
- Removed temporary V:, W:, and X: SUBST aliases used during validation. No
  source directory was deleted as part of alias cleanup.
- Added project map, setup instructions, experiment index, external-storage
  registry, forensic audit, compact machine manifest, and final validation
  record.

## Compatibility and defaults

- `CommunityShaders.dll`, `SKSE/Plugins/CommunityShaders/`, the `DLSSNR`
  internal ID, existing settings format, and existing saved settings remain
  compatible.
- Neural Rendering's existing user state is preserved.
- Adaptive NR: disabled by default; when enabled, default target is 80 Hz,
  minimum NR tier 70 percent, four-frame downshift, twelve-frame upshift,
  thirty-frame dwell, and 1.0 ms reserved headroom.
- Adaptive Crop: disabled by default; when enabled, default minimum coverage is
  60 percent and it remains subordinate to eye-tracked crop ownership.
- Temporal residual reuse: disabled by default (`cadence=0`).
- Native OpenVR gaze provider: disabled by default.
- OpenNR Capture: disabled by default, with new capture roots on C:.
- DLSS RCAS sharpening: disabled by default with manual controls retained.
- Automatic deployment: disabled. This package does not modify a game install or
  push to a remote repository.

## Explicitly not shipped or not promoted

The following remain separate research or future-contract paths and were not
silently promoted by the 2.15.0 consolidation:

- learned residual-student weights or a replacement neural model;
- optical-flow substitution;
- Catmull-Rom or low-resolution residual fill;
- public async/interposer runtime architecture;
- depth-matched residual-fill runtime;
- non-linear peripheral compression or a separate VR render-scale branch;
- eye-gaze DLSSNR submit-stage foveation;
- submit-stage foveation, resolution hysteresis, wind experiments, and runtime
  swaps;
- unavailable H: capture storage or any missing source/data dependency.

## Verification status

Passed source, build, and package gates include:

- Release `CommunityShaders.dll` build, version `2.15.0.0`.
- C++ suite: 171 cases and 2,357 assertions, including 12 adaptive cases and
  54 adaptive assertions.
- FXC `cs_5_0` compilation of the adaptive NR, adaptive Crop, and subrect-blend
  shaders.
- Eight Python regression suites and five external-storage/path tests.
- Native guide/output contract tests, including physical D: rejection.
- Both native teacher harnesses and the CUDA texture bridge compile.
- Synthetic CPU train/save/resume/evaluate/export workflow; resumed optimizer
  update matches exactly and ONNX checker passes.
- Source-contract, AIO manifest, lean-stage, 7-Zip archive, and extracted-file
  hash verification.
- Final package: 490 files, 228,054,772 compressed bytes, 440,813,081
  uncompressed bytes.
- Package SHA-256:
  `D5374E8DD84609E201065593984E30496083AB936D00058AE9BE73BBC45F9A51`.

The clean-source export also configured successfully with capture enabled and
disabled, and generated projects contained no legacy Skyrim workspace source
references. A second complete clean-export DLL and a capture-disabled DLL were
not built; the disabled result is configuration/source-selection evidence.

## Live acceptance boundary

Build and package validation do not establish live SkyrimVR acceptance. The
following still require a controlled no-capture HMD run: two-eye output,
rapid-motion/disocclusion behavior, Crop and NR transition appearance, menu/map
and VR input behavior, native resource stability, restoration under sustained
headroom, eye-tracking behavior, and delivered frame timing. The adaptive
resource-rejection hold is retained precisely so an unsafe native envelope does
not cause continued Crop oscillation. No unperformed headset check is described
as passed.

## Recovery

Use `C:/OpenNR/ConsolidationBackups/20260913` for source snapshots, patches,
history bundles, dependency manifests, migration records, and validation logs.
Keep the external Git object store with the repository backup. To roll back the
promotion, preserve any later work and revert the final mainline merge rather
than resetting away subsequent commits; storage rollback must use the per-file
copy/hash manifests before replacing a junction.
