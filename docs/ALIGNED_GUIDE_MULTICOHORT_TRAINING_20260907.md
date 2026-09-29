# Native-guide alignment and full-model continuation

## Active objective

Continue improving the OpenNR model toward MAE 0.011 using current data and documentation. The previous narrow renderer-refiner experiment is not completion of this objective. Its evaluated test clips remain out of tuning. All work is local; production, public builds, original captures and historical caches remain unchanged.

## Evidence-driven change

The legacy raw crop builder calls `sample_guide` with box `[0,0,512,512]` and source color size `[512,512]` even when native guide and teacher crops cover different regions. Sample metadata has teacher source 2496x2688 and crop (992,1088,512,512), but native source 1664x1792 and crop (576,640,512,512). The teacher crop corresponds to native crop-relative box `(85.3333,85.3333,341.3333,341.3333)`, not the complete native 512-pixel crop.

Training-only reconstruction checks sampled 12 rows from each of the prior and high-effect caches. Twenty raw-accessible samples exactly reproduced saved legacy guide tensors; all twenty differed after correcting only the coordinate box with the same bilinear/strict-valid sampler. Four initially missing samples reference the relocated next-grid capture tree, found at `G:\OpenNR_ColdStorage\OpenNR_RawCaptures_20260907\OpenNR_Captures_NextGridPilot_0.5.5_20260906`.

This confirms a training-input spatial mapping defect, not its effect size on model MAE. Corrected inference may initially regress a model trained on misaligned guides. A controlled continuation is required.

## Correction and isolation

`aligned_native_guides.py` converts the teacher crop to each native guide's coordinates before direct bilinear sampling at 128x128 or 96x96. Motion-vector magnitude/sign conversion remains the existing exact Feature-18 convention. Invalid support uses the existing >0.999 mask criterion. No optical flow substitutes are introduced.

Separate guide/context overlays reference the original RGB arrays without copying or modifying them. All training and validation rows are populated; test rows are left unpopulated and the overlay loader rejects test access. All source guide payloads, original row/completion identities, and generated arrays are hashed. The new pilot overlay also standardizes its earlier BOX-downsampled guides to this direct bilinear contract; this small filter change is disclosed in the comparison.

The analytic pixel-center, invalid-support, coverage-boundary and test-denial tests pass in `tools/test_aligned_native_guides.py`.

## Fixed full-model comparison

- Parent: selected Arm-C `best_mae.pt`, SHA-256 `d644d8fe04efe78df37da46451ae3d665fa96707755131fe999419628bb7cf51`. Full strict initialization; no capacity reset or new width/depth branch.
- Train all existing model parameters, not only the 62k refiner from the prior pilot.
- Cohort sampling: 50% prior merged strict corpus; 30% varied high-effect; 20% latest renderer pilot. Preserve all sequence/eye splits. Renderer channels remain recorded but this experiment changes native depth/MV preparation only; it does not claim to be conditioned-channel training.
- Two arms: original cached guides versus corrected native-guide overlays. Both receive the same RGB/teacher sequences, seed 351, initialization, optimizer/loss, sampling probabilities, and schedule.
- 1,200 steps per arm, batch 1, window 8, burn-in 2, AdamW cosine learning rate 2e-6 to 2e-7, EMA update 0.01, gradient norm cap 1.0.
- Loss: L1 + 0.12 adjacent error-delta L1 + 0.10 pooled-tone L1. This recipe differs from earlier width trials but is identical between these two arms.
- Complete streaming validation on all three cohorts at steps 0, 400, 800 and 1,200. Candidate selection requires all three MAEs to improve their parent baselines, then minimizes mean relative MAE. Also compare absolute results against the original-input parent baseline. No test evaluation or automatic promotion.
- Keep the active goal open unless broad evidence actually supports the target. A failed recipe is evidence for the next action, not a reason to relabel success.

## Paths

Guide overlays: `E:\OpenNR_TrainingInputs\AlignedGuides_AllCohorts_20260907`, `AlignedGuides_HighEffect_20260907`, `AlignedGuides_RendererPilot_20260907`.

Diagnostic evidence: `out/legacy_guide_mapping_audit_same_sampler_20260907.json`.

Trainer: `tools/train_aligned_multicohort.py`; read-only loader: `tools/aligned_cohort.py`; overlay builder: `tools/build_aligned_guide_overlay.py`.

## Live run checkpoint — September 7, 2026, approximately 15:04 local

All three overlays completed. Their populated training/validation eye-row counts are 29,568 prior, 2,816 high-effect, and 1,024 latest pilot (33,408 total). RGB arrays were not duplicated or changed. Original metadata identities and source guide payloads were hashed; output array hashes are in each `complete.json`.

The corrected full-model run is active at `E:\OpenNR_Training\alignment_multicohort_20260907\corrected`. All 3,480,979 existing parameters train. Training includes 184/17/6 sequences in the three cohorts, with 47/5/2 validation sequences. The parent baseline with corrected guides is MAE 0.019748280 / 0.019429492 / 0.019413111, respectively. These starting values do not themselves demonstrate improvement.

The first 50 steps completed with finite loss; logged peak Torch allocation was 6.210 GiB. The existing-guide control is queued after successful completion of the corrected arm in the same live execution session. Each arm is bounded to 1,200 steps and validation at 0/400/800/1,200. A failure stops the queued chain. Read `status.json`, `history.json`, and `selection.json` for current state; do not restart based on stale progress text.

The active MAE 0.011 goal remains incomplete. No frozen tests were read, no cloud resources were rented, and no runtime/public artifacts were changed by this continuation.

## Corrected arm completed — approximately 15:14 local

The corrected arm completed 1,200 steps in 643.11 seconds. Step 400 and 800 failed the all-cohort criterion because the prior mean regressed slightly. Step 1,200 passed against its own corrected-input parent baseline and was saved as `corrected/best_all_cohorts.pt` (SHA-256 `081fa029576010d90998b53c18350eaba790d169a425ed03cb18af1f6cada6e6`).

| Validation cohort | Corrected-input parent MAE | Step 1,200 MAE | Candidate temporal-delta MAE |
|---|---:|---:|---:|
| Prior (47 sequences) | 0.019748280 | 0.019734763 | 0.008491112 |
| High-effect (5 sequences) | 0.019429492 | 0.017683441 | 0.007729436 |
| Latest renderer pilot (2 sequences) | 0.019413111 | 0.015286623 | 0.009993354 |

This is a candidate, not a promotion. The prior gain is only 0.000013517 and its descriptive paired-sequence bootstrap interval crosses zero. Of 47 prior sequences, 26 improve and 21 regress; all five high-effect and both pilot validation sequences improve. These intervals are diagnostic only, not corrected for checkpoint selection or correlated scenes. Sequence-mean and pixel-weighted metric changes reconcile within 1e-8.

The largest prior regressions at earlier checkpoints were next-grid clips 67 and 68. Their input/teacher midpoint sheets show bright, highly textured rock/terrain views, and their teacher control settings match the other audited cohorts. This narrows a potential appearance-preservation issue; it does not authorize excluding these validation clips or moving them into training. The CPU-only sheet is `out/alignment_prior_regression_input_teacher_20260907.png`.

The matched `legacy` arm started automatically in the same live execution session after corrected exited successfully. Do not attribute an improvement to coordinate correction until the matched control and original-input baseline have been compared. Do not restart the active control. Next: finish the control, compare absolute per-cohort and temporal results, reload selected checkpoints for verification, and render fixed broad validation comparisons using `tools/render_alignment_ablation.py`. No frozen tests or further capture are needed for this comparison.

Calculation evidence is saved in `corrected/validation_analysis.json`, generated by `tools/summarize_multicohort_validation.py`. The validation skill informed the sequence-level reconciliation and explicit uncertainty/denominator caveats. The MAE 0.011 objective remains active.

## Completed matched comparison

The existing-guide control also completed 1,200 steps (646.53 seconds). Its best mean checkpoint is step 1,200, SHA-256 `1461b6397153fd09e0657e1b77b0ec2bc6799fc4f31ce62aefad5d28a7211616`. No trained control checkpoint passed all three own-baseline MAE checks.

| Validation cohort | Original-input parent | Trained existing-guide control | Trained corrected-guide candidate |
|---|---:|---:|---:|
| Prior: 47 sequences | 0.019690721 | 0.019696476 | 0.019734763 |
| High-effect: 5 sequences | 0.019369167 | 0.017727330 | 0.017683441 |
| Latest pilot: 2 sequences | 0.019421149 | 0.015918944 | 0.015286623 |

Corrected mapping beats the matched trained control on high-effect and latest MAE, not prior MAE. Relative to the original-input parent, latest MAE improves about 21.3%, but prior worsens about 0.224%. This is not broad target attainment or sufficient promotion evidence. Only one seed was run; latest validation consists of two correlated same-session clips. The legacy control's per-sequence uncertainty is in `legacy/validation_analysis.json`.

Corrected temporal-delta MAE is 0.008491112 / 0.007729436 / 0.009993354, compared with original-input parent 0.008520315 / 0.007934997 / 0.010550665. All three improve against that parent; against the trained control, corrected is slightly worse on high-effect temporal error. These offline metrics do not establish live headset quality or VR frame time.

Fixed first/middle/last validation sequences, both eyes at frame 32 after causal history, are rendered in `E:\OpenNR_Training\alignment_multicohort_20260907\visuals\index.html`. All three PNG sheets were inspected: labels/order are readable, but teacher texture/contrast remains visibly different, particularly face and dark wall details. Images are unenhanced display comparisons, not evidence of exact teacher equivalence. No test images are used here.

### Future-cache regression prevention

`tools/build_raw_crop_cache.py` now uses the shared teacher-region native-coordinate sampler by default for both guide and context arrays. `--legacy-guide-alignment` preserves explicit historical reproduction; generated metadata records the selected mapping. Existing caches are not rewritten. This geometry issue was already described in the historical proof-of-concept documentation, but persisted in the later raw-crop builder.

Four alignment unit tests and the raw-crop helper suite pass. Coverage includes analytic nonunit-resolution coordinates, legacy reproduction, identity mapping at 96/128 sizes, masks, unchanged MV signs, uncovered crops, and denied test-split access. The training recipe was not edited during either run. No game settings, DLLs, public packages, captures, or original caches changed.

Next research priority: preserve prior-cohort appearance while retaining the new-cohort gain, with corrected guides and training-only replay. Do not remove difficult prior validation clips, consume frozen tests for tuning, or request more capture merely to finish this comparison. Keep the existing production parent unchanged.

### Saved-checkpoint verification completed

`tools/verify_alignment_ablation.py` reloaded both selected checkpoints and replayed all 54 validation sequences per model. MAE, PSNR, and temporal-delta MAE reproduced exactly for all six arm/cohort comparisons. Evidence: `E:\OpenNR_Training\alignment_multicohort_20260907\checkpoint_verification.json`. Verification exited successfully; both training arms and their verification/render jobs are finished. The target goal remains unachieved, but this comparison is complete.
