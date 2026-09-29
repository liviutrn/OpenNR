# OpenNR merged face/VGG source-balanced phase — 2026-09-05

This phase tested whether native crop diversity, input-only face guidance, and a small appearance loss could improve the `context_v3` student without changing the captured corpus or the installed Open Shaders runtime.

## Integrity and preparation

- Base cache: `E:\OpenNR_MergedSpatialCache_20260905`
- Base cache schema: 3, row identity `d1a699d0b6b1efad97f3b04d58775ddfe22fc9ffbe306f0caa5dc8816b9d8cca`
- Training eyes: 5,360; validation eyes: 1,196; test eyes: 1,852
- Training sources: 964 older full-resolution eyes and 4,396 new 0.5.3 raw-crop eyes
- YuNet audit: 1,207/5,360 training eyes with a detected face (22.5%); mean confidence 0.9117, median 0.9177; 602 left-eye and 605 right-eye detections
- Audit result: `E:\OpenNR_FaceAudit_Merged_20260905\result.json`
- Audit is input-only and training-only. Validation and test rows were not used for face selection.

The merged corpus mixes 2496×2688 and 512×512 native color rows. `tools/prepare_dynamic_guides.py` now writes one memory-mapped guide tensor per native resolution, and `tools/dynamic_patches.py` selects the correct group per row. The guide cache is:

`E:\OpenNR_DynamicGuides_Merged_20260905`

It contains 4,396 `(5,128,128)` 512² guide entries and 964 `(5,672,624)` 2496×2688 guide entries, all finite float16, with the same base row identity. Raw color paths that already end in `.raw.bin` are now accepted without appending a second `.raw` suffix.

## Face/VGG continuation (uniform row sampling)

Run directory: `E:\OpenNR_Training\context_merged_face_vgg_v3_20260905`

The run initialized from `context_merged_v2_20260905\best_feature.pt` and used dynamic native crops, two face-directed slots per eye, VGG appearance weight 0.05, face-loss weight 0.50, learning rate 1e-5, batch 4, and 12,000 steps. It improved validation (best MAE 0.02130506; best feature distance 0.07683083), but the untouched test regressed:

| candidate | step | test MAE | test PSNR |
| --- | ---: | ---: | ---: |
| parent `context_merged_v2` best-feature | 18,000 | 0.02375495 | 29.34198 |
| face/VGG best-MAE | 11,000 | 0.02395140 | 29.26484 |
| face/VGG best-feature | 12,000 | 0.02396028 | 29.25600 |

This phase is retained as an experiment and is not promoted.

## Source-balanced continuation

Run directory: `E:\OpenNR_Training\context_merged_face_vgg_source_balanced_v4_20260905`

The fixed merged cache contains 7,712 old-source training patches and 4,396 new-source patches (63.6934% old-source). `tools/train_long_student.py` now has `--source-balance`, which deterministically interleaves the two native dynamic pools at that proportion while preserving the existing epoch and face-crop contracts. It was initialized from the parent best-feature checkpoint with VGG weight 0.05 and face-loss weight 0.25. The run was intentionally stopped after step 4,150 once the curve stopped improving; checkpoints already written remain valid.

The leading candidate is `best_feature.pt` at step 4,000:

- full checkpoint SHA-256: `3E0CE6885346E6ADCC10C65775EAA395BA2AFC5AF8B579D11606A5B4E04020D6`
- portable candidate: `OpenNR_ContextMerged_SourceBalanced_v4_best_feature.pt`
- portable SHA-256: `2AC7513B172781C1B4149FB5A81C0FCC8DE4756BF9E9F1E26F0B6AFC30712601`
- architecture: `context_v3`, 1,988,496 parameters

Frozen test result:

| candidate | step | test MAE | test PSNR | old-source MAE | new-source MAE |
| --- | ---: | ---: | ---: | ---: | ---: |
| parent best-feature | 18,000 | 0.02375495 | 29.34198 | 0.02446617 | 0.02274279 |
| source-balanced best-MAE | 1,000 | 0.02365708 | 29.38375 | 0.02430113 | 0.02274050 |
| **source-balanced best-feature** | **4,000** | **0.02358411** | **29.40491** | **0.02424038** | **0.02265014** |

The candidate improves both source subsets in this frozen test, but the visual parent-vs-candidate sheets remain close. Both models still differ from the teacher in dark hair/skin exposure and local microdetail. The candidate is therefore an offline quality/runtime candidate, not a claim of teacher equivalence.

## Runtime checks

TensorRT output:

`E:\OpenNR_Training\context_merged_face_vgg_source_balanced_v4_20260905\trt_fp16_best_feature\student_fp16.engine`

- TensorRT 10.13.3.9, FP16 tactics with FP32 reduction preference and FP32 I/O
- engine SHA-256: `D08B28D70810A6BC6EEB50BBF3F5D37788A9ADEEE362A6ECF38A3257AE6B9A5B`
- PyTorch-vs-engine mean absolute difference: `7.15e-05`; maximum: `0.001943`; left and right checks passed
- GPU-resident TensorRT sequential stereo median: `24.20 ms`
- shared D3D12 replay median: `25.30 ms`, p95 `25.37 ms`
- all six D3D12 input byte checks passed and packed output bytes matched exactly

The same-session parent D3D12 control measured `25.37 ms`, so the observed difference is within normal run-to-run timing noise. The replay includes shared-resource copies, guide/context preparation, TensorRT, packing, and return to graphics, but excludes Skyrim renderer/compositor and headset costs. It is not a live VR acceptance result and is not temporal reconstruction.

## Decision and next gate

Keep the source-balanced best-feature artifact as the leading offline candidate and keep the parent model as the known-good fallback. Do not overwrite or modify the installed `CommunityShaders.dll`; the known-good 0.5.3 OpenNR installation remains outside this training work. Before any live integration, run an isolated engine/model A/B in Skyrim with identical scene, refresh, reprojection, and DLSS/NR settings, then separately check stereo delivery, temporal stability, headset image quality, and VR frame budget.

NVFP4/FP8 is not promoted by this phase. The current evidence supports FP16 TensorRT as the verified runtime reference; low-bit work should follow only after the quality candidate is accepted visually and in-headset.
