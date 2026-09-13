# Broad multiscale tone experiment

Training session2200 completed exit0 after all1200steps. Starting validation reproduced parent MAE exactly on all three cohorts. Checkpoint replay and gallery generation launched sequentially afterward; their completion is pending.

Output: `E:\OpenNR_Training\multiscale_tone_broad_20260907`. Fresh identity-initialized103,756-parameter multiscale head over frozen verified seed352 parent. The diagnostic checkpoint is not loaded. Parent SHA2562024593e3ebacb576c2848d0176bc0d8a16bbc35e1250f0dda519937778c5f60.

Recipe matches prior broad tone runs: seed356,1200steps,AdamWlr1e-4,weight decay1e-4,mixture .5/.3/.2,8-frame windows,burn-in2,L1 + .5 pooled16RGB L1 + .12 temporal-error delta. Full64-frame validation at0/400/800/1200 on47/5/2 validation sequences, both eyes. All three MAEs must improve against the starting parent for checkpoint eligibility. Selection then minimizes mean relative cohort MAE; temporal metrics and visual quality are separate acceptance checks. Reused validation data and single seed limit generalization claims.

Starting MAE: prior .01944566017564994; high-effect .017931556953893354; latest .015411405727112045. These exactly reproduce the retained parent. Train/validation use immutable aligned overlays; loader denies test split. No deployment or cloud rental.

After training: reload selected checkpoint, reproduce full validation, inspect temporal metrics, and generate labeled same-scene both-eye sheets against a verified tone control. Renderer now labels multiscale architecture from checkpoint metadata. MAE .011 and facial visual acceptance remain unachieved.

Step400 MAE: prior .01940020039167374; high-effect .017785009167467555; latest .015366557830323776. All improve against the parent and narrowly beat the coarse control at the same step (.01940381104714429 / .017792036733590068 / .01537049348310878). Differences from that control are only a few millionths of MAE. This is an interim numerical result; no substantial visual gain or independent generalization has been demonstrated.

Step800 MAE: .019493076608909282 / .017897330170186857 / .015275151973279813. Step1200 MAE: .019455899919980993 / .017870950900639098 / .015254974229416499. Both later checkpoints regress on prior captures relative to parent and are ineligible under the preexisting all-cohort rule. Step400 remains selected, best mean relative cohort score .9955265164709836. Thus later training improved latest-cohort error at a retention cost; it did not reach .011 or produce a better eligible result.

Post-training pipeline replays the selected checkpoint, then generates `E:\OpenNR_Training\verified_multiscale_tone_gallery_20260907` against the verified coarse control. Completion and image inspection still required.
