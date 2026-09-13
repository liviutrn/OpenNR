# Native-resolution residual output: registered matched experiment

The ordinary 1x MAE <= 0.011 and teacher visual/color/temporal targets remain unmet. The corrected temporal-only continuation improved four ordinary cohorts slightly but regressed on the older renderer cohort. Its gallery still shows missing teacher skin texture, material shading and local color.

## Hypothesis and comparison

The current 38M stable U-Net generates twelve affine coefficients on a quarter-resolution grid and interpolates them to the delivered image. This experiment adds a 64-to-48 3x3 convolution followed by 4x pixel shuffle and a bounded 0.15*tanh RGB residual. It can express native-pixel corrections that are not restricted to interpolated affine coefficients. This is an output-capacity hypothesis, not an established bottleneck.

Both arms begin from the verified ordinary stable U-Net step5600 checkpoint `E:/OpenNR_Training/stable_unet_broad_20260907/best_all_cohorts.pt`, SHA256 `e240963bdf7d6cb61cafb0cc0445757af4c661b91e57217d5ef031b06c57c962`. They preserve its exact frozen causal parent. The control continues the affine-only head; the intervention adds a zero-initialized native residual. All head weights train in both arms. Renderer feature inputs and two-pass labels are not introduced, so the comparison isolates output formulation on ordinary 1x data.

GPU smoke at 512x512 verified bitwise-identical BF16 initial outputs (maximum difference 0), a nonzero gradient to the added residual weights, and 38,505,180 intervention parameters. This smoke is not full-run memory or validation evidence.

## Fixed recipe

- Six ordinary cohorts: prior, high-effect, older renderer, fresh September7 session, September8 renderer-state tranche, and the 19 new September8 clips.
- Cohort sampling probabilities: 0.40 / 0.15 / 0.10 / 0.15 / 0.10 / 0.10; uniform sequence sampling inside each cohort.
- Immutable sequence splits; 19 new clips use 12 train / 3 validation / 4 test. Test pixels never enter training, model selection, or this evaluation.
- Both arms: seed367, 400 updates, batch1, eight-frame windows, two burn-in frames, AdamW LR1e-4, weight decay1e-4, gradient clipping1.
- Loss: RGB L1 + 0.5 pooled16 RGB L1 + 0.12 adjacent prediction-error delta L1. BF16 inference/training; identical sample hashes and cohort draw counts are required.
- Full64-frame validation, both eyes, at0 and400. Initial metrics must match control within1e-7. Select an eligible checkpoint only when every ordinary cohort improves over common start. Compare the intervention against the matched control separately.

The initial matched pilot is bounded at400 updates. Extend only if its fitting/validation/visual evidence supports the direction. Native pixel shuffle can introduce checkerboard or temporal artifacts; inspect these directly before any promotion. No runtime or headset acceptance is implied by offline results.

Outputs: `C:/OpenNR/Training/native_residual_control400_20260908` and `C:/OpenNR/Training/native_residual_arm400_20260908`. Training tools save source/checkpoint/cache hashes, full validation results, sample hashes and experimental selections. No Runpod rental is needed for the smoke; full pilot memory remains to be measured.

## Live baseline and intake evidence

The matched control baseline is complete. MAE across prior/high-effect/older renderer/freshSeptember7/renderer-stateSeptember8/new19 is `0.019231266 / 0.017656344 / 0.014859464 / 0.016249614 / 0.020117967 / 0.029031637`. The new tranche is a substantially harder held-out face/material cohort for the existing warm model; its score must remain visible rather than being hidden in a pooled mean. This observation does not prove an irreducible error floor.

The control is training with measured peak allocated GPU memory4.29GiB. No cloud spend is needed.

Raw-current-RGB pair preflight on the new tranche examined1,920 non-test input eye rows (30 reset,1,890 warm) and skipped512 frozen-test rows. It found0 reset/warm groups with identical raw input RGB. Exact guide/renderer equality therefore cannot rescue any state pair in this tranche. The new clips remain ordinary temporal data. Evidence: `C:/OpenNR/Training/renderer_pairs_input_identity_preflight_20260908.json`.

A storage triage found approximately13.88GiB in the older renderer-state conditioning pilot and4.13GiB in the earlier refiner pilot, mainly regenerable intermediate artifacts. These are review candidates only; nothing has been deleted. Current training/checkpoints/raw captures and active immutable caches are preserved.

## Affine control completed; native arm started

The affine control completed400 updates in455.78 seconds. Endpoint MAE is `0.019599605 / 0.018175676 / 0.014999369 / 0.016064542 / 0.020555652 / 0.028933905` across the six registered cohorts. Only freshSeptember7 and the new19 improve over common start; the control retains step0 under the all-cohort gate. This is a control result, not evidence about the native residual intervention. The matched native arm was then launched without changing its registered recipe.

The strict new19 cache reports0 invalid depth values and5,841 invalid motion values, retained through validity masks. Across all six ordinary cohorts, every non-test row has identical recorded teacher settings (style0, intensity2, local structure2, local tone2, skin structure-1, auto-mask true, UI correction false). This rules out mixed recorded artistic controls as an explanation for this comparison; it does not prove that all hidden runtime state is identical.

## Completed matched result: reject the native residual endpoint

All six initial MAE/PSNR/temporal values match the control exactly. The400-step sample hashes and cohort draws also match (151/64/34/66/42/43). The native arm completed in379.70 seconds at4.29GiB peak allocated GPU memory.

| Ordinary cohort | Affine control MAE | Native residual MAE | Native minus control |
|---|---:|---:|---:|
| Prior |0.019599605|0.019686094|+0.000086489|
| High-effect |0.018175676|0.018271910|+0.000096234|
| Older renderer |0.014999369|0.015034985|+0.000035615|
| Fresh September7 |0.016064542|0.016095581|+0.000031039|
| Renderer-state September8 |0.020555652|0.020745367|+0.000189715|
| New19 September8 |0.028933905|0.029038057|+0.000104152|

The intervention regresses on every MAE cohort against its matched control and fails the common-start gate. Both arms retain step0. Temporal results trade off across cohorts and do not rescue the failed RGB result. The native endpoint was independently replayed on all six cohorts with differences within1e-7; fixed frame32/64 samples and signed RGB/luma diagnostics were written under `C:/OpenNR/Training/native_residual_arm400_20260908/independent_replay`. No test was used and no checkpoint was promoted. Do not extend this output experiment from this evidence.

Next evidence: the [context extent diagnostic](CONTEXT_EXTENT_DIAGNOSTIC_20260908.md) and the independently registered [frozen semantic-feature comparison](SEMANTIC_FEATURE_ABLATION_20260908.md).
