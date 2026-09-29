# Exact-parent temporal continuation and new capture intake

Registered September 8, 2026. Ordinary 1x MAE <= 0.011 remains the target, together with temporal stability and convincing teacher visual/color match.

## Initialization defect found

The prior `renderer_state_temporal_continuation_freeze_temporal_400_20260908` run requested temporal-only training but rebuilt the saved parent using CLI defaults: width 128, no extra branch, no residual/final gates. The actual seed352 parent has width 192, six blocks, extra width 96 with three blocks, and both gates enabled. The prior run records skipped capacity weight shapes. Its step-zero discrepancy therefore has an architectural confound; it is not adequate evidence that an exact temporal-only continuation fails. Its rejected child remains rejected.

The trainer now offers `--inherit-parent-capacity` and rejects temporal-only runs that change the capacity configuration or request fresh capacity initialization. This leaves deliberate architecture experiments available outside temporal-only mode.

## Registered corrected experiment

Parent: `E:/OpenNR_Training/aligned_retention_20260907_seed352/best_all_cohorts.pt`, SHA256 `2024593e3ebacb576c2848d0176bc0d8a16bbc35e1250f0dda519937778c5f60`.

Cache: `D:/OpenNR_TrainingInputs/RendererStateDistillationStrict_20260908`. Train split only; validation uses complete causal 64-frame streams, both eyes. Frozen test is not used. Native motion validity masks are retained.

Output: `C:/OpenNR/Training/exact_parent_temporal_continuation_20260908`.

Use the same 400 updates, seed 347, batch 2, window 8, burn-in 2, temporal LR 5e-6, temporal delta weight 0.12, feature weight 0.05, VGG weight 0.1 and tone weight 0.1 as the rejected run; spatial sampling stays disabled. Freeze all non-temporal parameters and inherit the entire parent architecture. Use isolated Python 3.12 dependencies at `C:/OpenNR/python312_ml_deps_20260908` (Torch 2.10.0+cu128) for both replay and training.

Before accepting the experiment, require step-zero validation agreement with independently loaded parent replay, no skipped parent weights, and exact inherited parameter identity. Independently replay a useful child; broad prior/new cohort checks and visual/color inspection remain required before promotion. A single-cohort win is insufficient.

## Fresh capture intake

The previously empty `C:/OpenNR_Captures_RendererStatePairs_0.5.7_20260908` now contains 19 clips. All 19 pass the strict metadata/path temporal gate, with 64 complete frames each. Decoded content audit and exact-pair readiness are pending. A folder name or clip count does not establish reset/warm pair identity.

Raw data is preserved. Approximately 136 GiB free on C:, 40 GiB on D:, and 33 GiB on E: at intake. Derived outputs are placed on C:. No cleanup is currently needed and no Runpod spend has occurred in this task.

## Corrected 400-step result

Training completed in approximately 170 seconds with peak allocated GPU memory 5.91 GiB. All 304 initial checkpoint tensors matched the parent exactly, capacity configurations matched, and skipped-parent keys were empty. The intentionally incorrect temporal-only CLI was rejected with the new explanatory error. Independent parent MAE was 0.0201341000437323; in-process step zero was 0.02013399842609134 (difference about 1.02e-7).

At step 400, validation MAE was 0.020105326496478584 and temporal-delta MAE was 0.00758976010832364, compared with step-zero temporal error 0.0075892947804728095. This is a small MAE gain with a slight temporal regression, not a quality-target achievement. Five-cohort independent parent/child replay is in progress in `broad_validation`. The frozen test remains untouched by this experiment.

Runpod read-only checks found no active pods. The catalog lists a community RTX 3090 (24 GB) at $0.22/hour with low availability; exact host suitability and total storage/setup costs are not verified. The billing query reports historical charges, not the remaining credit balance. The user-authorized maximum spend remains $3. Local training currently fits easily, so no rental is necessary.

## Broad replay: not eligible for promotion

| Ordinary cohort | Parent MAE | Corrected child MAE | Child minus parent |
|---|---:|---:|---:|
| Prior | 0.0194456023 | 0.0194323177 | -0.0000132846 |
| High-effect | 0.0179318117 | 0.0179247509 | -0.0000070608 |
| Older renderer | 0.0154116459 | 0.0154382392 | +0.0000265933 |
| Fresh September7 | 0.0159238232 | 0.0159227534 | -0.0000010698 |
| Renderer-state September8 | 0.0201341001 | 0.0201054287 | -0.0000286714 |

The child improves four cohorts but regresses on the older renderer cohort. Temporal changes are tiny: improvements on prior/high-effect/older renderer and slight regressions on the two latest cohorts. No checkpoint is promoted. The rendered six-image validation sheet at `C:/OpenNR/Training/exact_parent_temporal_continuation_20260908/visuals.jpg` still shows missing teacher skin shading, texture, highlights and local color. These crops are not proof of stereo correspondence or runtime acceptance.

The fresh19 content audit finished with19 accepted and0 excluded. The separately built strict cache at `C:/OpenNR/TrainingCache/RendererPairsStrict_20260908` contains2,432 eye rows and12/3/4 train/validation/test sequences. Its source root remains immutable. All19 first frames reset both eyes; a paired folder name does not establish warm/reset evidence.

The next registered independent mechanism is the [native-resolution residual output ablation](NATIVE_RESIDUAL_ABLATION_20260908.md), using ordinary1x cohorts and preserving separate held-out evaluation.
