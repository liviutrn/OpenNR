# Merged spatial training result — 2026-09-05

The second spatial continuation run trained the current `context_v3` student
against two trusted, provenance-labelled caches: the earlier full-resolution
pilot cache and the new Open Shaders 0.5.3 no-preview crop cache. The source
captures were not modified, the installed `CommunityShaders.dll` was not
modified, and the held-out test partitions from both sources remained frozen
until after training.

This is a stronger spatial candidate than either source-only run, but it is
still not a temporal, live-VR, or teacher-equivalence acceptance result.

## Run and data contract

| Item | Value |
| --- | --- |
| Merged cache | `E:\OpenNR_MergedSpatialCache_20260905` |
| Cache schema | 3 (`merged_compatible_spatial_caches`) |
| Cache rows fingerprint | `d1a699d0b6b1efad97f3b04d58775ddfe22fc9ffbe306f0caa5dc8816b9d8cca` |
| Patches / eye rows | 16,878 patches / 8,408 eye rows |
| Split | 12,108 train / 1,460 validation / 3,310 test patches; 5,360 / 1,196 / 1,852 eye rows |
| Source A | `fullres_20260904`: 10,008 patches, 1,538 rows; 7,712 / 352 / 1,944 patches |
| Source B | `raw_crops_0.5.3_20260905`: 6,870 patches, 6,870 rows; 4,396 / 1,108 / 1,366 patches |
| Architecture | `context_v3`, width 64, 3 blocks, scale 4 |
| Initialization | `E:\OpenNR_Training\context_raw_crop_v1_20260905\best_feature.pt`, cache rebound at initialization only |
| Schedule | 20,000 steps, batch 4, initial LR `1e-5`, feature weight `0.05`, VGG weight `0.05`, workers 0 |
| Runtime | RTX 5070 Ti, CUDA BF16 autocast, 2,891.15 seconds (48.19 minutes) |
| Test tuning | `false` |

The merge preserved each source's existing train/validation/test sequence
split and remapped context row indices. No temporal-invalid stress capture,
duplicate sequence, or known bad geometry source was silently added. The
cache remains spatial/feed-forward evidence only; it has no reset-qualified
contiguous temporal contract.

## Validation selection

Lower is better. The training evaluator selected the two objectives separately.

| Step | MAE | PSNR (dB) | Feature distance | Eye MAE 0 / 1 |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 0.0220069 | 29.8759 | 0.0821625 | 0.0223730 / 0.0216408 |
| 3,000 | 0.0218476 | 29.9312 | 0.0813121 | 0.0222472 / 0.0214480 |
| 6,000 | 0.0217552 | 29.9749 | 0.0806243 | 0.0222130 / 0.0212974 |
| 8,000 | 0.0218107 | 29.9555 | **0.0804909** | 0.0222290 / 0.0213924 |
| 11,000 | 0.0217764 | 29.9633 | 0.0801924 | 0.0223695 / 0.0211834 |
| **13,000 — best MAE** | **0.0217180** | **29.9842** | 0.0802495 | 0.0222241 / 0.0212119 |
| 16,000 | 0.0218084 | 29.9520 | 0.0801395 | 0.0223165 / 0.0213004 |
| **18,000 — best feature** | 0.0217278 | 29.9744 | **0.0800647** | 0.0222146 / 0.0212410 |
| 20,000 — last | 0.0217377 | 29.9725 | 0.0801430 | 0.0222723 / 0.0212031 |

The separate checkpoints are intentional. Pixel and feature objectives do not
select exactly the same iteration, so the files must be evaluated separately
before choosing a visual or runtime candidate.

## Frozen combined test

The 49-sequence/3,310-patch test split was not used during training or
selection. The input identity baseline is the same for all candidates at
`MAE 0.0362991`; lower model MAE and higher improvement are better.

| Checkpoint | Step | Test MAE | PSNR (dB) | Improvement vs input | Eye MAE 0 / 1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `best_mae.pt` | 13,000 | 0.0237598 | 29.3359 | 34.54% | 0.0246882 / 0.0228315 |
| `best_feature.pt` | 18,000 | 0.0237550 | **29.3419** | 34.56% | 0.0246943 / 0.0228157 |
| `last.pt` | 20,000 | **0.0237452** | 29.3415 | **34.58%** | 0.0246676 / 0.0228228 |

The final checkpoint is marginally best on this aggregate numeric test, but
the differences are small. It was not selected automatically because the
training selection protocol retains best-MAE and best-feature candidates.

### Frozen test by source

The evaluator also grouped the held-out patches by their immutable
`cache_source` label. This helps detect a mixed-corpus regression that an
aggregate number could hide.

| Checkpoint | `fullres_20260904` MAE | `raw_crops_0.5.3_20260905` MAE |
| --- | ---: | ---: |
| `best_mae.pt` | 0.0245070 | **0.0226964** |
| `best_feature.pt` | 0.0244661 | 0.0227430 |
| `last.pt` | **0.0244082** | 0.0228018 |

The new 0.5.3 source is the easier held-out domain for this model, while the
older full-resolution source remains the harder domain. The merged run lowers
the new-source test error relative to the earlier raw-only result, but the
domain gap remains visible and needs visual/native validation.

## Visual review

The best-feature test gallery is at:

`E:\OpenNR_Training\context_merged_v2_20260905\visual_evaluation\best_feature_gallery`

The reviewed samples show the student preserving the teacher's broad scene
layout, face/clothing structure, and tone direction. It still differs in
dark-material exposure, skin and hair local contrast, fine surface detail, and
shadow response. The gallery is evidence of progress, not evidence that the
student looks identical to the teacher. Both eyes and multiple held-out frames
must be checked before any runtime promotion.

## Checkpoint evidence

| Artifact | SHA-256 |
| --- | --- |
| `E:\OpenNR_Training\context_merged_v2_20260905\best_mae.pt` | `0B20B91141FA455F87BDAF0673FDCE194CD164F6DE89413F55F1EFEA9ABBB26E` |
| `E:\OpenNR_Training\context_merged_v2_20260905\best_feature.pt` | `085B4BD8305B69AEF8067333E250C7A6A160AE03F628202A9E1F99943BECFEFF` |
| `E:\OpenNR_Training\context_merged_v2_20260905\last.pt` | `6D2273EAE71DCB07A466E1F7DB90C6561B1D49887D5FA784EFD7EC2AB11A8008` |

The frozen test result is:

`E:\OpenNR_Training\context_merged_v2_20260905\test_evaluation\result.json`

The completion metadata is:

- `E:\OpenNR_Training\context_merged_v2_20260905\status.json`
- `E:\OpenNR_Training\context_merged_v2_20260905\run.json`
- `E:\OpenNR_Training\context_merged_v2_20260905\history.jsonl`

## Runtime evidence

The benchmark used CUDA-resident held-out inputs on the RTX 5070 Ti. It is a
model-forward measurement and excludes guide preparation, capture interop,
engine launch, compositor, display submission, and headset frame budget.

| Checkpoint | Warm per-eye median / p95 | Warm sequential stereo median / p95 | Warm batched stereo | Peak allocation |
| --- | ---: | ---: | ---: | ---: |
| `best_mae.pt` | 69.55 / 71.18 ms | 131.97 / 133.33 ms | 141.77 ms | 2.149 GiB |
| `best_feature.pt` | 70.61 / 75.15 ms | 132.18 / 133.20 ms | 141.29 ms | 2.149 GiB |

Benchmark JSON files:

- `E:\OpenNR_Training\context_merged_v2_20260905\benchmark_best_mae_test.json`
- `E:\OpenNR_Training\context_merged_v2_20260905\benchmark_best_feature_test.json`

These timings are far above a usable live stereo-VR budget in their current
form. They are useful for tracking the cost of this larger context model, not
as evidence that it is ready to replace the live OpenNR path. FP8 and TensorRT
should remain separate calibrated experiments after visual selection; the
previous FP8 trials did not establish a quality or speed win.

## Isolated FP16 TensorRT artifacts

After the quality and frozen-test checks, both quality candidates were
exported to fixed-shape native-eye ONNX and built with the existing FP16
TensorRT path. The engine was checked against PyTorch FP32 on both eyes of one
validation stereo pair. Both passed the existing mean error `<= 0.001` and
maximum error `<= 0.05` gates.

| Candidate | Engine | Left mean / max | Right mean / max | Actual sequential stereo median / p95 |
| --- | --- | ---: | ---: | ---: |
| `best_feature.pt` | `trt_fp16_best_feature/student_fp16.engine` | 0.0000698 / 0.00198 | 0.0000637 / 0.00171 | 26.32 / 26.92 ms |
| `best_mae.pt` | `trt_fp16_best_mae/student_fp16.engine` | 0.0000681 / 0.00181 | 0.0000622 / 0.00185 | 26.13 / 27.78 ms |

These are GPU-resident engine timings for the actual validation pair. They
exclude capture, guide preparation, D3D12 interop, compositor, and headset
submission. The engine is FP16 with FP32 I/O and FP32 reduction preference; it
is not NVFP4 or a promoted live runtime.

Portable candidate hashes:

| Artifact | SHA-256 |
| --- | --- |
| `OpenNR_ContextMerged_v2_best_feature.pt` | `305146967BB6D0638E65A02DEC572D37FA76444DB589A514B5A5FF138F24D6F6` |
| `OpenNR_ContextMerged_v2_best_mae.pt` | `70F91DF9ED2F9145A038D097DE741E07FDAB02F44D3E6B8FEC1DB2B48D79988D` |
| `trt_fp16_best_feature/student_fp16.engine` | `92CC6A22F5E6B0DAAFFFED428503B6D93C8D97CBADFBE3FB058DFCA9A474423B` |
| `trt_fp16_best_mae/student_fp16.engine` | `F707ABE32D2E8FE1A435A5165C37AA5B4EBD205FABCEF0F61240C82D0FA0840B` |

The ONNX source hashes are recorded alongside each engine in its
`source.json`; the full numerical results are in each directory's
`runtime_result.json`.

The same two engines then passed the existing shared D3D12 replay harness on
the recorded validation stereo pair. All six input byte checks (RGB, depth,
and motion for both eyes) and the exact output byte check passed.

| Candidate | Wall median / p95 | CUDA median |
| --- | ---: | ---: |
| `best_feature.pt` | 27.38 / 27.90 ms | 27.30 ms |
| `best_mae.pt` | 27.29 / 27.81 ms | 27.20 ms |

Results are in:

- `E:\OpenNR_Training\context_merged_v2_20260905\native_replay_best_feature\result.json`
- `E:\OpenNR_Training\context_merged_v2_20260905\native_replay_best_mae\result.json`

The four-way native replay sheets (recorded input, student via D3D12, native
NVIDIA replay, and captured teacher) are in each candidate's `visual` folder.
For example:

`E:\OpenNR_Training\context_merged_v2_20260905\native_replay_best_feature\visual\replay_detail_eye0.jpg`

This validates the offline resource bridge and its data movement, not live
SkyrimVR scheduling, headset delivery, reprojection, temporal history, or
90-Hz acceptance. At roughly 27 ms per stereo pair, this context model remains
too slow for a 90-Hz VR frame budget before the game renderer and compositor.

## Next gates

1. Compare `best_feature.pt`, `best_mae.pt`, and `last.pt` in a broader native
   eye gallery, with both eyes and a representative dark-material/face subset.
2. Run the two new FP16 engines through the existing D3D12 shared-resource
   replay harness. Keep the current runtime and installed 0.5.3 DLL unchanged
   until that A/B is accepted.
3. Run a calibrated FP8 experiment only as an isolated quality/speed test;
   reject it if it changes appearance or shows no end-to-end benefit.
4. Collect a small reset-qualified temporal burst before making any temporal
   or recurrent-quality claim. The merged cache is intentionally spatial only.
