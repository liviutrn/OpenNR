# The AMD HIP port is a valuable backend reference, not an OpenNR runtime candidate

Assessment date: 2026-09-13  
Scope: `guentra/dlss5-amd-hip-linux`, release `v0.1.0-poc`, and its relevance to the OpenNR-VR / SkyrimVR Feature 18, white-box, fusion, and distillation work.  
Decision state: research-only; `promotion=false`.

## Recommendation

Keep this repository as a pinned, read-only research reference. It is relevant enough to inform the native-style CUDA/fusion and graph-contract work, and it provides a useful independently written HIP expression of the claimed 71-block schedule. It is not, however, a validated NVIDIA-equivalent teacher, a trainable student, a temporal/stereo implementation, or a candidate for the protected Windows SkyrimVR runtime.

The useful next step is a small, isolated experiment inspired by the repository: adopt compact per-stage health telemetry and, only if the native-parity prerequisite is met, add selected intermediate activation dumps around the ViT and one encoder/decoder boundary. Do not start a broad new Skyrim capture tranche, do not install the Linux bridge into MGO/OpenNR, and do not promote any weights or graph derived from this repository.

## Executive summary

The lead is materially more relevant than a README-only claim or another small portable model. The public source contains explicit HIP/rocWMMA kernels, a 71-block network object, a weight conversion path, a synchronous C API, a temporal-capable V2 frame surface, and a live Wine/vkd3d/ReShade integration boundary. The source is therefore valuable for studying implementation structure, fixed layouts, stage boundaries, and how a full graph is made inspectable.

The important boundary is equivalence. The converter and runtime metadata explicitly mark the C32/attention layouts and the ViT bridge as AMD-consumer-derived rather than proven NVIDIA tensor maps. Strict conversion refuses incomplete mappings unless the derived-layout mode is enabled, and the runtime reports `nvidia_equivalence_verified=false`. The repository itself therefore supports the conclusion that this is an executable reconstruction scaffold, not a mathematically verified native Feature 18 graph.

The timing claim is also correctly bounded. The release reports approximately 210–216 ms of GPU time for one 1920x1080 inference on an RX 9070 XT (`gfx1201`). The live route adds CPU readback/upload and makes the game wait. It resets temporal history each live frame because motion readback is not wired through that hook. This is useful proof-of-concept evidence, but it is not comparable to live SkyrimVR FPS, per-eye delivery, headset quality, or the local native Feature 18 timing anchors.

The lead changes the priority of one research question, not the project acceptance gates: “Can internal graph features help design a smaller student?” becomes testable in a controlled way, but only after the teacher source and frame contract are trustworthy. The repository’s current trace is a scalar health summary, not an activation-dump facility, and it contains no autograd, training loop, LoRA, or student checkpoint.

## What was verified

The assessment used the public repository and release pages plus a read-only local clone at:

`C:\OpenNR\research\dlss5-amd-hip-linux_20260913`

The clone is pinned to commit `2361caf52d1fd903c2aab0dcf8778d3b31981c8e`. No external binary was executed, no Linux bridge was installed, and no OpenNR/MGO runtime or profile was modified.

| Area | Verified observation | Interpretation |
|---|---|---|
| Graph | `hip/src/network.hip` wires preblock, Swin encoder, eight 640-token × 1024-channel ViT blocks, decoder/skip stages, postblock and RGB head; the network object exposes 71 logical blocks. | Strong evidence of a real full-graph source scaffold rather than a partial kernel demonstration. |
| Weight conversion | The converter is pinned to a specific private `nvngx_dlssnr.dll` SHA and records 223 coefficient tables. C32/attention layouts and the ViT bridge are marked derived. | Useful for controlled experiments; not proof of exact NVIDIA tensor-map equivalence. |
| Trace | `DLSS5_HIP_TRACE` reduces each marked block to count, nonfinite count, min, max, sum and hash. | Low-volume stage-health and identity telemetry; not serialized intermediate features. |
| C API | V1 is static/no-history. V2 accepts motion, reset, history, transfer, color and paper-white state and has explicit lifecycle/error behavior. | A good API contract to study. It does not establish temporal correctness by itself. |
| Live path | The Windows-facing helper reads a D3D12 resource back to CPU, resizes, calls the HIP DLL with `reset=1`, resizes back, and uploads the result. The code logs that the path is not temporal. | The live route is a synchronous proof of integration, not an OpenNR-compatible temporal path. |
| Performance | The public release reports about 210–216 ms GPU time per 1920x1080 inference on RX 9070 XT/gfx1201. | Network-only POC timing; not in-game, stereo, compositor, or HMD acceptance. |
| Reproducibility | The public `Makefile` references regression tests that are absent from the source snapshot. No local AMD gfx1201/ROCm reproduction was available. | Source structure is inspectable, but independent performance/equivalence reproduction remains incomplete. |
| Licensing | Project code is marked MIT; modified vkd3d-proton is separately identified as LGPL-2.1-or-later. The repository says NVIDIA DLLs and weights are not included. | The public code can be reviewed, but vendor-derived coefficients and bundled runtime components require a separate private-use/redistribution review. |

The primary external sources are the [repository README](https://github.com/guentra/dlss5-amd-hip-linux), [HIP backend README](https://github.com/guentra/dlss5-amd-hip-linux/blob/main/hip/README.md), [v0.1.0-poc release](https://github.com/guentra/dlss5-amd-hip-linux/releases/tag/v0.1.0-poc), [build notes](https://github.com/guentra/dlss5-amd-hip-linux/blob/main/docs/BUILD.md), [third-party notices](https://github.com/guentra/dlss5-amd-hip-linux/blob/main/linux/THIRD-PARTY.md), and [license](https://github.com/guentra/dlss5-amd-hip-linux/blob/main/LICENSE).

## Relevance to OpenNR-VR

| Project area | Relevance | Recommendation |
|---|---:|---|
| Explicit graph and kernel architecture | High | Read and selectively borrow design patterns for fixed layouts, stage manifests, fused kernels, workspace ownership, finite checks, and host/graph boundaries. |
| Intermediate-feature distillation | Medium, conditional | Treat the repository as an experiment scaffold. Add selected activation capture only in a separate lineage, and only after source-matched native first-frame parity is established. |
| Native Feature 18 teacher | None for promotion | Keep the actual local Feature 18 output as the authority. Do not relabel this graph or its outputs as native teacher targets. |
| Smaller student / LoRA / trained model | Low today | There is no training code or checkpoint. The repository may inform architecture ablations, but it does not justify spending broad training or capture budget. |
| Windows SkyrimVR runtime | Low / fail for current scope | Do not port the Linux/Proton/ReShade/vkd3d bridge into the protected route. The platform, hook ownership, GPU target and resource contract differ. |
| Temporal quality | Not established | The V2 API is interesting, but the supplied live path resets history every frame and has no verified motion-guide ownership. |
| Stereo and HMD delivery | Not established | Nothing in the repository proves full-eye parity, per-eye resource correctness, compositor behavior, headset output, or VR budget. |
| Legal/package readiness | Unresolved for derived artifacts | Preserve private source-matched coefficients and do not redistribute vendor-derived data or modified runtime pieces without review. |

This is a backend-research lead, not a new deployment lead.

## Comparison with the current local baseline

The local project already has a more relevant hardware-local path for the primary target. The current target is Windows 11 SkyrimVR with Quest 3/OpenXR, an RTX 5070 Ti, and the exact Feature 18-bound per-eye color/depth/motion/reset contract. The external repository targets Linux x86_64, ROCm/HIP 7, `gfx1201`, and a Wine/Proton integration built around an FSR hook and modified vkd3d behavior.

The local native-style fusion work has already shown why the external source is useful as a reference: a C32 feed-forward probe reduced a 127.633 ms eager control to 5.477 ms, and a complete C64 block measured 1.980 ms versus 35.823 ms for its eager control. Those are isolated CUDA measurements, not live VR acceptance, but they point toward the same practical lesson as the HIP port: fixed layouts and fused execution dominate the useful optimization surface.

The external 210–216 ms number should not be placed on the same scorecard as the local measurements. It is a different GPU, backend, graph implementation, resolution contract, and timing boundary. In particular, it does not contradict the local native Feature 18 stereo anchor of roughly 24 ms, nor does it establish a replacement for it. The correct comparison is architectural: both lines support measuring fused schedule cost and memory movement; neither line, by itself, proves live OpenNR readiness.

The teacher boundary remains the decisive one. The recovered MLX-DLSS replay improved some RGB rows but did not meet the local Gate-A requirement of approximately `<=0.007`; the fresh full-frame replay was about `0.01994314` MAE against the native output and included material per-sequence regressions. That result makes it unsafe to use a partly derived external graph as unquestioned feature supervision. A feature probe can be valuable, but it must remain explicitly attached to a named, parity-qualified lineage.

Relevant local evidence: [native kernel investigation](WHITEBOX_NATIVE_KERNEL_INVESTIGATION_20260912.md), [native-style C32/C64 probe](WHITEBOX_NATIVE_STYLE_C32_PROBE_20260912.md), [white-box distillation assessment](WHITEBOX_DLSS5_DISTILLATION_ASSESSMENT_20260911.md), and the [current OpenNR baseline](../README.md).

## The per-block trace and ViT opportunity

The suggested focus on tracing and the eight ViT blocks is directionally right, with one correction: the current repository does not yet provide cheap intermediate activation capture. Its trace path launches a reduction after each marked block and reports scalar statistics and a hash after GPU synchronization. That is excellent for detecting nonfinite values, range explosions, stage changes, and replay instability. It is not enough to train a student against internal representations.

If this question earns a bounded experiment, use the following design:

1. Keep the external clone and all converted weights outside the protected native and student lineages.
2. Reproduce only one fixed-resolution, one-eye, one-frame graph slice first. Begin with one encoder boundary, one ViT input/output boundary, and one decoder boundary; do not dump every tensor by default.
3. Record graph commit, weight provenance, layout mode, source frame ID, eye, reset state, motion-guide validity, native input/output hashes, shape, dtype, and the exact boundary name.
4. Require a source-matched first-frame parity check against the native Feature 18 output before treating any activation as a teacher target. If parity fails, use the result only for architecture debugging or ablation.
5. Compare final RGB loss against selected feature losses, then test sequence-disjoint motion bursts and long reset-qualified temporal runs. Do not infer temporal value from static feature agreement.
6. Keep the trace sidecar and activation dumps separate from deployable checkpoints. Promotion remains false until full-eye output quality, temporal behavior, stereo consistency, runtime ownership and live VR budget all pass.

The first experiment should answer a narrow question: does supervision at one or two selected boundaries improve convergence or Pareto quality for a smaller model on a parity-qualified corpus? It should not attempt to turn the AMD port into a production backend.

## Recommended action order

### P0 — Preserve the boundary

- Keep the read-only clone pinned at commit `2361caf...` and record later upstream changes as new snapshots.
- Do not run the prebuilt release, install the modified vkd3d/ReShade route, or place its DLLs in MGO/OpenNR.
- Keep `promotion=false` for the repository, its layouts, its converted weights, and any outputs.

### P1 — Use the source where it adds signal

- Adopt the compact per-block scalar trace schema as a diagnostic sidecar concept for isolated local CUDA/recovered-graph probes, after checking that it does not duplicate or conflict with existing OpenNR traces.
- Continue native-style CUDA fusion and fixed-layout/resolution measurements on the RTX target. Compare kernel, graph, host-transfer, stereo and live-runtime costs in separate columns.
- If the parity prerequisite is met, implement a small activation probe around the eight ViT block boundaries plus one encoder and one decoder boundary. Make it a research-only branch/output directory.

### P2 — Spend data and training budget only on a proven question

- Do not launch a broad Skyrim data collection pass for this lead.
- Do not start LoRA or student training from the external graph or its derived coefficients.
- Collect new frames only if the bounded feature experiment identifies a specific missing visual regime or a measured native-parity failure that requires targeted evidence.

## Gate decisions

| Gate | Decision |
|---|---|
| Architecture/backend research | Pass as a reference. |
| Intermediate-feature experiment | Conditional; not ready as teacher supervision. |
| Native Feature 18 teacher replacement | Fail. |
| OpenNR Windows/SkyrimVR runtime fit | Fail for the current scope. |
| Temporal parity | Not established; supplied live route is reset-each-frame. |
| Stereo/full-eye/HMD/VR budget | Not established. |
| Promotion to student/runtime/package lineage | No. |

## Artifact and safety disposition

Created in the OpenNR-VR worktree:

- [recommendation report](DLSS5_AMD_HIP_LINUX_OPENNR_RECOMMENDATION_20260913.md)
- [reviewed machine-readable data snapshot](DLSS5_AMD_HIP_LINUX_OPENNR_RECOMMENDATION_DATA_20260913.json)

External source snapshot:

- `C:\OpenNR\research\dlss5-amd-hip-linux_20260913`
- commit `2361caf52d1fd903c2aab0dcf8778d3b31981c8e`

No binaries were executed. No external runtime was installed. No protected OpenNR/MGO profile, DLL, capture route, or live SkyrimVR configuration was changed. Existing user-owned dirty worktree changes were preserved.

## Bottom line

Yes, this is relevant—but specifically as an explicit backend and architecture-research scaffold. It is a strong lead for understanding fused full-graph execution and for designing a controlled intermediate-feature experiment. It is not evidence of NVIDIA equivalence, not a ready teacher, not a trainable student, and not a viable current OpenNR SkyrimVR runtime. The project should preserve it, mine its structure selectively, and keep all native, temporal, stereo, live-VR and promotion gates unchanged.
