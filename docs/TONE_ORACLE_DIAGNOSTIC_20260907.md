# Target-assisted tone fitting diagnostic

Completed process58240, exit0. Evidence: `E:\OpenNR_Training\tone_oracle_diagnostic_20260907\result.json` and twelve labeled image sheets. This is not a deployable model, validation result, or achievement of MAE .011.

Six existing training sequences: upper-median and maximum training-error sequence from each of three cohorts; both eyes at causal frame32, twelve equally sized512px images. Same frozen verified seed352 parent. Per-image affine coefficient grids fitted directly against teacher RGB, 200 Adam updates, learning rate .03, pure L1. Matrix/bias bounds and interpolation match the learned tone head. No validation/test access.

| Four images per cohort | Parent MAE | Target-fitted 1/16 | Target-fitted 1/4 |
|---|---:|---:|---:|
| Prior | .0314657851 | .0074443607 | .0043280148 |
| High-effect | .0221385024 | .0058339173 | .0041543433 |
| Latest | .0191975678 | .0065141016 | .0046401697 |

Means are across four equally sized images per cohort, not full-sequence validation. All twelve fine-grid fits achieved MAE below .0062. This establishes attainable correction within the parameterization for these images, not whether the inputs contain enough information or whether a shared predictor can learn the mapping. Finite optimization is not a proof of the best possible fit.

Inspected `seq-1788671093778-18-eye0.png`: target-fitted images visibly approach teacher shading in the pictured hair/clothing/background. This image does not establish all requested facial conditions, generalization, or temporal stability. Sheets clearly label target-fitted images NOT MODEL.

## Next diagnostic launched

`tools/train_tone_fit_probe.py` fits one shared quarter-grid50,412-parameter head to the same twelve training images using normal input RGB, frozen parent output, native guides, and context. No teacher is passed as an input; teacher is used only in the L1 training loss. Parent frames must reproduce oracle baseline within1e-7 before training. Seed358,1200steps,lr1e-3,no weight decay,static frame32,no temporal loss. Fresh identity-initialized head; twelve images visited round-robin. Float32 fitting removes mixed-precision arithmetic as a confound in this diagnostic, but also means it is not a matched broad-training comparison.

Output `E:\OpenNR_Training\tone_shared_fit_probe_20260907`, live session55347 at launch. Only `diagnostic_only.pt` may be saved, never promoted. A successful small-set fit would support further work on broad learning/generalization; failure would motivate investigating the shared predictor and optimization. Neither outcome is held-out achievement of .011.

## Shared-head result

Session55347 completed exit0. Mean training-image MAE: step0 .024267285130918026; step200 .023009807026634615; step400 .022805338259786367; step600 .022284974499295156; step800 .021719226303199928; step1000 .022130484925583005; step1200 .021219986646125715. Best saved at1200. This is substantially above the directly fitted coefficient results on the same images. The current shared predictor/optimization recipe has not demonstrated small-set fitting capability near .011. No inference about irreducible error or necessary model size follows from this finite run.

Next investigation should examine shared predictor fitting and scene/spatial context rather than enlarging the coefficient grid again. A multi-scale predictor is a hypothesis to test, not an established fix.

## Shared-head replay and input-range check

Replay session38308 completed exit0. `E:\OpenNR_Training\tone_shared_fit_replay_20260907\verification.json` records exact zero reproduction difference for all twelve images; checkpoint SHA256847b99c944f4db2133e27d4be5f2021f7b79d161c64af1942344cb1e7f3b6899, step1200. Twelve labeled TRAINING FIT ONLY image sheets generated. Inspected `seq-1788740617923-25-eye1.png`: teacher armor/clothing shading remains substantially different from the shared-head fit. Not facial acceptance evidence.

Read-only range check on these twelve frames found all guide/context values finite. Depth-like channel approximately .5605..1; motion channels approximately -.1469...2378; two mask channels constant1 on this selection; context RGB0..1. No extreme input magnitude was observed. This does not validate every capture or establish all channel semantics. No model or cache mutation occurred in this range check.
