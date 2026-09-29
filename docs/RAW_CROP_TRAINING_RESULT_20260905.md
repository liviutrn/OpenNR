# Raw-crop continuation result — 2026-09-05

The first full training continuation over the new 0.5.3 no-preview capture
completed successfully. The run used the validated raw-only crop cache and
initialized the `ContextStudent` v3 model from the prior balanced
`OpenNR_ContextFaceVGGFaceLoss_v4_best_mae.pt` weights. The cache identity was
explicitly rebound at initialization; future resumes remain identity-strict.

## Run and data contract

| Item | Value |
| --- | --- |
| Capture root | `C:\OpenNR_Captures_Temporal_Crops_0.5.3_NoPreview_20260905` |
| Cache | `E:\OpenNR_RawCropCache_0.5.3_20260905` |
| Cache rows | 6,870 stereo eye rows from 3,435 frames and 111 sequences |
| Split | 70 train / 18 validation / 23 test sequences; 4,396 / 1,108 / 1,366 eye rows |
| Cache rows fingerprint | `2d47b2deb16a3c537a2cabc86d235a6bf7fe075631d100765154b7703053c82a` |
| Candidate manifest fingerprint | `392105c47932860361b01e5da650fc0a0523bd3445ba314ebca6af53439d8f16` |
| Architecture | `context_v3`, width 64, 3 blocks, scale 4 |
| Initialization | `D:\.CODEX_Projects\OpenNR-VR\out\quality_phase_20260905\OpenNR_ContextFaceVGGFaceLoss_v4_best_mae.pt`, parent step 1,000 |
| Schedule | 12,000 steps, batch 4, initial LR `2e-5`, feature weight `0.05`, VGG weight `0.05` |
| Runtime | RTX 5070 Ti, CUDA BF16 autocast, 2,157.29 seconds (35.95 minutes) |
| Test tuning | `false`; the test split was evaluated only after the run completed |

The cache masked 645,524 invalid motion pixels and zero invalid depth values.
The invalid motion values were handled by the documented guide masks and the
resulting tensors were finite. All eight one-frame sequences and the
mid-reset/gapped sequence 59 remain excluded from this candidate. The source
capture and installed runtime DLL were not modified.

## Validation selection

The fixed validation split was evaluated every 1,000 steps. Lower is better.

| Step | MAE | PSNR (dB) | Feature distance | Eye MAE 0 / 1 |
| ---: | ---: | ---: | ---: | ---: |
| 6,000 | 0.0199922 | 30.6606 | 0.0772505 | 0.0197574 / 0.0202270 |
| 8,000 | 0.0200025 | 30.6415 | 0.0763481 | 0.0198072 / 0.0201979 |
| 9,000 | 0.0199223 | 30.6642 | 0.0759922 | 0.0197567 / 0.0200879 |
| **10,000 — best MAE** | **0.0198681** | **30.6832** | 0.0756485 | 0.0196567 / 0.0200796 |
| **11,000 — best feature** | 0.0198857 | 30.6644 | **0.0755031** | 0.0197333 / 0.0200380 |
| 12,000 — last | 0.0199544 | 30.6336 | 0.0756983 | 0.0197723 / 0.0201365 |

The training feature distance is a selection aid, not independent visual
acceptance. Both checkpoints are retained because pixel and feature objectives
do not select exactly the same point.

## Frozen test result

The 23-sequence/1,366-eye-row test split was not used for optimization or
checkpoint selection. It was evaluated once after the run. The input identity
baseline is the same for all candidates (`MAE 0.0322447`); lower model MAE and
higher improvement are better.

| Checkpoint | Step | Test MAE | PSNR (dB) | Improvement vs input | Eye MAE 0 / 1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `best_mae.pt` | 10,000 | 0.0231885 | 29.6200 | 28.09% | 0.0237636 / 0.0226135 |
| `best_feature.pt` | 11,000 | **0.0231750** | **29.6281** | **28.13%** | **0.0237519 / 0.0225981** |
| `last.pt` | 12,000 | 0.0232515 | 29.5935 | 27.89% | 0.0238098 / 0.0226933 |

The feature-selected checkpoint is marginally better on this frozen test
metric, but the difference from the best-MAE checkpoint is small. Keep
`best_mae.pt` as the validation-protocol default and use `best_feature.pt` as
the separate visual/perceptual A/B candidate until a native-eye gallery and
runtime test decide between them.

## Checkpoint evidence

| Artifact | SHA-256 |
| --- | --- |
| `E:\OpenNR_Training\context_raw_crop_v1_20260905\best_mae.pt` | `C6D28700AFBEF17C44508328BF8285C54711C36449B0D9F7CCCE09CC88C88740` |
| `E:\OpenNR_Training\context_raw_crop_v1_20260905\best_feature.pt` | `70B42F65CF7350125BC87B54E8B1EB6EBDD89F79312DCFE6ACD35E922F28AAD0` |
| `E:\OpenNR_Training\context_raw_crop_v1_20260905\last.pt` | `1135F44ABACAFFEC97A5E5AB646F79F77E718A4E14839501232C95CEC8B2BAE7` |

The frozen-test evaluator and result are:

- `tools/evaluate_frozen_raw_crop_test.py`
- `E:\OpenNR_Training\context_raw_crop_v1_20260905\test_evaluation\result.json`

The corrected native-eye benchmark (`tools/evaluate_student.py` now accepts
already-suffixed `.raw.bin` paths) measured both candidates on the RTX 5070 Ti
with CUDA-resident 512×512 inputs:

| Checkpoint | Warm per-eye median / p95 | Warm sequential stereo median / p95 | Warm batched stereo | Peak allocation |
| --- | ---: | ---: | ---: | ---: |
| `best_mae.pt` | 11.36 / 12.00 ms | 20.98 / 22.28 ms | 13.93 ms | 0.132 GiB |
| `best_feature.pt` | 11.80 / 12.49 ms | 21.84 / 22.64 ms | 13.29 ms | 0.132 GiB |

These are model-forward timings only. They exclude raw-guide preparation,
capture interop, engine launch, compositor, display submission, and headset
frame budget. The raw benchmark JSON files are
`E:\OpenNR_Training\context_raw_crop_v1_20260905\benchmark_best_mae.json` and
`benchmark_best_feature.json`.

The completion metadata is in:

- `E:\OpenNR_Training\context_raw_crop_v1_20260905\status.json`
- `E:\OpenNR_Training\context_raw_crop_v1_20260905\run.json`
- `E:\OpenNR_Training\context_raw_crop_v1_20260905\history.jsonl`

## Next gates

1. Generate a broad held-out visual A/B sheet for `best_mae.pt` and
   `best_feature.pt`, including both eyes and changed regions. Choose a visual
   candidate only after checking facial shadow, skin, hair, local contrast, and
   stereo consistency. A first six-sheet direct-view gallery is already at
   `E:\OpenNR_Training\context_raw_crop_v1_20260905\visual_evaluation\dual_gallery`;
   it shows the two students are close to each other and closer to the teacher,
   but still differ in dark-material exposure and local appearance.
2. Benchmark the chosen checkpoint as a CUDA-resident native 512×512 eye and
   sequential stereo pair. Record model-forward timing separately from guide
   preparation, capture, compositor, and headset frame time.
3. Export and validate a TensorRT FP16 engine only after the visual candidate is
   selected. Treat FP8 as a later calibration experiment, not an automatic
   quality upgrade.
4. Collect a small reset-qualified temporal burst with `[true,true]` on its
   first record before claiming recurrent temporal behavior. The current cache
   is spatial/feed-forward evidence only.

These results establish a usable, reproducible spatial student candidate. They
do not establish teacher-equivalent appearance, Feature 18 guide sign/direction
correctness, temporal quality, live SkyrimVR performance, stereo-headset
acceptance, or replacement readiness.
