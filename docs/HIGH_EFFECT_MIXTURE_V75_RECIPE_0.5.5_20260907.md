# High-effect old/new mixture recipe — v75 preparation

Status: prepared, not started. The v73 and v74 names are already used by
separate specialist probes recorded in the latest project report, so this
parent-preserving old/new mixture uses v75.

## Inputs and safeguards

- Parent:
  `E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt`
- Parent SHA-256:
  `5672252B438669169D8B2FED9FFB16F20768270F01D79DC924F32B9318FBC3E3`
- Old temporal cache:
  `E:\OpenNR_TrainingInputs\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906`
- New temporal cache:
  `E:\OpenNR_RawCropCache_VariedHighEffectTemporalClean_0.5.5_20260907`
- Spatial cache:
  `C:\OpenNR_Cache_VariedHighEffectSpatialAllCrops_0.5.5_20260907`
- Output:
  `E:\OpenNR_Training\high_effect_mixture_v75_probe_0.5.5_20260907`

The old cache is the SHA-256-verified E: staging copy of the intact G: cold
archive. The new cache has 17 train / 5 validation / 6 frozen test sequences.
The trainer reports old-domain, new-domain, and pixel-weighted merged
validation separately. No test split is used for selection.

## Command to run only after GPU ownership is released

Run from `D:\.CODEX_Projects\OpenNR-VR`:

```powershell
& 'E:\OpenNR-VR-Poc-Venv\Scripts\python.exe' 'tools\train_capacity_temporal_student.py' `
  --initialize 'E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt' `
  --cache 'E:\OpenNR_TrainingInputs\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906' `
  --new-temporal-cache 'E:\OpenNR_RawCropCache_VariedHighEffectTemporalClean_0.5.5_20260907' `
  --new-temporal-prob 0.35 `
  --spatial-cache 'C:\OpenNR_Cache_VariedHighEffectSpatialAllCrops_0.5.5_20260907' `
  --output 'E:\OpenNR_Training\high_effect_mixture_v75_probe_0.5.5_20260907' `
  --steps 1200 --window 8 --burn-in 2 --batch 2 `
  --base-lr 1e-7 --temporal-lr 1e-6 --capacity-lr 2.5e-6 `
  --feature-weight 0.05 --vgg-weight 0.10 --tone-weight 0.10 `
  --effect-power-weight 0.10 --effect-power 4 `
  --identity-weight 0.75 --identity-threshold 0.05 `
  --micro-identity-weight 1.0 --micro-identity-threshold 0.01 `
  --delta-weight 0.12 --spatial-prob 0.25 `
  --capacity-width 128 --capacity-blocks 6 `
  --extra-capacity-width 64 --extra-capacity-blocks 3 `
  --residual-gate --final-gate --delta-scale 0.12 `
  --eval-every 100 --seed 337
```

The capacity settings reproduce v65: inherited width 128 / 6 blocks, extra
width 64 / 3 blocks, residual gate, and final gate. The intended change is the
explicit new-domain sampler. At 0.35, new temporal streams are deliberately
oversampled relative to their roughly 9% share under naive old/new mixing.

## Evaluation and stop rule

Before running, evaluate v65 on the old and new frozen test splits. Afterward,
evaluate `best_mae.pt`, `best_old_domain.pt`, `best_new_domain.pt`, and
`last.pt` on both tests and render an A/B gallery against the teacher. Stop if
merged validation regresses at two consecutive evaluation points. Do not
promote or install a candidate based on training loss alone. The `0.011` goal
is not achieved unless a frozen test result reaches it and visual validation
agrees.

Keep batch 2 and this capacity fixed on the local 16-GiB GPU. Monitor E: free
space and `status.json`; do not launch while another Codex task owns the GPU.
