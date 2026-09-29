# Paired semantic-parent replication and duration check

The seed367 joint-parent pilot independently improved MAE and temporal-delta error on all six ordinary cohorts against the verified common start. It beat its matched frozen-parent control on four MAEs and all six temporal errors. Its renderer-state gain against common start is only 0.0000282, and the visual teacher match remains incomplete. This justifies replication and additional measured training, not promotion or a claim that the 0.011 target is near.

## Registered recipe

Use a new seed, 812, and restart both arms from the same verified broad5600 head and seed352 causal parent. Keep pretrained DINOv2 frozen. Compare a frozen-parent control against a trainable-parent arm for 1,200 updates each, with full validation at 0/400/800/1200. The 400-update comparison checks whether the earlier direction repeats; later checkpoints test duration under the same paired design.

Keep six ordinary cohorts, probabilities 0.40/0.15/0.10/0.15/0.10/0.10, head LR 1e-4, parent LR 1e-5 when trainable, AdamW weight decay 1e-4, BF16, eight-frame windows, two burn-in frames, batch1 and the existing L1/pooled/temporal objective. Clip head and parent separately at1. Require exact common-start metrics and identical sample hashes/draws. Preserve all per-cohort MAE and temporal comparisons against common start and same-step control.

Both arms save complete head/parent weights, optimizer and RNG state for a later evidence-led continuation. This experiment is a fresh replication, not a resume or a new architecture. No frozen-test tuning, runtime installation, data deletion or Runpod rental is part of it. The 1,200-update bound is a screening/replication checkpoint, not an assertion of convergence or a final stop for the active goal.

Tool: `tools/train_semantic_parent_replication.py`. Outputs: `C:/OpenNR/Training/semantic_parent_seed812_control1200_20260908` and `C:/OpenNR/Training/semantic_parent_seed812_joint1200_20260908`. The local one-off queue runs the control, joint arm and independent joint endpoint replay in that order.

## Live preparation update

The control completed all 1,200 updates in 939.31 seconds. No checkpoint passed the six-cohort MAE gate. Its final in-process scores are:

| Cohort | Control MAE | Control temporal error |
|---|---:|---:|
| Prior |0.018909262|0.008521860|
| High-effect |0.016167964|0.007779047|
| Older renderer |0.013821953|0.009948506|
| Fresh September7 |0.015181342|0.005377773|
| Renderer-state |0.021030005|0.007575311|
| New19 |0.025623529|0.011059035|

Five MAEs improve from common start, while renderer-state MAE regresses by about4.53%. All six temporal errors worsen. The final control tensor audit confirms all304 parent tensors and175 encoder tensors are unchanged, while all206 original head tensors changed. Control SHA256: `b07c5275f8e424ec9b22390a7b3c35b2b83de19338bf8b8f0d29eae0b39d0abb`. This verifies the frozen-control intervention, not an independently replayed endpoint score.

## Completed joint replication

The joint arm completed 1,200 updates in 1,154.80 seconds. Independent reconstruction reproduced MAE, PSNR and temporal-delta error exactly on all six validation cohorts. Endpoint SHA256: `fa8a2497e0f89c25dada3d1007fbbf7981fe1c9a2fe2f8fb6c5200ec3ab75bb9`.

| Cohort | Joint MAE | Frozen control MAE | Joint temporal error |
|---|---:|---:|---:|
| Prior |0.018172906|0.018909262|0.008304319|
| High-effect |0.015692761|0.016167964|0.007510010|
| Older renderer |0.012689539|0.013821953|0.009565743|
| Fresh September7 |0.014377497|0.015181342|0.005241154|
| Renderer-state |0.020027444|0.021030005|0.007320696|
| New19 |0.028111196|0.025623529|0.010946762|

All six MAEs and temporal errors improve against common start. Five MAEs and all six temporal errors beat the matched control. New19 loses to control by 0.002487667, and its joint MAE also worsens from step800 (0.027195966). The renderer-state common-start MAE gain is small. These are mixed duration results, not promotion. All six MAEs remain above 0.011; convincing visual/color match remains unaccepted. The step800 checkpoint and optimizer were preserved with SHA256 `792d37248ed22a7a015d8732f800f0266d6ad91d99a1763a8f94a9deab9a3521`.

Evidence: `C:/OpenNR/Training/semantic_parent_seed812_joint1200_20260908/independent_replay/result.json`, its `index.html`, and `endpoint_comparison.json`.

Directly inspected fixed sheets: new19 sequence13 left frame64, renderer-state sequence25 left frame32 and fresh-session sequence17 left frame32. The cart remains too dark/less warm; the dark fur scene retains local color differences; the face lacks the teacher's freckles/skin texture and stronger eye-region detail. The facial discrepancy is visibly more than a global color offset. The affine semantic head cannot by itself establish learned high-frequency synthesis; duration of the trainable parent is being tested, but a lower pooled MAE must not be treated as recovery of that texture. No temporal visual or headset acceptance is inferred from these static sheets.

### Fixed-sample color diagnostic

`tools/summarize_replay_color.py` aggregates the existing uncompressed-tensor color metrics by pixel count, separately for each cohort and teacher-change region. It does not derive metrics from JPEGs. Evidence: `fixed_sample_color_summary.json` in the seed812 joint1200 directory, linked by source/report hashes. Eight fixed frames per cohort are represented; these are not full-cohort statistics or semantic face/skin labels.

| Cohort | Signed luma error where teacher brightens | Signed luma error where teacher darkens |
|---|---:|---:|
| Prior |-0.011869|+0.025895|
| High-effect |-0.015427|+0.014562|
| Older renderer |-0.007526|+0.011872|
| Fresh session |-0.041144|+0.026307|
| Renderer-state |-0.005840|+0.051904|
| New19 |-0.019331|+0.036754|

The sign pattern is consistent across these six sample sets: teacher-brightened regions remain too dark and teacher-darkened regions remain too bright. Opposing errors can cancel in overall signed color averages. This supports investigating under-reproduction of local tone changes; it does not prove a specific architectural or objective cause. Any objective intervention should first confirm the pattern on training-only examples, then use a matched control and all-cohort temporal checks. The ongoing duration run remains unchanged.

## Registered duration continuation

Control update2400 completed with canonical-order MAEs0.018586969/0.016073615/0.014061485/0.014545010/0.021003449/0.026622816. Four MAEs improve from control1200, but older-renderer and new19 worsen. Renderer-state remains above common-start MAE, and five temporal errors remain above common start (older renderer is the exception). This is still an unpromoted in-process result; the matched joint continuation has not yet reached this checkpoint. Full metrics remain in the continuation `history.json`.

The resumed control reproduced predecessor MAE, PSNR, temporal-delta error and first-frame MAE exactly on all six cohorts. Its first new checkpoint, update1600, completed with MAEs0.018882392/0.016647020/0.013577628/0.015466497/0.021213883/0.026444782 in canonical cohort order. Only prior and older-renderer MAE improve from control1200; the other four worsen. No all-cohort MAE gate passes. These are in-process validation scores pending matched joint results; the duration experiment continues within its registered4000-update bound. Update1600 weights and optimizer are preserved in `checkpoint_1600.pt`.

Both seed812 endpoints are continuing from update1200 to absolute update4000, with full validation at1200/1600/2400/3200/4000. The initial evaluation must reproduce the predecessor; optimizer, sample schedule and RNG are restored. Learning rates, sequential execution, objective and cohort probabilities remain fixed. Both arms retain every evaluated checkpoint. The newest-cohort regression is explicitly tracked against same-step control and common start; duration is an experiment, not presumed improvement.

The [continuation protocol](SEMANTIC_PARENT_CONTINUATION_PROTOCOL_20260908.md) passes CPU restoration properties and an actual-checkpoint sample-schedule preflight. The one-off queue `tools/run_semantic_continuation_20260908.ps1` launches control, joint and independent endpoint replay sequentially. Outputs use `semantic_parent_seed812_control4000_20260908` and `semantic_parent_seed812_joint4000_20260908` under `C:/OpenNR/Training`. No frozen tests are used. At launch C: had120.11GiB free; no data removal or Runpod spending was needed.

### Duration endpoint assessment

Both continuation arms completed absolute update4000, and the joint endpoint independently replayed exactly. The control's canonical-order MAEs were `0.01892668 / 0.01564961 / 0.01352710 / 0.01486850 / 0.02149543 / 0.02727919`. The joint endpoint was `0.01822377 / 0.01462583 / 0.01268353 / 0.01409771 / 0.02026825 / 0.02927384`. Joint training remains materially better on prior, high-effect, fresh-session and renderer-state, while new19 is worse than both its own update1200 value and the control. Older renderer is slightly better than control but not near0.011. The best all-cohort accepted checkpoint remains joint update1200 (mean ratio0.922719); update3200 has a lower mean ratio but fails the all-cohort retention gate because renderer-state regresses. Independent endpoint replay reproduced all six MAEs, PSNRs and temporal errors exactly.

| Joint update | Prior | High-effect | Older renderer | Fresh session | Renderer-state | New19 | All-six MAE gate |
|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1200 |0.018173|0.015693|0.012690|0.014377|0.020027|0.028111|pass|
| 1600 |0.018081|0.015334|0.012746|0.014699|0.020817|0.027412|fail|
| 2400 |0.017441|0.014829|0.012727|0.014562|0.019893|0.031116|fail|
| 3200 |0.017934|0.014996|0.012297|0.014216|0.020573|0.025273|fail|
| 4000 |0.018224|0.014626|0.012684|0.014098|0.020268|0.029274|fail|

The affine semantic head is therefore not promoted. Fixed-sheet review continues to show local tone and material differences. A new zero-initialized native-resolution residual experiment is registered below from the verified joint update1200 checkpoint.

### Native-resolution semantic residual extension

The residual branch adds a 64-to-48 3x3 convolution, 4x pixel shuffle and bounded0.15*tanh RGB residual after the semantic affine output. Its two new tensors are zero-initialized; a GPU smoke reproduced the verified joint checkpoint output exactly (max absolute difference0), with5.26GiB peak for an eight-frame window. The 60,586,396-parameter intervention begins from `C:/OpenNR/Training/semantic_parent_seed812_joint1200_20260908/last.pt` (SHA256 `fa8a2497e0f89c25dada3d1007fbbf7981fe1c9a2fe2f8fb6c5200ec3ab75bb9`) and restores its optimizer/RNG. The existing joint continuation `semantic_parent_seed812_joint4000_20260908` is the matched schedule/control; the first zero-residual predecessor replay passed with all differences0. The run is `C:/OpenNR/Training/semantic_native_residual_from_joint1200_20260908`, with validation at1600/2000/2400/2800/3200/3600/4000. It uses the original sequential objective and no test data. A residual improvement must beat the matched affine control and retain all cohorts before any extension or promotion.

The residual arm was stopped for assessment after its update2000 checkpoint because it failed the all-cohort retention gate at both evaluated post-start checkpoints. At update1600 its MAEs were `0.018232486 / 0.015532575 / 0.012982224 / 0.014695789 / 0.020692920 / 0.027305414`; at update2000 they were `0.017673206 / 0.015261352 / 0.013158160 / 0.014638737 / 0.020777812 / 0.028464598`. Renderer-state remained above the common-start MAE (ratio1.028579 at1600 and1.032799 at2000), while older renderer also stayed above its affine joint update1200 value. The branch produced some prior/high-effect/new19 gains but broadened the tradeoff rather than improving all cohorts. Its evaluated checkpoints and optimizer states remain preserved: update1600 SHA256 `1a6af0d21999fbce988e746cd2a03d804ff431e236b0d8bcd3c009524fda0c18`, update2000 SHA256 `39ae351cd85a7bc4d0a1c1b5d81167001410e3e0c93d82ec59569d5e207f44fb`. The branch is rejected as a broad output-capacity fix; no runtime or model promotion occurred.

### Tone-change weighted pilot

Because fixed-sample diagnostics showed under-correction in both teacher-brightened and teacher-darkened regions, a matched target-conditioned loss pilot was run from the same joint update1200 checkpoint. Each pixel's RGB L1 term was weighted by `1 + 3*abs(teacher-input luma)`, normalized per frame; pooled RGB L1 and temporal-error terms were unchanged. The target is used only to form the training loss and never enters inference. The predecessor replay was exact across all six cohorts.

At update1600, the weighted pilot produced MAEs `0.018111507 / 0.015240395 / 0.012799247 / 0.014786326 / 0.020962049 / 0.027146777`. It improved high-effect and new19 against the matched affine joint continuation at update1600, but worsened prior, older renderer, fresh session and renderer-state; it failed the all-cohort gate and was not extended. The experiment's best-ratio field remains inherited from the joint start, not a new selected checkpoint. Output: `C:/OpenNR/Training/semantic_toneweighted_from_joint1200_20260908`. This result does not justify using the weighting in the main continuation without another matched recipe.

### Hard-cohort mixture pilot

The renderer-state and new19 cohorts were then given twice their original sampling probability: `0.25/0.10/0.10/0.15/0.20/0.20` versus the original `0.40/0.15/0.10/0.15/0.10/0.10`. Both arms began from the same verified joint update1200 checkpoint, restored optimizer/RNG, and used the unchanged objective and trainable parent. The original-mixture arm was a fresh same-start control; the rebalanced arm intentionally changed only cohort probabilities. Both predecessor replays were exact.

At update1600, original control MAEs were `0.018081392 / 0.015338883 / 0.012743273 / 0.014696015 / 0.020816499 / 0.027410774`. The rebalanced candidate produced `0.018150871 / 0.014704771 / 0.013744613 / 0.014240776 / 0.020174142 / 0.025413541`. It improved new19 by0.001997233 and renderer-state by0.000642357 against the matched control, but worsened prior and older renderer; renderer-state is still just above common-start MAE (ratio1.002792), so the all-cohort gate fails. This is the first intervention to materially improve the hardest cohort without harming temporal error there, and it merits a longer paired continuation before rejection. Outputs: `C:/OpenNR/Training/semantic_mixture_rebalanced_pair_20260908`.
