# OpenNR DLSSNR VR 2.13.0 upstream audit

Date: 2026-09-10

## 2.13.0 disposition

The stable OpenNR lane is the former 2.12.1 base plus the branding/attribution
transition and the already-audited PR #630 VR grass path. Upstream PR #615 is
carried in the local OpenNR Capture fork and packaged as opt-in Beta NearClip;
PR #634 is carried in Alpha Wind; PR #625 is carried in Alpha SubmitStage.
These experimental lanes are buildable and packageable, but none is treated as
stable live-VR acceptance evidence.

## Promoted changes

- Open Shaders dev was audited through `7d5622f` on the upstream `dev` branch.
  The current base already contains the recent stereo classification, Eye 1
  viewport, final-depth, and stereo-reprojection fixes.
- Open Shaders PR [#630](https://github.com/alandtse/open-shaders/pull/630)
  was tested in an isolated merge. Its per-eye VR grass path is now included
  in the internal 2.13.0 public and OpenNR builds: CPU per-eye frustums,
  eye-specific Hi-Z/camera selection, separate indirect-draw accounting,
  HMD render dimensions, and safer per-eye bucket capacity handling.
- The local foveated writeback path now returns a failure from stretch/blend
  operations and propagates it to the standard DLSS fallback. This is the
  narrowly scoped failure-handling portion suggested by the review of draft
  [#625](https://github.com/alandtse/open-shaders/pull/625); the experimental
  eye-submit/foveated-render-stage design itself was not merged.

## Audited but intentionally not promoted

- [Cheeky Foveated DLSS v0.3.2](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/releases/tag/v0.3.2)
  supplies useful VR ideas: OpenVR/UEVR late-init recovery, corrected
  Virtual Desktop/OpenXR calibration, HDR/vertical-flip handling, stable
  output extents, native DLSS sizing protection, and independent DLSS-NR
  gaze from DLSS-SR foveation. Its code and binaries were not copied into the
  native Skyrim Feature 18 route. Stable extents and independent NR gaze need
  an isolated live eye-tracking test before promotion because a geometry change
  currently invalidates the matching DLSSNR history by design.
- [OptiScaler](https://github.com/optiscaler/OptiScaler) master and its DLSSNR
  issue tracker were checked for resolution hysteresis, resource ownership,
  and runtime replacement ideas. The reported alternating-feature-size
  rebuild problem is useful guidance for a future hysteresis guard, but no
  OptiScaler binary or proxy runtime is installed in the known-good route.
- [ReShade](https://github.com/crosire/reshade) current commits and open PRs
  were checked for D3D12 descriptor, HDR, effect-unload, and synchronization
  fixes. None is a direct DLSSNR/eye-gaze improvement for this DX11 Feature 18
  path, so no ReShade binary or wrapper was packaged.
- [Streamline 2.14.1](https://github.com/NVIDIA-RTX/Streamline/releases)
  was noted for current fixes and Vulkan/MFG work, but the package retains the
  separately audited native Streamline 2.13 runtime plus the stock DLSSNR
  310.8 component. A runtime swap requires a separate Skyrim VR acceptance
  run and is not inferred from an upstream release.
- Open Shaders PR #615 (dynamic near clip) is now integrated into the local
  OpenNR Capture source and remains default-off because its vanilla-fog behavior
  needs a dedicated live VR test.
- PR #625 (submit-stage foveation) is available only in Alpha SubmitStage. Its
  map/resource/ghosting concerns remain open; no stable package includes it.
- PR #634 (dynamic wind/grass response) is available only in Alpha Wind and is
  not promoted without scene- and performance-specific evidence.
- Cheeky Foveated DLSS 0.3.2's independent DLSS-NR gaze/SR foveation split is
  documented as a future OpenNR eye-tracking adapter. The current native route
  has no trusted gaze source, so copying the feature would be unsafe.
- OptiScaler's resolution hysteresis idea is documented as a future rebuild
  guard. The native Feature 18 route has no equivalent controller yet, so no
  proxy/runtime swap or unmeasured hysteresis change is included.

## Package and size audit

The pair packager is rerun for `DlssNrOnly` and `LeanVr` using the rebuilt
2.13.0 OpenNR public and OpenNR Capture AIO trees. It verifies x64 PE format,
file versions, stock NVIDIA DLSSNR hash/signature, ImGuiVRHelper v1.7.0
identity, OpenNR presence/absence, FOMOD metadata, and the excluded-payload
rules. The three public-only experimental lanes were packaged with the same
checks; they are test artifacts, not stable release candidates.

| Profile | Variant | Payload files | DLLs | Archive bytes | CommunityShaders SHA-256 | Archive SHA-256 |
|---|---|---:|---:|---:|---|---|
| DlssNrOnly | Stable public | 455 | 19 | 144,266,763 | `3DF435E36501826DD74B4A78B2C098955C139DF43B8FEF09D3928647EAB2F745` | `3FD1BAA5A998D453EAE1C578BFB719A2AE65BE7E8CAE4BC39AA306FD7DCFBEF5` |
| DlssNrOnly | Stable OpenNR Capture | 457 | 19 | 144,308,218 | `D284EE3618AE63527E0B7FA7A374DFE2DA98474099AE9E2F99478E02320F20C3` | `6823FD3B0E1C55B5825BE05CC0BAAAB0C53E2BA715C75EAC1BA5465DA608E60A` |
| LeanVr | Stable public | 458 | 21 | 147,656,960 | `3DF435E36501826DD74B4A78B2C098955C139DF43B8FEF09D3928647EAB2F745` | `4EDF3570B9A7ABBAFFC743FF408507276CD07A9AAA8BA415D8FF5A87F2A73124` |
| LeanVr | Stable OpenNR Capture | 460 | 21 | 147,696,605 | `D284EE3618AE63527E0B7FA7A374DFE2DA98474099AE9E2F99478E02320F20C3` | `3A650FB19A13305262F0AEBD088D94EDA3B8577D68FB459659C0E82F594A791F` |
| DlssNrOnly | Beta NearClip | 455 | 19 | 144,244,308 | `354B38F2ACB1400F3FE1532A07071738A60DD284795630ED7EB9147020B360EE` | `566C885710DC43E5919D46B6785CA35736433F271376F00C8EF1A0F9F93E1DB6` |
| DlssNrOnly | Alpha Wind | 472 | 19 | 144,390,017 | `0F7857CB080F39DB809DFA2563D1085946FEC1F32FF17739AB49BD18C24F44B4` | `66283FC8EB805479F5B5FD3BF32F0B170784AB1966C5A2CD593307BDF3828CCC` |
| DlssNrOnly | Alpha SubmitStage | 457 | 19 | 144,262,416 | `E75D140619D5144B4EFABAC3C2756D9D3F0F3D1E7A4276770347EE0F1C14ECD4` | `DD986172A9343707F7A9510931885F36B409A5A6C428661DA4D6B82335FEB5F4` |

The DLSSNR-only archives contain no OpenXR, FidelityFX, StreamlineDX12,
RenderDoc, PDB, texture, mesh, or particle-light payload. LeanVr adds only
the FSR upscaler/loader pair and its license; it still omits frame generation.
Compared with the 0.5.7 public archive, the 2.13.0 stable public archive is
556,695 bytes larger; the OpenNR Capture archive is 1,097,408 bytes smaller.
The net public increase is accounted for by the two new OpenNR logos, the
upstream grass/Hi-Z shader additions, refreshed translations, and small UI
assets, while the old OpenXR eye-tracking layer and stale feature registrations
are gone. No unexpected optional runtime caused the growth: the stable
DlssNrOnly package contains no OpenXR, FidelityFX, StreamlineDX12, frame
generation, RenderDoc, PDB, texture, mesh, or particle-light payload. LeanVr
adds only the two FSR loader/upscaler DLLs and the corresponding license.

## Acceptance boundary

Both source trees compiled successfully with the existing Visual Studio 2022
configured build trees, and all four archives passed package-time validation.
This proves source/package health only. Skyrim VR launch, native Feature 18
resource binding, headset two-eye output, eye-gaze behavior, temporal quality,
and frame-time/VR-budget improvements still require the separate live test
gates.
