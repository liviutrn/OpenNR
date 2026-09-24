# DLSS NR community implementation review — 2026-09-24

This is a source and PR review, not a performance or HMD result. Searches
covered GitHub repositories, PRs, issues, releases, GitLab search results,
and NVIDIA's published DLSS 5 description. No relevant GitLab source lead
with stronger VR evidence appeared in the indexed results. Repository owners
and branches below matter: OpenNR's own `olekspa` PR #606 is internal work.

## Applied to the 2.17.0 candidate

- Open Shaders `alandtse/open-shaders` dev commit
  [`7f4672b9` / PR #756](https://github.com/alandtse/open-shaders/pull/756)
  corrects Streamline camera reprojection using the captured per-eye view and
  projection matrices plus camera-origin delta. The same focused helper and
  test are integrated here. This is a temporal-quality correctness fix, not
  a measured speedup or proof of Feature 18 output quality in SkyrimVR.
- Fresh VR settings reduce Screen Space GI AO samples and update Skylighting
  probes less frequently, while enabling hardware-gated VRS. These are local
  A/B candidates; the neural model does not replace missing lighting.

## Reviewed; no direct port

| Lead | Relevant finding | Decision |
| --- | --- | --- |
| [OptiScaler-DLSSNR PR #42](https://github.com/Dagherbou/OptiScaler_DLSSNR/pull/42) | Motion-vector resolution and subrect metadata can cause flickering if assumed zero-origin or always render-sized. D3D12 tested by author; Vulkan unchecked. | Retain as a metadata audit. OpenNR already uses explicit per-eye Feature 18 guide extents and zero-origin SBS resources; verify the actual live tags before changing them. |
| [OptiScaler-DLSSNR issue #29](https://github.com/Dagherbou/OptiScaler_DLSSNR/issues/29) | Alternating feature sizes triggered repeated model creation and VRAM growth in MSFS 2024. | Audit OpenNR's feature-slot lifetime and tier transitions. Its per-eye/tier/pass slots and resource envelope are a different ownership model; do not copy dispatch-count hysteresis without a local reproduction. |
| [OptiScaler-DLSSNR PR #36](https://github.com/Dagherbou/OptiScaler_DLSSNR/pull/36) and [pre-SR design](https://github.com/GrimsVerk/OptiScaler_NR_then_SR/blob/nr-before-upscale/OptiScaler/dlssnr/design/nr-before-upscale.md) | Pre-upscale NR can reduce model input area, but jitter, motion scaling, dynamic resolution and colour transfer remain unresolved or scene-specific. | OpenNR already owns a native pre-SR Feature 18 route. Use this as a verification checklist, not an injector port. |
| [VR OptiScaler fork](https://github.com/tig3rmast3r/OptiScaler_DLSSNR_VR) | Processes eyes separately to avoid shared temporal state. | Already an OpenNR invariant; no new code. |
| [Open Shaders PR #723](https://github.com/alandtse/open-shaders/pull/723) | Another native pre-SR Feature 18 implementation with per-eye history and diagnostics. | No merge: local release-parity and HMD gates remain open, and it overlaps OpenNR-owned Feature 18. |
| [OptiScaler-DLSSNR PR #55](https://github.com/Dagherbou/OptiScaler_DLSSNR/pull/55) | Draft D3D12 source-guided colour and a game-specific Streamline presentation bridge; author reports no FPS A/B. | No port. Its Endless Legend 2 route does not own SkyrimVR's compositor and adds a colour pass. |
| [OpenDLSS-NR](https://github.com/maanHimself/OpenDLSS-NR) | Vulkan model reimplementation and experimental PTX route. | Research-only. Offline/network parity and model timing cannot establish teacher equivalence or native SkyrimVR Feature 18 acceptance. |
| [RenoDX](https://github.com/clshortfuse/renodx) and [DLSS5 Bridge](https://github.com/NIGos/dlss5-bridge) | Generic add-on and bridge routes include post-present/optical-flow substitutes and ongoing idle/flicker issues. | No replacement of engine depth/motion or the known-good per-eye D3D11/D3D12 bridge. |

## Remaining gate

After installation, compare the rollback profile against 2.17.0 in the same
interior and exterior paths. Record per-pass GPU cost, total frame time,
reprojection, memory, both-eye output, head motion, and reset transitions.
Source, tests, archive integrity, and mod-manager registration are separate
from a live Feature 18 evaluation and HMD acceptance.
