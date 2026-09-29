# Full-cohort continuation learning-rate comparison

Purpose: test whether stronger optimization can improve the replicated retention candidate on preserved validation cohorts. No frozen tests. This is motivated by the six-clip fit probe, not a claim that its confounded recipe established learning-rate causality.

Both arms start from E:/OpenNR_Training/aligned_retention_20260907_seed352/best_all_cohorts.pt (verified step400). Fixed seed355,1200 steps, cohort mixture80/15/5, all3.481M weights, window8/burn-in2, batch1, existing L1+.12 temporal+.1 tone loss, augmentation and EMA unchanged. Only initial learning rate differs:1e-6 control versus5e-6 intervention, both cosine-decay to10% of initial rate. Evaluate at0/400/800/1200. Same original-input Arm-C selection baseline and exact split checks; also compare absolute metrics to the retained initialization, not only the older parent.

Outputs E:/OpenNR_Training/retention_lr_control_20260907_seed355 and retention_lr_higher_20260907_seed355. Sequential execution: intervention starts only if control exits successfully. Existing candidates, captures, and caches remain unchanged. No deployment or cloud spend. Full objective remains held-out improvement toward0.011; passing an original-parent gate alone does not establish improvement over retention.

## Control step400

Validation MAE prior/high-effect/latest:0.019288978 /0.018101580 /0.015494987. Compared with retained initialization0.019445660 /0.017931557 /0.015411406, prior improves but both newer cohorts regress. The unchanged selection rule therefore retains step0 as best overall eligible checkpoint so far. This is not a new promoted model. Control training remains live beyond425 in session98643; higher-rate arm remains queued. Do not restart or revise the recipe mid-comparison.

## Control completed; higher-rate arm started

Control finished1200 steps in640.79 seconds. Final MAE0.019359628 /0.018204813 /0.015495696. Selection remains step0: no overall gain over retained initialization. Higher-rate arm automatically started in the same live session98643 after successful control completion. Recorded parent/cohort hashes, seed, sampling, steps, losses, window, burn-in, batch, splits and selection reference match; learning-rate schedules are1e-6 to1e-7 versus5e-6 to5e-7. Do not restart the completed control or infer the higher-rate result before evaluation.

## Completed comparison

Higher-rate step400 MAE0.019172047 /0.018180062 /0.015625918; step8000.019465662 /0.017999714 /0.015552377; step12000.019483868 /0.018111107 /0.015467381. Final higher-rate checkpoint is worse than retained initialization in all three cohorts. Both arms keep step0 under the predefined aggregate selection rule; no candidate promotion. The higher rate initially favors prior retention at the expense of newer cohorts, then loses that prior advantage. This one-seed bounded comparison does not establish that every learning-rate schedule fails, but it does not justify extending this recipe blindly.

The retained seed352 step400 checkpoint remains the verified research candidate. Next investigate a different mechanism: temporal-context mismatch (random eight-frame windows with only two-frame burn-in versus full64-frame evaluation), or training-only error structure/input conditioning. Do not reuse this failed comparison as evidence that capacity is the sole bottleneck. All original models, caches and tests remain unchanged.
