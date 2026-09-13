# DLSS5 real-weight static ONNX reconstruction: local assessment

Date: 2026-09-10
Decision status: research-only portability breakthrough confirmed; not suitable for OpenNR-VR promotion or live integration
Scope: the real-weight static ONNX artifact described in the supplied finding, not the separate small `DLSS5PortableModel` checkpoint

## Executive recommendation

The new finding is credible at the artifact and reproducibility level. The published `taowen/dlss5-onnx` model is a 1.17-GB ONNX graph that loaded locally, reproduced all four published reference outputs exactly, and exposed the declared fixed `[1,3,256,256]` current-RGB contract. The model is materially different from the small 12.7k-parameter `DLSS5PortableModel` tested in the earlier assessment: this artifact contains the claimed recovered real-weight static network.

It is still not an OpenNR-VR teacher replacement, Feature 18 replacement, temporal model, stereo model, or SkyrimVR runtime candidate.

On the frozen OpenNR spatial test set, the real-weight graph did not beat the identity input in aggregate. With the direct normalized OpenNR byte interpretation, its MAE was `0.02415306` versus the identity baseline at `0.02385935` across 128 exact 256x256 held-out tiles: `+0.00029372`, or `1.23%` worse. It won 63 of 128 tiles, but the aggregate regressed. With the model's stated sRGB-to-linear contract applied to the OpenNR RGB8 bytes, MAE was `0.03508473`, `47.05%` worse than identity, and only 5 of 128 tiles improved.

The bounded temporal probe showed the same split result: a small static improvement on one 32-frame held-out stream, but an `8.75%` worsening of frame-to-frame teacher-delta error and only `68.0%` of the teacher's mean delta magnitude. Exact repeat inference was deterministic, as expected from a current-RGB-only stateless graph; no temporal history, reset, reprojection, or native guide contract was exercised.

Recommendation:

1. Keep the real-weight ONNX artifact and local measurements in the isolated research area as a valuable reconstruction/reference asset.
2. Do not change the active native Feature 18/Open Shaders route, MGO deployment, OpenNR capture contract, current training lineage, or promoted-model status.
3. Do not use this graph as the OpenNR teacher, a production student, a temporal/stereo inpainting model, or a drop-in SkyrimVR runtime.
4. If a follow-up is explicitly authorized, use it only as a separate static/reference or intermediate-feature research branch. The native Feature 18 teacher remains authoritative for OpenNR labels and acceptance.

## What was tested

The pasted finding named three related but separate things:

| Item | Local treatment | Decision relevance |
|---|---|---|
| `dlss5_real_static_256.onnx` from `taowen/dlss5-onnx` | Downloaded, hash-verified, loaded with ONNX Runtime, run on published fixtures and OpenNR data | This report's primary subject |
| Recovered source/reconstruction repository at commit `59a414cfd09676f3a09ff042330b5dc8407ebc79` | Pinned and inspected in the existing isolated clone; native DLL/CUBIN material was not executed | Provenance and source-contract context |
| Small `DLSS5PortableModel` and `dlss5_pytorch_portable_v1.pt` | Already assessed separately in [`DLSS5_PORTABLE_MODEL_ASSESSMENT_20260910.md`](D:/.CODEX_Projects/OpenNR-VR/docs/DLSS5_PORTABLE_MODEL_ASSESSMENT_20260910.md) | Do not conflate its negative result with this real-weight graph |

The test intentionally did not install anything into the active OpenNR or SkyrimVR runtime. The downloaded model, isolated Python dependencies, outputs, and reports are under:

```text
C:\OpenNR\research\dlss5_real_onnx_20260910\
```

No native DLL or CUBIN was loaded for this assessment. This matters because a static ONNX result is not evidence that the private Windows runtime, resource bindings, or native Feature 18 execution path has been reproduced.

## Provenance and artifact identity

The source/reconstruction snapshot was locally confirmed as:

```text
repository: https://github.com/taowen/dlss5-as-inpainting
commit:     59a414cfd09676f3a09ff042330b5dc8407ebc79
clone:      C:\OpenNR\research\dlss5-as-inpainting_20260910_59a414c
```

The released model was obtained from `taowen/dlss5-onnx` at Hub revision `d3c44c4ea314d03ea7540cfc9ac4411f9dcfba28` (last modified 2026-09-09 13:24:36 local API time). The local artifact is:

```text
file:       C:\OpenNR\research\dlss5_real_onnx_20260910\dlss5_real_static_256.onnx
bytes:      1,167,220,673
sha256:     4f48985cd8398085910422745ed297d76dcd61bf6d77464ad8c4a06f7dc42c23
parameters: 145,755,691  (published model metadata)
opset:      17      (published model metadata)
```

The local SHA-256 exactly matches the published model-card hash. The source repository and model card describe this as a research reconstruction, not an official NVIDIA release. The Hub model metadata returned no license value, and the source snapshot still does not provide a normal license grant in its repository metadata; resolve ownership and redistribution terms before packaging or redistributing any native-derived artifact.

Primary external references:

- [Hugging Face model card](https://huggingface.co/taowen/dlss5-onnx) — artifact, contract, limitations, published hash, and validation claims.
- [Pinned reconstruction commit](https://github.com/taowen/dlss5-as-inpainting/commit/59a414cfd09676f3a09ff042330b5dc8407ebc79) — source/reconstruction provenance.
- [Pinned source tree](https://github.com/taowen/dlss5-as-inpainting/tree/59a414cfd09676f3a09ff042330b5dc8407ebc79) — separate native, semantic, and small portable execution paths.

## Published tensor contract, independently checked locally

The ONNX Runtime session exposed exactly:

```text
input:  rgb     [1, 3, 256, 256]  float32
output: output  [1, 3, 256, 256]  float32
```

The published color contract is `[0,1]` linear RGB in and `[0,1]` linear RGB out. The model is fixed to batch 1 and 256x256. Local shape probes rejected 512x512, non-square, and batch-2 inputs with `INVALID_ARGUMENT`.

The graph has only the current `rgb` input. The published static setup embeds frame-zero noise, uses current color/history fallback, sets auxiliary and scalar lanes to zero, and selects the reference RGB post branch. It therefore does not accept OpenNR depth, motion vectors, ControlMask, history, reset flags, or renderer conditioning.

This is a fixed-size image-to-image graph, not a full-resolution upscaler API. Applying it to OpenNR's `2496x2688` color eye would require a new tiling, overlap, seam, color conversion, and scheduling wrapper. None of those are supplied or validated here.

## Reproduction of the published cases

The four published 256x256 input/output arrays were downloaded and evaluated with ONNX Runtime `1.27.0` on the local CPU provider. All outputs were finite and matched the published arrays exactly:

| Case | MAE vs published output | Maximum absolute error | Measured inference |
|---|---:|---:|---:|
| `blue_marble` | `0` | `0` | `5.3478 s` |
| `portrait_cc0` | `0` | `0` | `5.0648 s` |
| `scenic_landscape` | `0` | `0` | `5.1055 s` |
| `stone_texture` | `0` | `0` | `5.0859 s` |
| Median | `0` | `0` | `5.0957 s` |

The benchmark included one warm-up and one measured run per case; timings include ONNX Runtime `session.run` and its input/output transfer, but not file I/O. A separate CLI run measured `3.1229 s` for one `blue_marble` inference, so the observed CPU range is roughly 3.1–5.3 seconds per 256x256 image under the current host load. This is model portability evidence, not a production performance claim.

The local published-case artifact is:

```text
C:\OpenNR\research\dlss5_real_onnx_20260910\cpu_benchmark\validation.json
```

## Frozen OpenNR spatial evaluation

### Dataset and controls

The evaluation used the existing immutable spatial cache:

```text
C:\OpenNR\TrainingCache\full_eye_periodic_spatial_20260909
```

The cache contains 240 512x512 RGB patches with a sequence-level train/validation/test split. The frozen test portion contains 32 patches from the held-out sequences. Each 512x512 patch was divided into four non-overlapping 256x256 tiles, producing 128 model calls. The native Feature 18 teacher tile and input tile remained spatially paired.

The identity baseline is the OpenNR input bytes returned unchanged. No model weights, thresholds, crops, or test rows were tuned from these results. The test was an inference-only comparison against the existing teacher.

OpenNR's stored color is `R8G8B8A8_UNORM` normalized to `[0,1]`; the capture format does not make it equivalent to the published model's linear-RGB contract. Therefore two interpretations were measured rather than silently assuming one:

- Direct-code: feed OpenNR normalized bytes directly and compare the model output directly to normalized teacher bytes. This is the closest apples-to-apples diagnostic to the existing cache/identity baseline.
- sRGB-linear: decode OpenNR normalized bytes to linear RGB, run the model, encode the result back to sRGB, then compare to normalized teacher bytes. This follows the external model's stated color contract if the OpenNR bytes are interpreted as sRGB.

### Aggregate result

| Path | Identity MAE | Real-weight MAE | Change vs identity | Tiles better than identity |
|---|---:|---:|---:|---:|
| Direct normalized code | `0.02385935` | `0.02415306` | `+0.00029372` (`1.23%` worse) | `63 / 128` |
| sRGB -> linear -> sRGB | `0.02385935` | `0.03508473` | `+0.01122539` (`47.05%` worse) | `5 / 128` |

The direct-code path is the less damaging diagnostic, but it still fails the aggregate identity comparison. Its mixed tile wins do not establish broad quality transfer; the mean, frozen test set, and teacher-match gate remain negative. The contract-corrected path produces visibly elevated grain/noise and a substantially larger teacher error on the sampled OpenNR material.

The evidence is visual as well as numeric. A four-row input/direct-code/sRGB-linear/Feature-18-teacher sheet is preserved at:

```text
C:\OpenNR\research\dlss5_real_onnx_20260910\opennr_spatial_test\opennr_spatial_ab_sheet.jpg
```

The full machine-readable result, including per-tile records and held-out sequence grouping, is:

```text
C:\OpenNR\research\dlss5_real_onnx_20260910\opennr_spatial_test\result.json
```

## Bounded temporal and reset probe

The external graph is not stateful, but a local probe was still run to prevent a folder-level or initial-reset claim from being mistaken for temporal behavior.

The probe used 32 contiguous frames from one sequence-held-out test sequence, eye 0, and the center 256x256 tile of the strict temporal cache:

```text
cache:    C:\OpenNR\TrainingCache\full_eye_temporal_pilot_strict_20260908
sequence: seq-1788915943240-14
eye:      0
frames:   1..32
first reset: true
mid resets:  false
```

The model received only current RGB in the direct normalized-code interpretation. Results:

| Measurement | Identity input | Real-weight static graph | Change |
|---|---:|---:|---:|
| Static MAE | `0.01871995` | `0.01847112` | `1.33%` better in this narrow stream |
| Frame-to-frame teacher-delta error | `0.01094367` | `0.01190145` | `8.75%` worse |
| Mean output delta magnitude | `0.02575908` teacher magnitude | `0.01752720` model magnitude | `0.680x` teacher magnitude |

Repeating the exact first input produced a maximum absolute output difference of `0`. That confirms deterministic stateless execution for this ONNX session. It does not demonstrate temporal stability; without a history or reset input, the model cannot condition on the previous frame, perform motion reprojection, or update a temporal state.

The machine-readable temporal result is:

```text
C:\OpenNR\research\dlss5_real_onnx_20260910\opennr_temporal_probe\result.json
```

The probe's PNGs are diagnostic only; they are not headset or stereo acceptance evidence.

## Runtime and VR-budget assessment

The local inference installation exposed only:

```text
['CPUExecutionProvider']
```

No CUDA ONNX Runtime provider was available, so no GPU timing is claimed. The reference ONNX is also intentionally the reproducibility-oriented model with FP64 reductions and emulated precision boundaries, not a native FP8 GPU implementation.

At the published fixed shape, the measured CPU inference is approximately 3.1–5.3 seconds per tile. A naive non-overlapping decomposition of one `2496x2688` eye is 10x11 = 110 tiles; serialized two-eye model time would extrapolate to roughly 11.5–18.7 minutes before tile assembly, overlap handling, preprocessing, guide conversion, GPU/CPU transfer, compositor work, SteamVR, or frame pacing. This is an extrapolation, not a measured full-eye implementation, but it is already incompatible with a VR frame budget on the tested path.

Even a future GPU port would still need separate evidence for:

- a full-eye tiling/overlap policy with no seams;
- OpenNR's exact color and range conversion;
- any depth/motion/history/control-mask conditioning;
- temporal reset and motion response;
- left/right stereo consistency;
- GPU-resident interop and end-to-end frame time;
- SkyrimVR/Open Shaders/SteamVR delivery and headset stability.

The current artifact passes none of those live-runtime gates because it does not implement the required interfaces.

## Decision matrix

| Question | Decision | Reason |
|---|---:|---|
| Is the claimed real-weight ONNX artifact real and locally runnable? | Pass | Exact published hash, ORT load, finite output, fixed contract, and four published cases reproduced with zero numerical error. |
| Is it a recovered static graph with substantially more capacity than the small portable checkpoint? | Pass, with scope limits | Published metadata reports 145,755,691 parameters and the source/model documentation describes the recovered 71-block static path. This is not proof of complete native parity. |
| Does it replace the native Feature 18 teacher for OpenNR labels? | Reject | Frozen OpenNR spatial MAE regressed against identity; color contract remains unresolved; graph has no temporal/native guide contract. |
| Does it improve OpenNR static quality broadly? | Reject | Direct path was 1.23% worse over all 128 held-out tiles; sRGB-linear path was 47.05% worse. |
| Does it reproduce temporal behavior? | Reject | Current-RGB-only graph; exact repeat determinism; temporal-delta error worsened 8.75% in the bounded probe. |
| Does it support stereo/disocclusion inpainting? | Reject / untested capability | No eye coupling, geometry input, motion reprojection, hole mask, or state update is exposed by the tested model. |
| Is it a viable SkyrimVR runtime candidate? | Reject | Fixed 256x256 CPU-only local path, no GPU timing, no full-eye wrapper, no native integration, no VR acceptance. |
| Is it worth retaining for research? | Yes | It is a credible inspectable real-weight static reference and may support isolated feature/intermediate-supervision studies. |

## Recommended next action

Keep this artifact as an isolated research reference and leave the current OpenNR native teacher, capture contract, temporal cache, training lineage, and runtime untouched.

If a separate follow-up is later authorized, the safest useful experiment is not direct deployment. It would be a new, immutable-manifest study that:

1. aligns the exact OpenNR teacher/input color contract before training or scoring;
2. uses native Feature 18 outputs as the authoritative target rather than replacing them with the recovered static graph;
3. evaluates an explicit adapter or intermediate-feature loss in a separately named lineage;
4. keeps the 256x256 tiling/overlap wrapper and any guide encoding as explicit experimental components;
5. requires frozen sequence-level spatial, full-eye, reset-qualified temporal, stereo, visual, and end-to-end VR gates before any runtime consideration.

The only promotion that this local test earned is a provenance classification:

> **Real-weight static ONNX reconstruction: confirmed as a portable research artifact; not OpenNR-ready.**

## Local evidence inventory

```text
Source clone:
C:\OpenNR\research\dlss5-as-inpainting_20260910_59a414c

Model and runtime:
C:\OpenNR\research\dlss5_real_onnx_20260910\dlss5_real_static_256.onnx
C:\OpenNR\research\dlss5_real_onnx_20260910\cpu_benchmark\validation.json
C:\OpenNR\research\dlss5_real_onnx_20260910\cli_blue_marble_output.png

OpenNR static evidence:
C:\OpenNR\research\dlss5_real_onnx_20260910\opennr_spatial_test\result.json
C:\OpenNR\research\dlss5_real_onnx_20260910\opennr_spatial_test\opennr_spatial_ab_sheet.jpg

OpenNR temporal evidence:
C:\OpenNR\research\dlss5_real_onnx_20260910\opennr_temporal_probe\result.json
C:\OpenNR\research\dlss5_real_onnx_20260910\opennr_temporal_probe\samples\
```

All results above are local measurements from this isolated assessment. They do not authorize a runtime change or promote any model.
