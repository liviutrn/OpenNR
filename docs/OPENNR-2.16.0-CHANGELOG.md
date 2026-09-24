# OpenNR 2.16.0

Release candidate: 2026-09-22. Current Open Shaders development sync plus the
OpenNR 2.15.1 VR neural-rendering line.

## Upstream and internal source refresh

- Synchronizes the embedded runtime with `alandtse/open-shaders/dev` at
  `fd6350ca7e82a52a8f578c8aaa62def53f051f72`.
- Carries OpenNR's internal PR #606 line through
  `olekspa/open-shaders` commit `edf1dc9e29f875b68555f82de35b322e66966e19`.
  PR #606 is internal engineering provenance, not independent validation.
- Updates the embedded CommonLibVR dependency to `adb3e2c4` (8.4.0) and
  Streamline-DX12 to `2122257e` (2.14.1).
- Includes the current upstream renderer, shader, translation, build, and unit
  test refreshes while retaining OpenNR-owned capture, stereo isolation,
  adaptive resource envelopes, gaze reset policy, temporal-history guards, and
  package/source-contract validation.
- Wires PR #606's scene-manager feature-page action, draft-aware scene toggle,
  toolbar controls, and guarded feature drawing into the OpenNR menu while
  preserving the dedicated Neural Rendering and Upscaling pages.
- Reconciles the scene-settings blacklist with the generated Wind catalog by
  removing the obsolete `Wind/Tree Meshes` path instead of blacklisting the
  entire Wind feature.

## Neural rendering and VR safety boundary

- Keeps native Feature 18 color, depth, motion-vector, per-eye, subrect, and
  output extents explicit; no optical-flow or generic post-process substitute
  is introduced.
- Keeps adaptive NR and crop opt-in, bounded by the existing memory ceiling,
  exact-extent fallback, transition/reset handling, and no-implicit-deployment
  policy.
- Keeps moving gaze/crop changes conservative: history is reset when the crop
  origin or extent changes; this release does not claim continuous moving-crop
  temporal reconstruction or HMD acceptance.

## External implementation review

The OptiScaler, ReShade, Streamline, `stray-dlssnr`, and
OptiScaler-DLSSNR-PreSR-Multipass reviews informed contracts and diagnostics,
not code or binary imports. Reused design conclusions are fail-open behavior,
explicit pre/post-TAA ownership, exact motion/depth/subrect metadata, bounded
resource lifetimes, reset/history diagnostics, and frame-cadence guards. Their
game-specific hooks, proprietary carriers/models, optical-flow substitutes,
and unlicensed or non-VR add-ons are not promoted into OpenNR.

The competing upstream PR #723 temporal residual implementation is retained as
research-only. Its current release-parity shader checks are not a promotion
signal, and it does not replace the native OpenNR teacher/capture route.

## Compatibility and acceptance

The runtime identity remains `CommunityShaders.dll`. Existing settings remain
unchanged and experimental controls remain disabled by default. Source, build,
unit-test, shader, and package evidence are separate from live SkyrimVR,
SteamVR, stereo/full-eye, eye-tracking response, temporal appearance, frame
time, and sustained HMD acceptance. No installation or game run is part of
this release-candidate packaging turn.
