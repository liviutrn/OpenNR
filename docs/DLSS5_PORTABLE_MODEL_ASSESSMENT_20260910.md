# DLSS5PortableModel assessment for OpenNR-VR

Date: 2026-09-10  
Decision status: research complete; supplied checkpoint rejected for OpenNR promotion or live integration  
Scope: `DLSS5PortableModel` from [`taowen/dlss5-as-inpainting`](https://github.com/taowen/dlss5-as-inpainting), assessed against the current OpenNR-VR teacher, capture, temporal, stereo, and VR-budget requirements.

## Executive recommendation

Do not use the supplied `DLSS5PortableModel` checkpoint as an OpenNR teacher replacement, production student, Feature 18 replacement, SkyrimVR runtime, or temporal/stereo inpainting model. On the existing OpenNR data it consistently worsened RGB-to-teacher error, and feeding the available native depth/motion guides made the result worse again.

The repository is still useful as a small, backend-independent residual-network reference and as a reproducible ONNX/TensorRT portability experiment. A separately trained RGB-only version could be retained as a narrow static-residual baseline if we later want that ablation. That would be a new OpenNR research candidate with its own manifest and gates, not adoption of the upstream checkpoint.

The practical recommendation is therefore:

1. Keep the upstream snapshot and measurements in the isolated research area.
2. Do not modify the active Feature 18/MGO path, capture contract, current training lineage, or promoted-model status.
3. If a follow-up is authorized, train the architecture from scratch or from an explicitly isolated OpenNR checkpoint using immutable sequence splits. Start with RGB-only input; do not use the supplied depth/motion-conditioned weights.
4. Continue prioritizing the existing OpenNR semantic/temporal work and strict live acceptance. This candidate cannot shortcut teacher matching, stateful temporal behavior, stereo consistency, or headset frame-budget validation.

## What the upstream project actually provides

The pinned upstream snapshot presents three materially different paths. They must not be conflated:

| Upstream path | What it is | Relevance to OpenNR |
|---|---|---|
| `DLSS5BitExactModel` | Native carrier/runtime path using the original NVIDIA-side artifacts; the project’s bit-exact claim is confined to that path and its compatible local runtime/GPU conditions. | Not a redistributable OpenNR teacher or a replacement for the private Feature 18 route. |
| `DLSS5Graph` | A recovered semantic graph with most of the visible graph translated, while the private front producer is not fully recovered. | Research/reference value only; not a complete teacher contract. |
| `DLSS5PortableModel` | A small ordinary-PyTorch residual approximation that can run on CPU/CUDA/ROCm/other backends. It is explicitly not a CUBIN clone or bit-exact native implementation. | A portable residual baseline and deployment scaffold, not a DLSS5/Feature 18 substitute. |

The relevant upstream documentation describes the portable model as a fitted approximation made from ordinary `Conv2d`, SiLU, concatenation, interpolation, and clamping operations. It preserves the input spatial dimensions, starts from an identity-like output head, and accepts optional depth, history, motion, and control-mask tensors. Missing optional conditions are zero-filled. The model has three convolutions with 32 hidden channels and about 12.7k parameters; its stacked 3x3 convolutions give it only a local approximately 7x7 receptive field.

That last point is important for the name “as inpainting.” The model has no reprojection, no spatial warp, no recurrent state, no learned memory update, and no mechanism for reconstructing a wide disocclusion from distant context. Its `control_mask` gates the residual; a zero mask copies the RGB source. That is not equivalent to a geometry-aware hole-filling or stereo-occlusion pipeline.

Primary upstream references:

- [Repository at the pinned commit](https://github.com/taowen/dlss5-as-inpainting/tree/59a414cfd09676f3a09ff042330b5dc8407ebc79)
- [`DLSS5PortableModel` implementation](https://github.com/taowen/dlss5-as-inpainting/blob/59a414cfd09676f3a09ff042330b5dc8407ebc79/src/dlss5/portable.py)
- [Portable model documentation](https://github.com/taowen/dlss5-as-inpainting/blob/59a414cfd09676f3a09ff042330b5dc8407ebc79/docs/DLSS5_PORTABLE.md)
- [User guide and native/portable input conventions](https://github.com/taowen/dlss5-as-inpainting/blob/59a414cfd09676f3a09ff042330b5dc8407ebc79/docs/DLSS5_USER_GUIDE.md)
- [Upstream stereo-pipeline design notes](https://github.com/taowen/dlss5-as-inpainting/blob/59a414cfd09676f3a09ff042330b5dc8407ebc79/docs/STEREO_PIPELINE_V2.md)

## Provenance and isolation

The assessment used this exact upstream commit:

```text
repository: https://github.com/taowen/dlss5-as-inpainting
commit:     59a414cfd09676f3a09ff042330b5dc8407ebc79
commit UTC: 2026-09-09 18:48:23 +08:00
clone:      C:\OpenNR\research\dlss5-as-inpainting_20260910_59a414c
```

The portable checkpoint was loaded with the safer `torch.load(..., weights_only=True)` mode for this assessment. Its identity is:

```text
file:       models/dlss5_pytorch_portable_v1.pt
size:       57,915 bytes
sha256:     b05d921c3ae7a4579eac5c8538c1e0834d7a9613ea296fae0ee5c08cc811f6c6
format:     dlss5_pytorch_portable_v1
steps:      250
parameters: 12,739
```

The checkpoint metadata reports the upstream ten synthetic source pairs and an identity MAE of `0.0293095652` versus a distilled MAE of `0.0159348045` after 250 steps. That is a valid upstream synthetic experiment result, but it did not transfer to OpenNR data.

The pinned snapshot did not contain a `LICENSE`, `NOTICE`, or `COPYING` file, and `pyproject.toml` did not declare license metadata. That is a provenance and redistribution caveat. The repository also contains a separate native NVIDIA DLL/CUBIN path; those files were not executed, copied into OpenNR, or treated as redistributable.

No active OpenNR, MGO, Feature 18, capture, training, or deployment file was changed for this assessment. Generated ONNX and TensorRT artifacts remain under the isolated `C:\OpenNR\research\...` tree.

## Compatibility with OpenNR requirements

| Requirement / gate | Result | Evidence and interpretation |
|---|---:|---|
| Match the native Feature 18 teacher | Fail | The supplied weights worsened OpenNR teacher MAE on every tested split and every full-eye sample. The model is explicitly an approximation, not a native graph/CUBIN clone. |
| OpenNR color contract | Caution / not equivalent | Upstream training and native notes use linear RGBA16F. The OpenNR cache used here is captured as R8G8B8A8/PNG RGB artifacts normalized to `[0,1]`. The comparison is a useful cross-domain diagnostic, not a formal native-equivalence test. |
| Native depth/motion conditioning | Fail for supplied weights | The upstream distillation script trains the portable checkpoint with optional conditions omitted, so the depth/history/motion weights have no useful OpenNR calibration. Supplying OpenNR depth and motion made MAE worse than the RGB-only default. |
| Temporal state/history/reset | Fail / absent | The portable model is stateless. It has no recurrent state, reset behavior, history update, or motion-based reprojection contract. The temporal test was therefore only a per-frame residual probe. |
| Stereo eye consistency | Fail / untested as a capability | There is no left/right coupling or stereo state. Both eyes were tested independently; no stereo improvement or paired inpainting claim is justified. |
| Occlusion/disocclusion inpainting | Fail as an OpenNR role | A local 7x7 residual and residual gate cannot stand in for the existing geometry/mask/history pipeline. The upstream stereo notes themselves describe the portable checkpoint as not proven to preserve DLSS5 hole-filling ability. |
| Portable backend/export | Pass as a scaffold | CPU/CUDA PyTorch, ONNX Runtime CPU, and TensorRT fixed-shape execution were reproduced with finite outputs and close numerical parity. This proves portability mechanics, not quality or SkyrimVR compatibility. |
| VR frame budget | Not accepted | TensorRT model-only cost at native color resolution is approximately 7.48 ms per eye median / 10.11 ms p95. Two-eye end-to-end cost was not measured and would also include preprocessing, guide preparation, copies, pack/unpack, compositor, and headset timing. |
| Legal/release readiness | Unresolved | The pinned snapshot has no discoverable license metadata. Do not redistribute or package its native artifacts without resolving ownership and license terms. |

## OpenNR test method

The tests used existing immutable OpenNR artifacts, with no test rows used to tune the direct checkpoint or the reported small adaptation probe:

- Static/full-eye spatial cache: 240 RGB patches, split `176 train / 32 validation / 32 test`, from `C:\OpenNR\TrainingCache\full_eye_periodic_spatial_20260909`.
- Strict temporal test: four held-out sequences, 64 frames per sequence, both eyes, 512 eye rows, with the recorded strict initial reset and no mid-sequence reset.
- Full-eye check: eight held-out full-color images, both eyes across four test sequences, at `2496x2688` source color resolution.
- Identity baseline: return the OpenNR input RGB unchanged.
- Portable default: run the supplied checkpoint with RGB input and omitted optional conditions, which is the checkpoint’s intended zero-filled condition path.
- Guide diagnostic: pass OpenNR depth and motion channels after resizing them to the RGB tensor size, leave history zero, and use an all-one control mask. This was deliberately treated as a diagnostic, not as a validated conditioning contract.

The local OpenNR capture contract remains authoritative for the teacher and guides: it uses the in-process Open Shaders Feature 18 tap, exact Feature 18-bound native depth/motion resources, and separate strict temporal evidence. See [`OPENNR_CAPTURE_FORMAT.md`](D:/.CODEX_Projects/OpenNR-VR/docs/OPENNR_CAPTURE_FORMAT.md) and [`build_raw_crop_cache.py`](D:/.CODEX_Projects/OpenNR-VR/tools/build_raw_crop_cache.py).

## Direct supplied-checkpoint results

### Static spatial cache: RGB-only default path

| Split | Identity MAE | Portable MAE | Change | Portable better fraction |
|---|---:|---:|---:|---:|
| All 240 patches | 0.03455896 | 0.03790971 | +0.00335075 | 6.25% |
| Train, 176 patches | 0.03643484 | 0.03977297 | +0.00333813 | 7.95% |
| Validation, 32 patches | 0.03494122 | 0.03729389 | +0.00235267 | 3.125% |
| Frozen test, 32 patches | 0.02385935 | 0.02827760 | +0.00441825 | 0% |

The supplied checkpoint is not merely neutral on OpenNR: it worsens the mean error, and it loses on every frozen test patch.

### Static cache with available native depth/motion guides

| Split | Identity MAE | Portable with depth+motion | Change versus identity | Change versus RGB-only portable |
|---|---:|---:|---:|---:|
| All | 0.03455896 | 0.04441600 | +0.00985704 | +0.00650629 |
| Validation | 0.03494122 | 0.04357883 | +0.00863761 | +0.00628494 |
| Frozen test | 0.02385935 | 0.03425128 | +0.01039193 | +0.00597368 |

This is the clearest reason not to wire the current OpenNR guide tensor into the supplied checkpoint. The model accepts channels syntactically, but the shipped condition weights are not trained for OpenNR’s depth/motion semantics or resolution contract. The actual guides increased the average deviation from the teacher.

### Strict temporal crop cache

Across 512 eye rows and 504 adjacent frame pairs:

| Measurement | Input identity | Portable RGB-only |
|---|---:|---:|
| Static MAE | 0.02310506 | 0.02644166 |
| Signed temporal-delta error versus teacher | 0.00918345 | 0.00975742 |
| Temporal-delta magnitude / teacher magnitude | 0.7842 | 0.7618 |

The portable model worsened static error by `+0.00333659` and temporal-delta error by `+0.00057397` (about 6.25% relative). It also reduced motion magnitude relative to the teacher rather than reproducing it. This is not temporal stabilization evidence: the model has no state, no reset, and no history update.

### Full-eye held-out RGB check

On eight actual full-eye images at `2496x2688`:

```text
identity MAE:  0.0294578392
portable MAE:  0.0323145259
change:       +0.0028566867
better eyes:  0 / 8
```

Every tested eye was worse than the identity input. Outputs were finite, but numerical validity is not quality acceptance.

## Bounded retraining probe

To determine whether the architecture itself has any narrow OpenNR value, I ran isolated 600-step probes on the 176 training patches, with validation selected independently and the frozen test retained for reporting. These probes did not save a checkpoint into the active project.

| Probe | Validation at step 0 | Best/late validation | Frozen test at step 0 | Frozen test at late point |
|---|---:|---:|---:|---:|
| Fresh RGB-only portable model, step 500 best validation | 0.03494122 | 0.03113106 | 0.02385935 | 0.02091167 |
| Supplied checkpoint warm-start, step 600 | 0.03729389 | 0.03158712 | 0.02827760 | 0.02170719 |
| Fresh depth+motion-conditioned model, step 600 | 0.03494122 | 0.03421614 | 0.02385935 | 0.02113400 |

The fresh RGB-only model improved the held-out validation score by about 9.1% relative at its step-500 validation best, which is enough to establish a possible static residual baseline. It is not enough for promotion: the absolute error remains far above the project’s teacher-match gate, there is no temporal/stereo behavior, and the run is much smaller than a proper sequence-level training/evaluation study.

The warm-start recovered from the supplied model’s initial harm but did not beat the fresh RGB-only run in this bounded probe. The guide-conditioned scratch run did not show a validation advantage and does not justify adding the current depth/motion tensor to a future portable experiment without a properly trained conditioning contract.

## Export and runtime checks

### Software and regression checks

The isolated environment was:

```text
Python 3.12.10
PyTorch 2.7.1+cu128
CUDA available: yes
GPU: NVIDIA GeForce RTX 5070 Ti
TensorRT: 10.13.3.9
```

The upstream repository’s test suite was run with unittest discovery because `pytest` was not installed:

```text
17 tests passed
```

Those tests validate reconstruction and implementation behavior. They do not establish OpenNR quality, Feature 18 equivalence, live SkyrimVR delivery, headset stability, or VR frame budget.

### ONNX

The supplied checkpoint was exported to an isolated five-input ONNX model:

```text
artifact:    C:\OpenNR\research\dlss5-as-inpainting_20260910_59a414c\research_outputs\dlss5_pytorch_portable_v1.onnx
sha256:      7a6448abea08477c1a80f9fd1a063e56374e754902ae990e65c01902e0c4cdfc
```

ONNX checker and ONNX Runtime CPU comparisons were successful across shapes `64x64`, `256x256`, and `37x53`, including a zero control-mask case. Maximum observed absolute differences were approximately `1.2e-7`; the zero-mask route returned the source exactly. This validates the export path, not the model’s usefulness.

### TensorRT at actual OpenNR color resolution

A fixed-shape FP16-optimized TensorRT engine was built from the portable graph at `2496x2688` color resolution. Its inputs and output remain FP32 at the engine boundary; FP16 is a builder optimization, not a complete end-to-end precision contract.

```text
artifact:       C:\OpenNR\research\dlss5-as-inpainting_20260910_59a414c\research_outputs\portable_color_2496x2688_fp16.engine
sha256:         794fa7358a83e1f21a60a1b8be3a0b4abd963bf390bf867c731a0be572dd7ab6
size:           374,316 bytes
TensorRT:       10.13.3.9
shape:          [1, 3, 2688, 2496]
```

GPU-resident model-only timing on the RTX 5070 Ti:

| Path | Median | p95 | p99 | Peak allocation / other result |
|---|---:|---:|---:|---|
| PyTorch FP16 | 18.07 ms/eye | 22.14 ms/eye | 23.55 ms/eye | 1,794 MiB peak allocated; finite output |
| TensorRT fixed-shape | 7.48 ms/eye | 10.11 ms/eye | 10.53 ms/eye | finite `[0,1]` output; mean abs diff `8.14e-5` vs GPU FP32 PyTorch |

Two sequential TensorRT eyes would be on the order of `14.95 ms` for model execution alone using the measured medians. That is not a stereo-frame result: no two-eye scheduling, preprocessing, depth/motion conversion, guide upload, interop, pack/unpack, compositor, SteamVR, headset, or frame-pacing cost was included. The engine is also fixed-shape and has not been installed into OpenNR.

The earlier isolated `1664x1792` TensorRT result was at the OpenNR guide rectangle, not the actual color rectangle. It is therefore a lower-resolution portability reference and must not be used as the native full-eye runtime claim.

## Why the direct result is negative despite upstream’s synthetic improvement

There is no contradiction between the upstream ten-pair synthetic improvement and the OpenNR regression:

- The upstream checkpoint was trained on ten synthetic/native-like pairs and omitted optional conditions during that distillation run.
- OpenNR has a different image distribution, VR scene content, exposure/color path, teacher behavior, and exact Feature 18-bound guide semantics.
- The upstream portable model is a local residual approximator. It does not have enough capacity or context to recreate OpenNR’s renderer-conditioned, temporal, and stereo behavior.
- OpenNR’s capture artifacts and the upstream native notes use different color/storage contracts. The present comparison is intentionally conservative: identity is the zero-risk baseline on the same OpenNR bytes.

The portable model’s strong sensitivity to nonzero optional channels is itself a warning. On a random 256x256 probe, setting the depth, history, or motion tensors to ones changed the output substantially relative to the RGB-only route. Because those channels were not trained in the supplied checkpoint, the fact that the API accepts them is not evidence that they are semantically usable.

## Recommended future use, if separately authorized

The only evidence-supported follow-up is a narrow, isolated static residual experiment:

1. Fork the architecture into a separately named OpenNR research candidate; retain the upstream checkpoint unchanged.
2. Begin RGB-only. Use exact OpenNR input/teacher pairs with a frozen sequence-level train/validation/test manifest.
3. Keep the identity baseline, upstream supplied-weight baseline, and new model outputs in separate lineage.
4. Select by validation only; report frozen test once; preserve all sequences and exclusions.
5. If guides are later studied, create a new model whose depth, motion, history, masks, resolution mapping, sign, scale, and color contract are explicitly trained and audited. Do not map the current five-channel OpenNR guide cache into the shipped checkpoint by position alone.
6. Require full-eye per-eye warm timing, exact reset-qualified temporal clips, both-eye/stereo checks, visual A/B inspection, and a decomposed end-to-end runtime measurement before any runtime experiment.
7. Do not touch Feature 18, MGO, the active capture profile, or a promoted checkpoint until the candidate beats identity and the current OpenNR baseline on the required quality, temporal, stereo, and VR-budget gates.

This is a useful baseline/scaffold task, not the next production model. The current evidence supports retaining it for comparison while keeping OpenNR’s native teacher and existing semantic/temporal training route authoritative.

## Local project references

- [`README.md`](D:/.CODEX_Projects/OpenNR-VR/README.md) — current OpenNR status and separate quality/runtime acceptance boundaries.
- [`OPENNR_CAPTURE_FORMAT.md`](D:/.CODEX_Projects/OpenNR-VR/docs/OPENNR_CAPTURE_FORMAT.md) — native Feature 18 tap, exact guide artifacts, and strict temporal gate.
- [`build_raw_crop_cache.py`](D:/.CODEX_Projects/OpenNR-VR/tools/build_raw_crop_cache.py) — current RGB/depth/motion cache shapes and conversions.
- Isolated upstream clone: `C:\OpenNR\research\dlss5-as-inpainting_20260910_59a414c`.
