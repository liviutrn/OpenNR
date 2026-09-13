# Scratch versus finetune result — 2026-09-10

## Outcome

The controlled scratch comparison is complete. Starting from the existing learned OpenNR representation is decisively better than restarting the OpenNR parent and semantic head from random weights. The finetune arm reached an ordinary renderer-pilot validation MAE of **0.012460920** at step 1600; the identity-safe scratch arm reached **0.016137965**. Neither arm reached the project target of **ordinary 1× MAE ≤ 0.007**, so neither is promoted.

This result supports continuing from the best learned representation. It does not support spending a long blind run on a random scratch model, widening the model again without a data/objective change, or treating this experiment as evidence that the protected production checkpoint has been replaced.

The immutable protected best remains:

- Checkpoint: `C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`
- SHA-256: `40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`
- Protected ordinary renderer-pilot MAE: `0.013283985`

The new finetune checkpoint is an experimental candidate only:

- `C:\OpenNR\Training\semantic_scratch_vs_finetune_20260910\finetune\checkpoint_1600.pt`
- SHA-256: `F1DDABE27DE2BDE99CDD876535575B7B19A0BF3259443C2F3B2F19CBA27DB53C`
- Ordinary renderer-pilot MAE: `0.012460920`

## Question and controlled design

The test was designed to answer one narrow question: does the current teacher-aligned representation provide useful initialization, or could a fresh model learn the same result more effectively from the accumulated corpus?

Both arms used the same:

- exact current `context_v7_capacity_temporal` parent graph;
- semantic/tone head and frozen pretrained DINOv2 encoder;
- seven-cohort train/validation corpus;
- sequence-disjoint validation protocol;
- precomputed temporal-window schedule, seed `909`, window `8`, burn-in `2`, batch `1`;
- pixel-only L1 objective, matching the protected best's recorded objective;
- AdamW setup, head learning rate `1e-4`, parent learning rate `1e-5`;
- 1600 optimizer steps and validation at steps `0, 400, 800, 1200, 1600`.

The seven cohorts were the six retained older cohorts plus `C:\OpenNR\TrainingCache\sparse_full_eye_anchor_crop_clean7_20260909`. The invalid `seq8` motion stream was not admitted. The 18-sequence cache and all protected checkpoints remained controls and were not modified.

The finetune arm loaded the protected best weights and started fresh AdamW state. The scratch arm newly initialized the trainable OpenNR parent and semantic/tone head while keeping only the pretrained DINOv2 encoder. Its zero-output/residual initialization was checked before training: maximum and mean identity error were both `0.0`, and the temporal state was present. This makes the scratch baseline stable and fair rather than an uncontrolled random-pixel baseline.

The complete scratch experiment is under:

`C:\OpenNR\Training\semantic_scratch_vs_finetune_20260910`

The generated schedule digest is `cabc1cf31badd39d8e12d4c080ca9285c9da79b60f4c203d4e06bff70f649a24`; the schedule itself contains `246` new-cohort draws out of `1600` steps, approximately `15%`.

## Validation results

Values below are validation MAE. “Old-six mean” is the unweighted mean of the six older cohorts; `renderer_pilot` is the ordinary 1× target cohort.

| Step | Finetune renderer-pilot | Scratch renderer-pilot | Finetune old-six mean | Scratch old-six mean |
|---:|---:|---:|---:|---:|
| 0 | 0.013283985 | 0.032923446 | 0.017770087 | 0.028786223 |
| 400 | 0.014060967 | 0.022225801 | 0.018256080 | 0.023344223 |
| 800 | 0.013522282 | 0.019899173 | 0.018158672 | 0.021173259 |
| 1200 | 0.012856951 | 0.017877388 | 0.018077886 | 0.020502571 |
| 1600 | **0.012460920** | **0.016137965** | **0.017834069** | **0.020947025** |

At step 1600, finetune is better than scratch by:

- **29.5%** on ordinary renderer-pilot MAE (`0.012460920` versus `0.016137965`);
- **14.9%** on the old-six mean (`0.017834069` versus `0.020947025`).

The finetune arm's step-1600 values by cohort were:

| Cohort | MAE | Temporal delta MAE |
|---|---:|---:|
| prior | 0.0180771156 | — |
| high_effect | 0.0151486746 | — |
| renderer_pilot | **0.0124609198** | **0.0094553486** |
| fresh_session | 0.0142166568 | — |
| renderer_state | 0.0197462384 | 0.0074076556 |
| new_pairs | 0.0273548079 | — |
| full_eye_pilot | 0.0137806501 | 0.0102351903 |

The final finetune stereo split on `renderer_pilot` was left-eye MAE `0.0132286952` and right-eye MAE `0.0116931450`. This is a useful improvement over its step-0 starting point, but it is not evidence of a convincing teacher visual/color match by itself; the visual A/B and live temporal/VR acceptance gates remain separate.

The scratch arm ended at:

- renderer-pilot MAE `0.0161379653`;
- old-six mean `0.0209470246`;
- renderer temporal delta MAE `0.0113518237`;
- full-eye-pilot MAE `0.0186329584`;
- new-pairs MAE `0.0361196097`.

Scratch improved rapidly from the identity baseline, but it did not catch the finetune arm. Its final checkpoint SHA-256 is `909E572738159D5DF2CDC22EE1BB687C6D1439B7009466F26BDC6BF411C9B94B`.

## Gate correction and interpretation

The first trainer version filled the finetune arm's `old_cohorts_not_worse_than_protected` fields by comparing against its own step-0 baseline, because the finetune arm was intentionally not passed a separate protected-reference validation object. That made the finished `finetune/status.json` field `old_broad_gate: true` misleading. The trainer has now been corrected so a missing protected reference produces `null`, and the final gate requires literal `True` values.

Using the actual protected-best validation as the reference, the finetune arm is **not** a broad promotion pass: it improves several ordinary/older cohorts but regresses `renderer_state` slightly and regresses `new_pairs` materially at step 1600. The scratch arm also fails the broad gate. The accurate conclusion is therefore:

> Finetune initialization wins the scratch comparison, but the candidate remains non-promotable because it does not meet the ordinary target and does not preserve every retained cohort.

The original `status.json` files are retained as run artifacts for provenance; this report is the corrected interpretation. Future runs use the corrected trainer logic.

## Engineering and reproducibility notes

An initial 100-step calibration using evaluation batch `4` failed only during the final full-stream cuDNN evaluation with `CUDNN_STATUS_EXECUTION_FAILED`. No nonfinite training loss was observed. The calibration was rerun with evaluation batch `1`, completed for both arms, and established the stable operating point used for the full experiment. The full run also used evaluation batch `1`, peaked at approximately `9.92 GiB` GPU memory, and produced no nonfinite values.

The independent replay helper reloaded both final checkpoints and reproduced the recorded validation metrics exactly: `max_abs_difference = 0.0` and `replay_match = true`. The combined replay summary is:

`C:\OpenNR\Training\semantic_scratch_vs_finetune_20260910\replay\summary.json`

The replay helper now writes arm-specific artifact names to avoid the earlier `checkpoint_1600_replay.json` collision between the two arms.

## Storage and control policy

At completion, C: had approximately **186.4 GiB free**, above the **100 GiB** guard. No old data, caches, controls, or checkpoints were deleted. The two final experimental checkpoints are about `593 MB` each; retaining their histories and replay evidence is inexpensive compared with the risk of losing a reproducibility control. Cleanup remains conditional on storage approaching the guard and must verify that a candidate is not referenced by a report, manifest, or future training plan before removal.

## Decision and next experiment

Do not continue the scratch arm. Do not promote the finetune arm. Continue from `finetune/checkpoint_1600.pt` in a separate recovery experiment with a lower learning rate and a smaller clean7 probability, paired against an old-data-only control. The purpose is to test whether the new cohort's 15% exposure caused the observed `renderer_state`/`new_pairs` regressions and whether a tempered continuation can improve ordinary renderer-pilot MAE without sacrificing the broad corpus.

The next run is intentionally bounded rather than a blind 50,000-step run:

- start from the finetune step-1600 candidate;
- exact same six old cohorts plus clean7;
- paired control and arm with the same old windows;
- arm new-cohort probability `5%`, control `0%`;
- fresh AdamW state at head `5e-5`, parent `5e-6`;
- `800` steps initially, validation every `400`, evaluation batch `1`;
- compare every cohort, renderer temporal delta, full-eye behavior, and visual/color match before extending.

This tests the most plausible recovery lever left by the comparison—less aggressive exposure to the currently mismatched new cohort—without mutating the protected best or confusing extra optimization time with a data effect. The current student target remains open: the best measured ordinary renderer-pilot MAE is `0.012460920`, versus the required `0.007000000`.

`test_used` is `false` for all artifacts in this experiment.
