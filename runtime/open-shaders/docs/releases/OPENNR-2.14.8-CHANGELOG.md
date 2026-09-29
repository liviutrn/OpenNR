# OpenNR 2.14.8 — Skylighting regression repair and native OpenVR eye-tracking experiment

Date: 2026-09-12

OpenNR 2.14.8 is the repaired current-line package. It preserves the 2.14.7
feature chain and isolated native OpenVR gaze experiment while fixing a real
runtime shader regression found in the 2.14.7 release package.

## Regression repaired in 2.14.8

- Qualified every affected Skylighting settings reference with
  `SharedData::` in `Skylighting.hlsli` and `UpdateProbesCS.hlsl`.
- This repairs the reported `skylightingSettings` / `GetArraySize` compiler
  errors. The bad common include caused a wide fan-out of failures in
  `Water`, `ImageSpace`, `Effect`, and `Lighting` shader families.
- Added the same exact-text checks to the source-contract validator and to the
  final archive stage. A package cannot pass merely because the C++ DLL built
  or because the expected files exist; the staged shader text must also be the
  qualified form.
- Made the source-contract validator a dependency of the plugin target, so a
  direct DLL build cannot bypass the OpenNR release contracts.
- Bumped the package to `OpenNR 2.14.8` so the repaired payload is never
  silently confused with or reused as `OpenNR 2.14.7`.

## Retained current-line features

- Native Feature 18 guide contract: each Neural Rendering pass carries explicit
  per-eye color, depth, motion-vector, and output extents, zero-based resource
  origins for isolated eye resources, motion-vector scale metadata, and the
  native low-resolution motion-vector create flag when applicable.
- Feature 18 cascade dimensions: the first color/model input is described with
  its actual dimensions instead of inheriting guide dimensions.
- VR stereo/depth history: Eye 1 geometry, reprojection blending, final-depth
  classification, and invalid-history rejection.
- Grass optimizations and reliability: per-eye culling, Hi-Z/SPD occlusion,
  compacted indirect draws, dynamic-resolution handling, VR hook and
  eye-transform fixes, bucket sizing, shader-cache protection, and HMD-size
  handling.
- Grass diagnostics: GPU-pass profiling and vanilla-path A/B instrumentation.
- Dynamic Near Clip: opt-in VR near-plane adaptation with corrected
  translations and diagnostics.
- Skylighting: early occluder rejection, guarded grid-quality presets, dynamic
  field sizing, reduced update frequency, incremental probe updates, shared
  grid/slice shader settings, and render-safe resource replacement.
- Tree Wetness: the simple tree-material wetness response.
- VR dependency boundary: Address Library 0.264.0 compatibility remains
  required by the modlist; the library itself is not redistributed.
- Menu/UI overhaul: larger VR-readable layout, separators, sidebar controls,
  background blur, and organized feature pages.
- Desktop UI input: fixed inverse letterbox mapping so mouse coordinates land on
  the actual menu after the desktop companion view is fitted to the window;
  pointer input in the desktop bars is rejected instead of selecting an offset
  control.
- VR UI presentation: the ImGui VR helper panel remains the sole HMD target,
  while the desktop companion copy is bound to the real desktop swapchain
  backbuffer. This removes the duplicate/curved desktop menu compositing seen
  when the helper panel and desktop mirror were both presented as VR surfaces.
- VR menu placement: the packaged helper default is `FixedWorld`, so a newly
  installed menu is world-floating rather than HMD-relative. Existing user
  positioning settings remain user-owned and are migrated only when changed
  explicitly.
- Local tone: the default `Local Tone` strength is now `1.00` in both the
  runtime default and the packaged helper profile.
- Fixed desktop mouse ownership: the VR helper now forwards wand input only
  while the ray is on the VR panel and preserves desktop hover/click input
  off-panel.
- Fixed Skylighting probe-address wrapping at positive array origins, which
  could alias wrapped probes to cell zero.
- Fixed Skylighting shadow-history warm-up so reset/new probes no longer
  interpret missing history as dark shadow samples and progressively darken a
  stationary scene.
- Neural Rendering menu: explicitly named `Neural Rendering` and kept as a
  separate peer page from `Upscaling`. The visible product title is exactly
  `OpenNR 2.14.8`; build-describe text is not appended.
- Menu safety: ordinary menus retain the NR route with safe guide fallback and
  temporal-history resets; loading screens and the console remain fail-closed;
  pre-upscale NR stays disabled in menus.
- Temporal residual reuse: disabled/opt-in experimental reuse that periodically
  runs native Feature 18, stores the native correction residual, and
  reconstructs intervening frames using accumulated exact motion-vector
  reprojection.
- DLSS sharpening: RCAS remains disabled by default with manual opt-in
  controls.
- NR cost control: ten-stop actual-resolution slider.
- NR hotkey: F6 toggles Neural Rendering on/off and resets temporal history.
- OpenNR Capture: unified, off-by-default Feature 18 capture payload, native
  guides, per-eye output, metadata, and capture-start history reset.

## Native OpenVR gaze experiment

- `NativeOpenVRGaze` is an in-process, opt-in provider compiled into
  `CommunityShaders.dll`. It borrows the already loaded game's OpenVR ABI and
  does not own OpenVR initialization, shutdown, compositor submission, or the
  Streamline/Feature 18 resource path.
- Uses `IVRSystem_026` and its native eye-tracked foveation-center query to
  resolve left/right crop centers into per-eye UV regions.
- Exposes provider enablement, smoothing in milliseconds, and crop movement
  quantization in output pixels. The sample is resolved once per game frame so
  the foveated DLSS and Neural Rendering paths share the same crop/reset
  decision.
- Fails closed to the persisted static crop when VR, focus, menu/loading/
  console state, the OpenVR interface, gaze validity, dimensions, stereo size,
  or sample freshness is unacceptable. Gaze jumps and crop-contract changes
  invalidate temporal state.
- Provides diagnostics for API/provider state, sample sequence and age, raw and
  filtered gaze, crop/fallback state, and history-reset state.
- Does not bundle an eye-tracking DLL, OpenVR runtime, OpenXR layer, or other
  third-party runtime. A compatible headset, tracker, and OpenVR runtime are
  required for live testing; the provider is disabled by default.

## Deliberately not enabled or shipped

- The upstream async/interposer architecture is not ported; only its ownership
  and fail-closed principles are represented in local boundaries.
- Non-linear peripheral compression, a separate VR performance render-scale
  branch, optical-flow fallback, Catmull-Rom/low-resolution residual fill, and
  learned residual-student architectures remain isolated research work.
- Eye-gaze DLSSNR submit-stage foveation, runtime swaps, and other
  research-only paths remain outside the stable feature contract.

## Validation boundary

- Source-contract validation covers the exact runtime shader qualification,
  Feature 18 guide wiring, branding, menu safety, temporal reuse, capture, and
  native eye-tracking contracts.
- AIO/package validation checks the exact staged archive payload, including the
  qualified Skylighting shader text, capture manifest, native eye-tracking
  manifest, lean-package exclusions, and required binary payloads.
- Release C++ compilation, archive integrity, and local package checks are
  necessary release gates. They do not substitute for live SkyrimVR/SteamVR,
  HMD, eye-tracker, temporal-quality, or VR-budget acceptance.
