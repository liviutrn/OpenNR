# OpenNR 2.14.0 upstream and package audit

Date: 2026-09-10

## Release disposition

OpenNR 2.14.0 is the single stable package built from the current audited Open
Shaders development ancestry. The package includes OpenNR Capture as a normal
compiled feature, but the capture master setting is explicitly default-off and
the menu explains its purpose, cost, and data contract before use.

The source branch is `codex/opennr-2.14.0`; the stable package keeps the
upstream-compatible `CommunityShaders.dll` filename and SKSE layout while the
human-facing fork and package identity are OpenNR.

## Promoted upstream work

- The local source already contains the current audited Open Shaders `dev`
  ancestry at the time of this refresh, including recent culling-cache,
  detour-failure, stereo, UI, and shader fixes. No newer fetched dev commit was
  missing from the selected source baseline.
- [Open Shaders PR #630](https://github.com/alandtse/open-shaders/pull/630) is
  promoted: per-eye grass frustums and Hi-Z selection, real HMD dimensions,
  eye-specific indirect accounting, and safer per-eye bucket capacity.
- [Open Shaders PR #615](https://github.com/alandtse/open-shaders/pull/615) is
  present as an opt-in dynamic near-clip path. It is not made a fresh-install
  default because the vanilla-fog interaction still needs headset testing.
- Foveated stretch/blend failures propagate to the normal DLSS fallback. A
  failed experimental writeback cannot silently present stale output.

## Investigated, but not promoted

- [Open Shaders PR #625](https://github.com/alandtse/open-shaders/pull/625)
  submit-stage foveation remains isolated in the alpha lane. Its review notes
  include mapping, foliage/cloud ghosting, and resource-lifetime concerns.
- [Open Shaders PR #634](https://github.com/alandtse/open-shaders/pull/634)
  wind/grass/tree/collision work remains in the alpha lane. It is too broad
  and optional for a stable package without scene-specific VR evidence.
- [Cheeky Foveated DLSS v0.3.2](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/releases/tag/v0.3.2)
  provides useful late-initialization, OpenXR calibration, HDR/flip, native
  sizing, and independent DLSS-NR-gaze ideas. The native Skyrim route has no
  trusted eye-gaze source or equivalent UEVR projection-layer contract, so no
  binary or unverified gaze path was copied.
- [OptiScaler issue #29](https://github.com/Dagherbou/OptiScaler_DLSSNR/issues/29)
  suggests resolution hysteresis to avoid alternating-size rebuilds and VRAM
  churn. It remains a design note until a native Feature 18 controller and
  reset-qualified measurements exist; no proxy runtime was installed.
- Current [ReShade](https://github.com/crosire/reshade/commits) and
  [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders/commits/main)
  changes were checked. None supplied a direct, verified improvement for this
  native DX11 Feature 18/DLSSNR route that justified adding a wrapper or
  optional runtime to the lean package.
- Streamline 2.14.x was not swapped into the stable package. The separately
  audited native Streamline 2.13 route remains the compatibility baseline until
  live Skyrim VR acceptance proves a newer runtime safe.

## OpenNR Capture integration

OpenNR Capture is now part of the main package and is no longer a second
archive. Its default-off contract is source- and package-audited:

- `bool enableCapture = false` is the master gate.
- Resetting capture settings restores the default-off state.
- Disabled capture does not poll capture hotkeys, initialize capture resources,
  issue GPU readbacks, or write `frames.jsonl`.
- The menu explains pre-NR, post-NR teacher, raw teacher, exact depth, and exact
  motion-vector stages. It explicitly disallows substituting optical flow for
  native motion vectors.
- Capture targets aligned Feature 18 training/validation data, not desktop,
  headset-compositor, or presented swap-chain screenshots.

## Package-size and provenance contract

The final archive is named `OpenNR 2.14.0.7z` and contains one MO2 payload.
The packager audits PE/x64 format, file version, signed runtime hashes,
ImGuiVRHelper v1.7.0, TerrainHelper identity, capture registration, default-off
source markers, excluded optional trees, and the absence of `SettingsUser.json`.

Excluded optional payload includes RenderDoc, OpenXR, textures, meshes,
particle-light assets, StreamlineDX12, FidelityFX, and `CommunityShaders.pdb`.
The package audit records included/excluded file counts and byte totals so any
future unexpected growth is attributable rather than silently accepted.

## Acceptance boundary

Build, archive, hash, and source/config validation are package-health evidence.
They are not live acceptance evidence. Skyrim VR launch, native Feature 18
binding, headset two-eye output, eye-gaze tracking, temporal stability,
foveated quality, and VR frame-budget changes require a separate controlled
test on the target profile.
