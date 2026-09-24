# OpenNR upstream implementation sync — 2026-09-22

## Decision

The embedded `runtime/open-shaders` tree is synchronized from the shared
Open Shaders ancestry `7d5622f8` through the current clean PR #606 line. The
result carries `alandtse/open-shaders/dev` at `fd6350ca` plus internal PR #606
at `edf1dc9e`, then preserves the OpenNR-owned VR/runtime adaptations from the
2.15.1 line. The sync is local and has not been pushed or deployed.

PR #606 belongs to this project (`olekspa/open-shaders` →
`alandtse/open-shaders:dev`). It is recorded as an internal source line and
must not be counted as independent upstream evidence. The current clean PR
checks were inspected separately; they establish CI status for our branch,
not SkyrimVR/HMD acceptance.

## Selected source and dependency changes

| Area | Decision | Reason |
| --- | --- | --- |
| Current `dev` renderer/shader fixes | Ported through the three-way source sync | They are the maintained Open Shaders baseline and affect the runtime shipped by OpenNR. |
| PR #606 adaptive VR NR controls and scene-manager UI integration | Ported, with OpenNR 2.15.1 conflict resolutions retained | This is our native Feature 18 route and the project’s chosen engineering line; the feature-page toolbar, draft-aware scene toggle, and draw guard are now wired into the shipped renderer. |
| CommonLibVR 8.4.0 | Updated to `adb3e2c4` | Current dev build dependency; compile validation is required before release. |
| Streamline 2.14.1 | Updated to `2122257e` | Current dev API/runtime contract and VRAM/resource diagnostics. |
| Upstream tests and generated translations | Ported/merged | Keeps current source and translation drift visible in local validation. |
| Current upstream wind, scene, terrain, rain, lighting, and menu additions | Carried as part of the maintained dev source snapshot | They are upstream runtime changes, but remain separate from the OpenNR acceptance gates and are not individually claimed as tested here. The scene policy was reconciled to the generated catalog; obsolete `Wind/Tree Meshes` naming was removed rather than broadening the blacklist. |

## Deliberately not promoted

- PR #723 (`kevdevrev/skyrim-community-shaders`, `messingaround-dlss`) is a
  competing neural-rendering implementation. Its dirty isolated checkout and
  layout probes remain untouched. Its temporal residual/history approach is
  research-only because current release-parity shader checks fail and there is
  no native OpenNR/SkyrimVR/HMD proof.
- PR #744’s UI tab reorganization, plus conflicting or failing unrelated open
  PRs, was not cherry-picked over the maintained dev snapshot. OpenNR keeps its
  dedicated NR/foveated pages and compatibility naming.
- OptiScaler DLSSNR/PreSR multipass code was not copied. Its useful cadence,
  current-raster, residual-history, and exposure observations are documented
  as research contracts; its game-specific integration and GPL boundary do not
  make it a drop-in SkyrimVR implementation.
- ReShade and `stray-dlssnr` were not used as a native route. Their fail-open,
  state-save/restore, resolved-color, and history-restore patterns informed
  review only; generic injection cannot establish Skyrim’s Feature 18 input
  semantics, per-eye ownership, or compositor placement.
- Optical flow, closed carriers, recovered model weights, and external model
  parity were not installed, executed, or substituted for native depth/motion
  vectors and capture provenance.

## Verification boundary

The source sync is structurally reviewable from the merge base and exact refs
above. The release run must record CMake configure, CommunityShaders build,
C++ tests, shader/config validation, source-contract validation, package
manifest/hash checks, and 7-Zip integrity separately. None of those checks
establishes live SkyrimVR rendering, two-eye correctness, gaze-to-display
response, temporal quality, SteamVR compositor behavior, or sustained VR
frame-time.
