# Uruk Neural Renderer audit notes

Audit date: 2026-09-03  
Repository: `jrcedeno/uruk-neural-renderer`  
Public revision: `cff09d4013718dd2b8cbad80ce741c8a4003e8b7`  
Public revision timestamp: `2026-04-07T15:44:40Z`

## Public artifact inventory

The Hugging Face model API reported 26 LFS-backed model files totaling
1,559,421,063 bytes (1.559 GB decimal, 1.452 GiB). The repository metadata
reported zero likes and zero downloads at audit time. The author API exposed
the Uruk model but no separate dataset repository.

Selected LFS objects:

| Artifact | Role | Bytes | LFS object SHA-256 |
|---|---|---:|---|
| `onnx/uruk_v2_ultra_best.onnx` | deployable ONNX student export | 27,702,198 | `6aad072494999c61d1d0675468a343e5689668edb1551736adde19c0e3ae7c31` |
| `v2_ultra/v2_ultra_global_best.pt` | V2-Ultra student checkpoint | 27,721,201 | `6cf56d70e69726de43826cd05c093283e87b411d5de4bd9cea8f774106003c35` |
| `v2_ultra/v2_ultra_best_stage1.pt` | V2-Ultra stage checkpoint | 83,182,045 | `06573415f52fe9ef7ccb7e2286ff952b5782eea01b5ae98910689d8ac97c83e4` |
| `v2_ultra/v2_ultra_best_stage2.pt` | V2-Ultra stage checkpoint | 83,182,045 | `a8c8c60daf441b6b1bb8a74513e151e07b345c7f79dffbfc3b06e764f61e314e` |
| `workstreams/ws5_cinematic_renderer/ws5_frontier_best.pt` | cinematic renderer checkpoint | 121,867,547 | `e14cacf08f1e987917fe95c97e9af9a166441d9f69a21219c52d2b28876b4e96` |
| `workstreams/ws4_world_remapper_v2/ws4_v2_best.pt` | largest selected checkpoint | 271,872,907 | `36bfa289cefab18758f5fb97b2b931aeff2a8856c575e16da4edf5afbc2816e6` |

## ONNX static audit

The public ONNX export was downloaded to a temporary directory and hashed:

`6AAD072494999C61D1D0675468A343E5689668EDB1551736ADDE19C0E3AE7C31`

The graph passed `onnx.checker`, uses ONNX opset 18, was produced by PyTorch
2.12.0, contains 1,079 nodes all in the standard `ai.onnx` operator domain,
230 float32 initializers, and 6,869,027 float32 initializer elements. No
PyTorch checkpoint was deserialized.

Declared inputs:

| Name | Shape | Type |
|---|---|---|
| `gbuffer` | `[batch, 12, height, width]` | float32 |
| `warped_rgb` | `[batch, 3, height, width]` | float32 |
| `occlusion_mask` | `[batch, 1, height, width]` | float32 |
| `prev_state` | `[batch, 16, height, width]` | float32 |

The four inputs total 32 channels. The public model card broadly describes the
12-channel branch as a G-buffer containing material IDs, depth, and normals,
but does not publish the exact channel map, normalization, or ranges.

Declared outputs were `rgb`, `new_state`, `material_probs`, `onnx::Gemm_735`,
and `876`. A synthetic float32 execution with ONNX Runtime CPU succeeded at
32x32 and 48x64. The observed 32x32 output shapes were `[1,3,32,32]`,
`[1,16,32,32]`, `[1,8,32,32]`, `[1,32]`, and `[1,8,32,32]`, respectively.
Repeating the identical 32x32 input produced exact equality for all five
outputs on that single CPU backend. This is a load/determinism smoke only, not
a quality, GPU-latency, TensorRT, or VR acceptance test.

The ONNX output metadata uses malformed symbolic dimension names for
`new_state`, `material_probs`, and the two unnamed auxiliary outputs even
though the bounded runtime smoke returned usable shapes. A defensive consumer
should select outputs by name and assert actual dimensions.

## Evidence boundaries

Verified here: public artifact existence, public file sizes and revision, ONNX
graph structure, bounded CPU loading/execution, and exact repeat behavior for
identical synthetic inputs. Not verified here: material accuracy, perceptual
quality, DLSS 5 superiority, dataset composition, teacher topology, GPU or
TensorRT performance, Skyrim integration, binocular stereo consistency, or
training reproducibility.
