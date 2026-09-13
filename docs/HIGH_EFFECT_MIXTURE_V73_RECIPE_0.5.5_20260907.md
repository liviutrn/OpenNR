# Superseded old/new mixture recipe — v73 filename retained for provenance

Do not run the v73 output path in this file. Separate v73/v74 specialist
probes were subsequently recorded in the latest project report. The prepared
old/new mixture is now named v75; use
`docs\HIGH_EFFECT_MIXTURE_V75_RECIPE_0.5.5_20260907.md` and its v75 output
directory instead. The rest of this file is retained as the original
preparation record.

Status: prepared only; not started on 2026-09-07 because another Codex task is
using the GPU.

## Objective

Continue from the selected v65 parent while giving the new varied high-effect
domain a controlled specialist share of temporal updates. The old-domain and
new-domain validation splits are evaluated independently and a pixel-weighted
merged metric is used for candidate selection. Both test splits remain frozen
and untouched.

## Immutable inputs

- Parent:
  `E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt`
- Parent SHA-256:
  `5672252B438669169D8B2FED9FFB16F20768270F01D79DC924F32B9318FBC3E3`
- Old temporal cache, NVMe staging copy:
  `E:\OpenNR_TrainingInputs\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906`
- Old temporal cache, cold verified copy:
  `G:\OpenNR_ColdStorage\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906`
- New temporal cache:
  `E:\OpenNR_RawCropCache_VariedHighEffectTemporalClean_0.5.5_20260907`
- Training-only spatial cache:
  `C:\OpenNR_Cache_VariedHighEffectSpatialAllCrops_0.5.5_20260907`
- Output (new directory):
  `E:\OpenNR_Training\high_effect_mixture_v73_probe_0.5.5_20260907`

The old staging copy has 8/8 files and 65.500 GiB with exact size/SHA-256
agreement against G:. The new cache has 28 clean strict sequences, split 17
train / 5 validation / 6 test. The older cache is the established old-domain
corpus; it must not be rebuilt by concatenating raw row files.

## Exact command

Run from `D:\.CODEX_Projects\OpenNR-VR` only after GPU ownership is released:

```powershell
& 'E:\OpenNR-VR-Poc-Venv\Scripts\python.exe' 'tools\train_capacity_temporal_student.py' `
  --initialize 'E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt' `
  --cache 'E:\OpenNR_TrainingInputs\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906' `
  --new-temporal-cache 'E:\OpenNR_RawCropCache_VariedHighEffectTemporalClean_0.5.5_20260907' `
  --new-temporal-prob 0.35 `
  --spatial-cache 'C:\OpenNR_Cache_VariedHighEffectSpatialAllCrops_0.5.5_20260907' `
  --output 'E:\OpenNR_Training\high_effect_mixture_v73_probe_0.5.5_20260907' `
  --steps 1200 `
  --window 8 `
  --burn-in 2 `
  --batch 2 `
  --base-lr 1e-7 `
  --temporal-lr 1e-6 `
  --capacity-lr 2.5e-6 `
  --feature-weight 0.05 `
  --vgg-weight 0.10 `
  --tone-weight 0.10 `
  --effect-power-weight 0.10 `
  --effect-power 4 `
  --identity-weight 0.75 `
  --identity-threshold 0.05 `
  --micro-identity-weight 1.0 `
  --micro-identity-threshold 0.01 `
  --delta-weight 0.12 `
  --spatial-prob 0.25 `
  --capacity-width 128 `
  --capacity-blocks 6 `
  --extra-capacity-width 64 `
  --extra-capacity-blocks 3 `
  --residual-gate `
  --final-gate `
  --delta-scale 0.12 `
  --eval-every 100 `
  --seed 337
```

The capacity arguments intentionally reproduce the selected v65 architecture:
128-wide six-block inherited capacity, a 64-wide three-block extra branch,
residual gate, and final gate. The changed variables are the explicit new
temporal source/probability, the training-only spatial probability, and the
bounded 1,200-step budget.

With `--new-temporal-prob 0.35`, a non-spatial temporal update chooses the new
domain 35% of the time. This is deliberate oversampling: the new cache is only
28 sequences versus 291 old-domain sequences, so naive stream mixing would
give the new domain roughly 8.8% exposure.

## Evaluation gate

Before the run, measure the v65 parent on both frozen test caches and save the
results under distinct output directories. After the run, evaluate
`best_mae.pt`, `best_old_domain.pt`, `best_new_domain.pt`, and `last.pt` on the
same two test caches. Promote only a candidate that improves the intended new
domain without unacceptable old-domain regression and that is also visually
checked against the teacher.

The trainer's validation history is structured as:

```text
validation.old_domain
validation.new_domain
validation.merged
```

`validation.merged.mae` is pixel-weighted by domain. Checkpoint names are
selection aids, not acceptance claims. The `0.011` target is not expected to
be declared achieved unless a frozen test result reaches it and visual
inspection agrees.

If merged validation regresses at two consecutive evaluation points, stop the
run and retain v65. Do not tune against either test split. Keep all produced
checkpoints until the comparison report is written; the output directory is
small relative to the 65.5 GiB cache and can be cleaned later by an explicit,
hash-backed retention decision.

## GPU/storage guard

Expected local peak memory is bounded by the prior v65/v72 batch-2 recipe; do
not increase batch or width in this run. Before launching, confirm no other
GPU owner is active and at least 30 GiB is free on E:. During training monitor
`status.json`, GPU allocation, and C:/E:/G: free space. The active MGO Skyrim
profile and production `CommunityShaders.dll` are not involved in this offline
experiment.
