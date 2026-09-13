# Corrected-guide retention continuation

The completed alignment comparison improves high-effect and latest validation MAE but slightly regresses prior validation against the established original-input parent. This round tests whether additional prior-training replay preserves older appearance without discarding the new-data gains. It does not remove difficult validation sequences or change split membership.

Fixed recipe before execution: initialize from corrected step-1200 best_all_cohorts.pt, train all 3,480,979 parameters for 1,200 steps; seed 352; corrected-guide cohort sampling 80% prior, 15% high-effect, 5% latest. AdamW cosine learning rate 1e-6 to 1e-7. Keep window 8, burn-in 2, batch 1, losses and EMA unchanged. Validate at 0/400/800/1200. This is a continuation, not a matched causal ablation of individual recipe changes.

Selection compares every cohort to the recorded original-input Arm-C baseline from alignment_multicohort_20260907/legacy/baseline.json, with exact validation sequence identity checked. The prior target is therefore 0.019690721, not the slightly worse corrected-guide initialization. No frozen-test access, cloud spend, runtime deployment, capture alteration, or public build changes. A three-cohort gain is only a research gate; MAE 0.011 and broader generalization remain unachieved.

Output: E:/OpenNR_Training/aligned_retention_20260907_seed352. Existing runs/checkpoints stay unchanged. Do not restart a live execution based on a stale status file.

## First validation checkpoint: step 400

The live execution (session 91851) completed its first post-training validation and continued beyond step 500. Prior/high-effect/latest MAE is 0.019445660 / 0.017931557 / 0.015411406. All three beat the original-input Arm-C baseline (0.019690721 / 0.019369167 / 0.019421149), so this checkpoint passes the research selection gate. Prior retention improved while some of the initial candidate's high-effect/latest gain was traded away. This is preliminary single-seed validation evidence, not frozen-test confirmation, production promotion, or achievement of 0.011. Continue the existing run to 1,200 steps without changing the recipe.

## Run completed

All 1,200 steps and validation completed successfully in 650.34 seconds, peak Torch allocation 6.201 GiB. Step 800 MAE was 0.019300204 / 0.018096754 / 0.015472086; step 1,200 was 0.019375005 / 0.018075206 / 0.015370167. All post-training evaluated checkpoints beat the original-input baseline on all three sets.

The prespecified mean-relative-MAE rule among all-cohort improvements selects step 400 (`best_all_cohorts.pt`, score 0.902290067). `best_mean.pt` instead remains the step-zero initialization, which has a slightly better unconstrained aggregate score but fails prior retention; do not confuse it with the selected candidate. No production promotion. Saved-checkpoint verification is a separate post-training run via `verify_alignment_ablation.py --single-run`; check `checkpoint_verification.json` for completion. Training session 91851 has exited successfully and must not be restarted.

## Verification and seed replication

Saved step-400 checkpoint replay completed successfully: MAE, PSNR, and temporal-delta MAE reproduced for every validation cohort (see checkpoint_verification.json). Verification session10509 exited zero.

Next preregistered run: seed353, otherwise identical retention recipe and same corrected pre-retention parent, not the selected seed352 model. Output E:/OpenNR_Training/aligned_retention_20260907_seed353. This checks robustness to stochastic training order; it is not independent capture-session generalization. Keep all 1,200 steps, 0/400/800/1200 evaluation schedule, original-input baseline, 80/15/5 sampling, learning-rate schedule and frozen-test prohibition unchanged. Do not pool checkpoints or select based on frozen tests.

### Seed353 first result

Step400 validation MAE is 0.019470947 prior, 0.018039097 high-effect, 0.015471227 latest. All three improve against the original-input parent, reproducing the direction of seed352's step400 result. This is preliminary replication, not completed-run selection or new-session evidence. Seed353 remains live in execution session48906 and must continue unchanged to step1200. Compared to seed352 at the same step, seed353 is slightly worse in all three metrics; retain both runs and report this variation rather than selecting only the favorable seed.

### Seed353 completed

Session48906 exited zero after all1200 steps and evaluations in639.22 seconds. Step800 MAE:0.019426730 /0.018139608 /0.015489083. Step1200 MAE:0.019369114 /0.018172233 /0.015591685. The unchanged all-cohort selection rule keeps step400, score0.905595569. Both seeds independently select step400 and improve all three cohorts over the original parent. Neither establishes target0.011 or independent-session generalization. Post-training checkpoint replay is running in session61772; do not restart completed training. Next: finish verification, render the two selected models, then diagnose remaining training-fit versus generalization error before choosing a materially different experiment.

### Both checkpoints verified and visual comparison completed

Seed353 verification session61772 exited zero and reproduced all three saved validation metrics (MAE, PSNR, temporal delta) per cohort. Both selected checkpoints are now verified. Render session6370 also exited zero. Gallery: E:/OpenNR_Training/retention_comparison_20260907/index.html, generated by tools/render_retention_comparison.py. The renderer checks verified checkpoint hashes and uses fixed first/middle/last validation sequences, both eyes, with causal history through frame32. All three sheets were visually inspected; labels are readable and no test examples or display enhancement are used. The seeds look similar in these examples; teacher skin texture and local contrast differences remain. This is still offline evidence, not live VR acceptance.

### Training-fit diagnostic launched

tools/evaluate_retention_training_fit.py replays all184/17/6 training sequences from the verified seed352 step400 checkpoint using the same causal evaluator as validation. Output E:/OpenNR_Training/retention_training_fit_20260907; live session43606. Exact checkpoint hash and training membership are checked. No optimizer or frozen-test access. Results are training-fit diagnostics, not held-out success. Train/validation scene distributions differ, so the aggregate gap alone cannot distinguish overfitting from scene difficulty or establish a capacity ceiling. Inspect full per-sequence results before choosing the next experiment.

### Training-fit replay completed

Session43606 exited zero. All207 training sequences were evaluated, without optimization or frozen-test access. Prior train/validation MAE:0.018085640 /0.019445660; high-effect:0.018040650 /0.017931557; latest:0.015125456 /0.015411406. Full metrics and per-sequence values are in E:/OpenNR_Training/retention_training_fit_20260907/result.json. Training error remains materially above0.011 in all cohorts. This rules out the simple description that this selected model already fits its training data near the target and only fails validation; it does not isolate optimization, input-information limitations, temporal-window mismatch, or model capacity. Cohort scene distributions differ and validation selection is adaptive.

Next diagnostic should inspect training-only error distribution and test bounded fitting of a fixed training subset before committing to a larger model or more collection. Any overfit probe is explicitly a mechanism diagnostic, not a generalizable candidate or evidence of held-out target attainment. Preserve original split identities and all captured data.
