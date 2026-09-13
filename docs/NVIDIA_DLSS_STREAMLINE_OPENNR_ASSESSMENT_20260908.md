# OpenNR-VR: NVIDIA DLSS 310.9.1 and Streamline 2.14.1 assessment

Date: 2026-09-08  
Scope: public NVIDIA DLSS and NVIDIA-RTX Streamline updates, assessed against the current OpenNR-VR / Open Shaders SkyrimVR architecture and research status.  
Decision status: research-only; no runtime, profile, package, model, capture, or worktree changes were made as part of this assessment.

## Technical summary

The two upstream repositories were updated on September 8, 2026:

- NVIDIA DLSS 310.9.1, commit 3749594, adds DLSS Ray Reconstruction Transformer Preset F and describes it as the default RR2 model, together with stability fixes. The SDK also refactors its public helper headers and adds a header-only NGX loader plus standalone CUDA helpers.
- NVIDIA Streamline 2.14.1, commit 2122257, adds V-Sync and frame-limiter support for Dynamic DLSS Multi Frame Generation, Vulkan Reflex through VK_NV_low_latency2, and stability fixes. The same release commit contains the larger 2.14.0 feature batch in its changelog, including a new DLSS 3D-Guided Neural Rendering plugin named sl.dlss_nr, new Streamline uplift resource tags, and a new Streamline feature ID.

The important project conclusion is selective rather than “update everything”:

1. Streamline 2.14.1 is the more consequential lead for OpenNR because it exposes an official host-side surface for 3D-Guided Neural Rendering. It is still only a future isolated integration candidate: the public source tree contains no sl.dlss_nr implementation, no dedicated sl_dlss_nr.h API header, and no public documentation of its input/control/state contract.
2. DLSS 310.9.1 does not replace our current direct Feature 18 teacher. The public DLSS tree contains the normal DLSS, DLSS-RR, and DLSS-G SDK artifacts but no public nvngx_dlssnr.dll or Feature 18 implementation. Its new RR model is aimed at a different ray/path-traced denoising path.
3. The current OpenNR teacher remains the private, pinned nvngx_dlssnr.dll 310.8.x route. The student still needs native Feature 18 labels, exact native guides, strict temporal evidence, and two-cohort validation. Neither upstream update supplies the missing Skyrim-specific teacher state, stereo route, or VR-compositor proof.
4. The safest immediate action is no production update. Prepare an isolated Streamline 2.14.1 inventory/probe later, with an exact matching release package and a preserved 2.13 fallback. Do not mix 2.14.1 headers with the current 2.13 binaries.

## Decision matrix

| Candidate | Immediate OpenNR value | What it can answer | What it cannot establish | Decision |
| --- | --- | --- | --- | --- |
| DLSS 310.9.1 | Low for the current Feature 18 teacher; selective for SDK/harness work | Whether a clean public NGX/RR harness is easier to maintain, and whether RR Preset F is relevant to a separate ray-traced path | Feature 18 parity, teacher weights/state, SkyrimVR stereo, SteamVR/OpenXR delivery, or student quality | Do not replace the current teacher or update the live route |
| Streamline 2.14.1 | Medium now; potentially high for a future isolated NR route | Whether the official sl.dlss_nr host surface can consume our renderer/color/control contract | A usable public NR API, runtime quality, hidden state, temporal behavior, or VR acceptance | Inventory and probe only after exact package pairing and isolation |
| Streamline 2.14.1 robustness changes | Medium as targeted maintenance references | Whether clone/present/path diagnostics address an observed local failure | General image-quality improvement or a lower VR frame time | Borrow selectively when a real failure maps to a changed path |
| Dynamic MFG / Vulkan LL2 additions | Low for this project | D3D12 MFG pacing on a conventional present path; Vulkan low-latency plumbing | SkyrimVR D3D11 Feature 18 behavior or SteamVR compositor acceptance | Keep out of the current OpenNR workstream |

The planning ratings above are ordinal engineering judgments, not external benchmarks. A higher rating means “closer to a justified next experiment,” not higher FPS, lower MAE, or better headset quality.

## What changed upstream

### NVIDIA DLSS 310.9.1

The official release page identifies DLSS 310.9.1 as available to developers and lists:

- DLSS Ray Reconstruction Transformer Mode, Preset F.
- Bug fixes and stability improvements.

The checked-out commit changes 74 files relative to the prior public 310.7.0 tree. The visible functional/API changes include:

- Ray Reconstruction Preset F is now documented as the default RR2 model in nvsdk_ngx_defs_dlssd.h. This is a model-selection change for the RR feature, not a new public DLSS-NR teacher.
- The old monolithic helper header is split into D3D, CUDA, DLSS-RR-D3D, and DLSS-G-D3D helper headers.
- A header-only NGX loader is added. It dynamically locates NGX core libraries and resolves function pointers, including adjacent DLL and registry/driver-store lookup paths on Windows.
- Header-only standalone CUDA initialization, feature creation, evaluation, parameter management, and progress-callback helpers are added.
- Windows ARM64/ARM64EC and Linux AArch64 artifacts are added or refreshed.
- The released binary set includes nvngx_dlss.dll, nvngx_dlssd.dll, and nvngx_dlssg.dll. It does not include a public nvngx_dlssnr.dll in the checked-out DLSS SDK tree.
- The public feature enumeration still labels ID 18 as Reserved18. That is a strong boundary against treating this public DLSS repository as a source or replacement for the private Feature 18 runtime used by OpenNR.

This is useful engineering plumbing for a future standalone D3D12/CUDA harness, but it is not a reason to change the Skyrim path. The new loader is designed around the public NGX feature libraries. It does not solve the current direct nvngx_dlssnr.dll loading, signed-runtime path behavior, separate D3D12 interop device, six-slot stereo/sequential evaluation, or the private Feature 18 parameter contract.

### NVIDIA-RTX Streamline 2.14.1

The official 2.14.1 release page lists:

- V-Sync and frame-limiter support for Dynamic DLSS Multi Frame Generation.
- VK_NV_low_latency2 support.
- Bug fixes and stability improvements.

The release commit’s changelog begins with a section labeled Release 2.14.0 Entries. The commit is therefore best read as a combined 2.14.0 feature batch plus the 2.14.1 release packaging/notes; this is an inference from the tag, parent commit, and changelog layout.

The most OpenNR-relevant additions in that feature batch are:

- A new DLSS 3D-Guided Neural Rendering plugin, sl.dlss_nr.
- A new Streamline feature ID, kFeatureDLSS_NR = 1004.
- Three new generic resource tags:
  - kBufferTypeUpliftInputColor = 70.
  - kBufferTypeUpliftOutputColor = 71.
  - kBufferTypeUpliftControlMask = 72.
- Streamline common-resource handling now recognizes uplift output as a write-through output.
- Resource metadata adds a Vulkan swap-chain-image internal flag so Streamline does not invoke a host release callback for an image it did not allocate.
- D3D11/D3D12 present logic now checks actual tearing capability before setting DXGI_PRESENT_ALLOW_TEARING.
- D3D12 clone handling masks unsupported allocation flags and alignment values before creating internal copies.
- NGX application-data/plugin lookup moves from the system temporary directory to the Streamline plugin directory.
- Nsight GPU Trace activity is initialized for better captures.
- Vulkan swap-chain, present, profiling, and queue-annotation fixes are included.
- The repository adds integration/validation checklists and agent skills for DLSS-SR, DLSS-RR, DLSS-FG, and Reflex/PCL. Those are process assets, not an OpenNR runtime implementation.

The checked-out Streamline source tree does not contain source/plugins/sl.dlss_nr, a dedicated sl_dlss_nr.h, or a public NR integration guide. Its package README also states that binary artifacts are obtained from release zips rather than the GitHub source tree. That makes the new feature important but opaque: the host-side identifiers are public, while the actual plugin behavior and detailed resource contract remain release-binary questions.

## Local OpenNR alignment

The local inspection found a version boundary that matters before any update:

| Local component | Observed state | Interpretation |
| --- | --- | --- |
| Direct NR runtime | vendor/open-shaders-dlssnr-vr-091bfb4d/src/Features/Upscaling/NeuralRendering/Runtime.cpp loads nvngx_dlssnr.dll, requires major 310/minor 8, and creates/evaluates Feature 18 directly | This is the current private teacher route and remains the authority |
| Direct NR binary | D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\streamline\streamline\nvngx_dlssnr.dll, file version 310.8.0.0, SHA-256 E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E | Do not replace or relabel this from the public 310.9.1 DLSS SDK |
| Local Streamline compile headers | vendor/open-shaders-dlssnr-vr-091bfb4d/extern/Streamline-DX12/include/sl_version.h reports 2.12.0 | The source/header checkout is older than the packaged runtime |
| Local Streamline runtime | D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\streamline\streamline contains sl.interposer.dll, sl.common.dll, sl.dlss.dll, sl.dlss_g.dll, sl.dlss_nr.dll, sl.reflex.dll and sl.pcl.dll at file version 2.13.0 | The current packaged DLL set is newer than the compile headers and already contains an sl.dlss_nr binary |
| Current Streamline host code | src/Features/Upscaling/Streamline.cpp loads DLSS/Reflex/PCL for D3D11 and DLSS-G/Reflex/PCL for D3D12; Streamline.h has no kFeatureDLSS_NR path | The local sl.dlss_nr binary is present but no host-side NR route was found |
| Current research status | RENDERER_CONTEXT_CONDITIONING_20260908.md and OPENNR_LATEST_FINDINGS_20260908.md record that the 0.011 ordinary-1x MAE objective remains unmet, the renderer-input and multi-layer arms failed the all-five promotion gate, and no model was promoted | A new SDK update does not remove the need for better paired native teacher/state evidence |

The presence of sl.dlss_nr.dll at 2.13.0 means the idea is not entirely new to the local package, but it does not demonstrate that it is loaded, supported, called, or semantically equivalent to direct Feature 18. The current host code checks only the existing DLSS/DLSS-G/Reflex/PCL feature set. This is a package/file-health observation, not live runtime acceptance.

## Usefulness to the project

### 1. Direct Feature 18 teacher replacement: not useful now

The current direct route and the public NVIDIA repositories operate at different compatibility boundaries:

- OpenNR requires nvngx_dlssnr.dll and Feature ID 18, with version gating at 310.8.x.
- DLSS 310.9.1 publicly exposes the ordinary DLSS/RR/FG SDK libraries and still presents Feature 18 as reserved in its public feature list.
- Streamline’s new NR feature is a generic Streamline plugin surface, not a documented drop-in replacement for the direct Feature 18 DLL or its private parameters.

Replacing the current teacher would therefore change both the binary and the host contract at once. It would invalidate current labels and make any metric change ambiguous. No such replacement is justified.

### 2. Future 3D-Guided NR route: the highest-value lead, but an isolated probe only

Streamline 2.14.1 gives the project its first official-looking public host identifiers for an uplift/3D-guided neural-rendering feature. This could eventually matter in three ways:

- It may provide a supported path for evaluating a color transform or neural uplift without the current direct Feature 18 wrapper.
- The uplift input/output/control-mask tags may clarify the intended resource lifetime and write-back semantics for a neural pass.
- The new feature ID and generic Streamline discovery APIs may let us determine whether the shipped plugin can be loaded and queried without guessing private exports.

The limitations are decisive:

- No public sl.dlss_nr source or dedicated header was found.
- The three uplift tags do not identify the required channel packing, resolution, color space, temporal inputs, model selection, or mask semantics.
- The public update does not expose teacher weights, hidden state, a training loss, or a causal state export.
- A plugin being loadable is not proof that it sees Skyrim’s D3D11 renderer, both eyes, correct source rectangles, correct HDR/display contract, or SteamVR/OpenXR output.
- A generic uplift control mask is not automatically equivalent to the 17-channel renderer-conditioning cache already audited locally.

Recommended status: keep this as a P0 research lead for a package-only/isolated probe after the current capture evidence is complete. Do not add it to the active MGO or OpenNR runtime yet.

### 3. Streamline robustness changes: targeted maintenance value

Several 2.14.1 source changes map to real classes of risk in the local code:

- D3D12 resource clone alignment/flag handling could reduce failures when Streamline copies tagged resources.
- Tearing-capability checks and expanded present diagnostics could help the existing D3D12 proxy/present path.
- The NGX plugin-directory change is relevant to the project’s separate DX11 and DX12 Streamline directories.
- More precise Vulkan resource and queue handling is useful as an upstream design reference, but SkyrimVR’s current target is D3D11 plus a separate D3D12 frame-generation/interop path.

These are maintenance hypotheses, not measured local fixes. They justify a controlled package matrix if a matching local failure is observed. They do not justify a blind runtime swap or a claim of improved VR frame time.

### 4. DLSS Ray Reconstruction Preset F: low current fit

Preset F is relevant to DLSS-RR/DLSSD, whose input contract is for noisy ray/path-traced rendering and associated guides. The current OpenNR path is a SkyrimVR neural-rendering/upsampling path with native Feature 18 labels, depth/motion guides, stereo reprojection work, and renderer-derived conditioning experiments. It is not currently a validated ray/path-traced RR integration.

The new RR model is therefore a separate research branch. It should not be used as a proxy for DLSS-NR, as a student teacher, or as evidence that the current Skyrim renderer can supply RR-quality guide data.

### 5. Dynamic MFG, V-Sync, and Vulkan low latency: outside the current quality bottleneck

The Dynamic MFG/V-Sync and VK_NV_low_latency2 changes are valuable for conventional Streamline integrations. They do not address the current OpenNR bottleneck:

- the training objective and visual teacher gap remain unresolved;
- the direct teacher is Feature 18, not DLSS-G;
- SkyrimVR’s game renderer is D3D11;
- SteamVR/OpenXR compositor timing and headset comfort are separate acceptance layers.

Keep these changes as background for the existing D3D12 DLSS-G path only. Do not spend quality/training effort on them before the teacher/data contract is better understood.

## Recommended next actions

| Priority | Action | Acceptance gate | Explicit non-goal |
| --- | --- | --- | --- |
| P0 | Preserve the current native Feature 18 teacher and current 0.5.7 worktree/package state | Hash-verified backup and a known-good rollback remain available | No DLL replacement, profile change, or public package rebuild |
| P0 | Complete the prepared reset/warm renderer-state capture tranche | At least eight exact reset/warm pair units, normally 16 valid 64-frame clips; both eyes; contiguous IDs; native guides; renderer stages; strict audit | Do not add a state-loss term or relabel with an external runtime |
| P0 | Create a read-only Streamline 2.14.1 package inventory | Obtain the exact release zip, record asset/file hashes, list every matching DLL/license, and keep it outside the active runtime | Do not mix 2.14.1 headers or DLLs into the 2.12/2.13 route |
| P1 | Compile an isolated host probe for kFeatureDLSS_NR if the release package exposes a usable contract | Feature discovery, load/support status, function binding, resource-tag validation, and clean shutdown all succeed on a throwaway D3D11/D3D12 test surface | No claim of SkyrimVR support from feature discovery alone |
| P1 | If the plugin can run, compare it against native Feature 18 on recorded resources | Reset-qualified first frame, static temporal burst, controlled motion, disocclusion, both eyes, source rectangles, HDR/display contract, and output hashes are all recorded | No optical-flow substitution for native motion vectors |
| P1 | Run a matched quality comparison only after the runtime contract is understood | Native Feature 18 remains the label authority; any new route must beat the matched control on the appropriate cohorts and preserve temporal/stereo behavior | No dataset relabeling based on one crop or one mean |
| P2 | Consider adopting upstream robustness changes | A local failure maps directly to the changed clone/present/path code and is reproduced before/after | No broad source merge merely because the upstream diff is large |
| P2 | Evaluate DLSS 310.9.1 RR or header-only NGX helpers as a separate harness | A concrete RR or public-NGX need exists and the new helper is tested outside the game route | No use of RR as a Feature 18 or OpenNR teacher substitute |

## Acceptance layers

The update must be evaluated in separate layers. Passing one does not imply the next:

1. Source/API health: exact headers, source, ABI/version pairing, compile, static checks, and license files.
2. Package health: matching production DLLs, signatures/provenance, dependency closure, and fallback copy.
3. Offline functional health: feature discovery, resource tags, create/evaluate/release, reset behavior, and captured output hashes.
4. Game/render health: the plugin observes Skyrim’s actual D3D11/D3D12 resources and does not disturb the current Streamline split or direct Feature 18 route.
5. Stereo/temporal quality: both eyes, exact reset, motion-vector convention, jitter, disocclusion, source rectangles, and long temporal stability.
6. Headset/compositor health: SteamVR/OpenXR delivery, startup/recovery, UI/controller/menu behavior, and audible/headset inspection.
7. Deployment and VR budget: clean package, rollback, per-eye warm timing, frame pacing, reprojection behavior, and sustained VR-budget evidence.

The upstream repositories provide evidence primarily at layer 1, with release binaries relevant to layer 2. This assessment did not execute layers 3–7.

## Limitations and legal/packaging boundary

- The Streamline source tree documents the new sl.dlss_nr feature IDs/tags but does not publish the feature implementation or a dedicated host API header. The actual release binary must be inspected as a binary dependency, not assumed from the changelog.
- The Streamline changelog inside the 2.14.1 commit is headed Release 2.14.0 Entries. The combined-release interpretation is an inference from the commit/tag layout.
- Local file versions were inspected, but no live SkyrimVR, SteamVR, HMD, compositor, audible, or frame-budget acceptance was run for this report.
- The local project is dirty in both the OpenNR-VR checkout and the Open Shaders vendor checkout. Those user-owned changes were preserved.
- The NVIDIA DLSS SDK license is not an open-source license for the SDK binaries. It grants specific use and distribution rights, restricts reverse engineering and stand-alone redistribution, permits secure-network authorized users, and places separate constraints on cloud use and public commercial release. This is a project/legal review item, not a legal opinion. Keep vendor binaries, private teacher inputs, and any derived private tensors segregated from public source and distribution.
- Streamline’s source license and NVIDIA-supplied binary/runtime terms are not interchangeable. Use the exact license files delivered with the release package and do not infer redistributability from the public source repository alone.

## Method and evidence record

The assessment used:

- The official DLSS v310.9.1 release and commit, plus a clean local checkout at commit 374959484e79a640feaba44c93ac8cfb0a03f5b5.
- The official Streamline v2.14.1 release and commit, plus a clean local checkout at commit 2122257e0fce486f91b385aa63b9a09b0a34b363.
- A local source diff against the immediately preceding public commits: DLSS 310.7.0 and Streamline 2.12.0.
- Current OpenNR-VR status and renderer-conditioning records, including RENDERER_CONTEXT_CONDITIONING_20260908.md and OPENNR_LATEST_FINDINGS_20260908.md.
- The local Open Shaders vendor checkout at commit 40631c3c, with its dirty worktree preserved.
- Local file-version and SHA-256 inspection of the packaged Streamline 2.13.0 DLLs and 310.8.0.0 NGX binaries.

Primary public sources:

- DLSS 310.9.1 release: https://github.com/NVIDIA/DLSS/releases/tag/v310.9.1
- Streamline 2.14.1 release: https://github.com/NVIDIA-RTX/Streamline/releases/tag/v2.14.1
- Streamline 2.14.1 commit: https://github.com/NVIDIA-RTX/Streamline/commit/2122257e0fce486f91b385aa63b9a09b0a34b363
- Streamline 2.14.1 changelog at the assessed commit: https://raw.githubusercontent.com/NVIDIA-RTX/Streamline/2122257e0fce486f91b385aa63b9a09b0a34b363/changelog.txt
- Streamline README and release-binary policy: https://github.com/NVIDIA-RTX/Streamline/blob/main/README.md
- NVIDIA RTX SDK license: https://github.com/NVIDIA/DLSS/blob/main/LICENSE.txt

## Bottom line

Do not update the active OpenNR/MGO runtime from these releases yet.

Streamline 2.14.1 is worth a controlled future probe because its new sl.dlss_nr/kFeatureDLSS_NR/uplift-tag surface is the first upstream lead that could overlap the project’s long-term neural-rendering route. That lead is not actionable as a production integration until the release binary’s host contract, actual resource requirements, temporal behavior, and SkyrimVR stereo/compositor behavior are measured.

DLSS 310.9.1 is useful as a current RR/API reference and a possible isolated harness dependency, but it does not change the Feature 18 teacher, the pending reset/warm evidence tranche, the current two-cohort quality gates, or the requirement to keep native teacher labels authoritative.
