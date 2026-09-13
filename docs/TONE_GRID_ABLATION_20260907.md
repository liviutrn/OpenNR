# Local tone-grid resolution ablation

Status: training session 69413 and verification/gallery session 84699 completed successfully. Both selected step400 checkpoints reproduced all three validation cohorts. Matched comparison and both-eye gallery completed. No clear grid-resolution benefit or facial visual acceptance established.

User acceptance targets are stronger nose/cheek highlights, more realistic skin color, and deeper mouth/hood/under-eye shading. Prior local/global affine heads produced only small validation changes and did not establish visual acceptance.

Compare fresh 1/16 and 1/4 coefficient-grid arms with the same frozen verified seed352 parent, seed356, 50,412 trainable head parameters, 1,200 steps, learning rate 1e-4, cohort mixture .5/.3/.2, eight-frame windows with two-frame burn-in, and identical L1 + .5 pooled16 RGB L1 + .12 temporal-error loss. At 512px, coefficient grids are 32x32 and 128x128. Fine-grid activation work increases; parameter count does not. This is a grid-configuration ablation: fixed convolution dilations mean the full-image receptive field also changes, so it does not isolate interpolation precision alone.

Use existing immutable aligned train/validation overlays. No frozen-test access, cloud rental, runtime changes, or deployment. Keep original parent feedback unmodified. Preserve the original tone-head module and checkpoint source hash; new resolution module is hashed separately. Existing verified tone checkpoint reload passed after backward-compatible loader changes.

Five unit tests passed, including exact nonzero coarse-grid equivalence, matched parameter count, identity initialization, gradients, frozen-parent/state contract, and bounded output. Native-512 CUDA fine-head backward smoke passed. Smoke allocation is not full training VRAM or runtime-performance evidence.

Outputs:
- `E:\OpenNR_Training\tone_grid_coarse_20260907`
- `E:\OpenNR_Training\tone_grid_fine_20260907`

Before accepting a candidate: finish both arms; reload selected checkpoints and reproduce all three complete validation cohorts; compare temporal errors; create same-scene, both-eye visual sheets without exposure adjustment. Small MAE gains alone do not satisfy facial appearance targets. No claim of achieving MAE .011.

## Interim evidence

The fresh coarse control's step0 exactly reproduced the parent MAE on all three cohorts. Step400 MAE is prior .01940381104714429, high-effect .017792036733590068, latest .01537049348310878. This is a small improvement over the parent, close to the earlier coarse-head result, not evidence of a fine-grid benefit. The fine arm has not yet produced results. Reload verification and visual acceptance remain pending.

Coarse control completion: step800 MAE .019468676611774514 / .017909245903138072 / .015331607855235537 regressed on prior data relative to the parent, despite improving latest data. Step1200 MAE .01943991774179583 / .01791847075801343 / .015352958696894348. Best eligible mean relative MAE score is .9958041706419628, from step400. More coarse-head steps did not yield a better eligible three-cohort result.

Fine-grid step0 reproduced the parent exactly. Step400 MAE is .019401354412630807 / .017794859774100284 / .015378673599722484. Against the same-step coarse control this is slightly better on prior data and slightly worse on the other two cohorts. No clear finer-grid advantage is established; final comparison, reload verification, and visual inspection remain pending.

Fine-grid completion: step800 MAE .019445700392602606 / .017895777162630112 / .01537417562212795; step1200 MAE .019424574431494302 / .01790510779246688 / .015382034529466182. Training process exited0. Post-training checks target `tone_grid_comparison_20260907.json` and `verified_tone_grid_gallery_20260907` under `E:\OpenNR_Training`; neither artifact is considered complete until its generating process succeeds and the result is inspected. These results do not establish a substantial gain toward .011 or facial visual acceptance.

`tools/compare_tone_grid.py` prepares same-step comparisons of MAE, temporal error, and counts of improved sequences. It requires completed runs, matching recorded configurations except grid resolution, matching validation sequence identities, equivalent initial baselines, and verified checkpoint hashes. Its incomplete-run rejection check passed; full successful execution must wait for both completed and reloaded arms. Comparison uses no dataset or test access. The validation skill informed these comparability and claim-scope checks. Image labels are now derived from each checkpoint's grid metadata.

## Verified outcome and next diagnostic

The full comparison succeeded at `E:\OpenNR_Training\tone_grid_comparison_20260907.json`. Both selected step400. Fine versus coarse MAE changes are -0.01266% prior, +0.01587% high-effect, +0.05322% latest; mixed and negligible in this experiment. These are single-seed results on repeatedly used validation cohorts, not independent generalization.

Gallery: `E:\OpenNR_Training\verified_tone_grid_gallery_20260907\index.html`. Inspected `seq-1788671399304-47-eye0.png` and `seq-1788705227244-60-eye1.png`: fine and coarse are visually nearly identical; teacher facial shading/texture remains different. These examples do not cover all requested hood/mouth conditions. No promotion or deployment.

Next diagnostic implemented in `tools/diagnose_tone_oracle.py`: directly fit bounded affine coefficient grids to teacher targets on six training sequences, both eyes, causal frame32. Select upper-median and maximum training-error sequence per cohort, same as the prior fit probe. This is TARGET-ASSISTED, not a learned inference model. It tests attainable correction on these images; a low error does not prove predictability, and a high finite-optimization error does not prove a representation ceiling. Identity, bounds, and reachable-brightening smoke checks passed. Output target `E:\OpenNR_Training\tone_oracle_diagnostic_20260907`. No validation/test access or deployable checkpoint is produced.
