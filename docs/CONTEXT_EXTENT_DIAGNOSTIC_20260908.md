# Context extent diagnostic

The current strict crop builder constructs the RGB channels of `context.npy` by resizing the captured512x512 input crop to96x96 (`tools/build_raw_crop_cache.py`, `_build_cache`). The aligned renderer builder does the same (`tools/prepare_conditioning_pilot.py`). Consequently, this context does not contain scene information outside the crop, despite older model comments referring to whole-eye context. The teacher is evaluated on an entire eye image. This is a potential missing-input limitation, not proof that context explains the remaining MAE gap.

The older audited spatial master cache `C:/OpenNR/TrainingCache/student_v1` retains true whole-eye96x96 RGB context derived from native2496x2688 input images. Those masters are spatial evidence; they are not strict reset-qualified temporal clips.

## Registered inference diagnostic

Use only the26 primary training sequences from `out/fullres_audit_20260904/training_manifest.jsonl`, first committed eye row and first fixed patch per sequence/eye:52 patches. No validation or test selection. Verify each cached input/teacher patch against its committed raw full-image master and verify stored whole-eye RGB thumbnails by recomputing them from input masters.

Compare the same verified stable U-Net step5600 and frozen parent with two variants: true whole-eye context RGB versus a thumbnail of the current crop. Keep the image patch, native guide tensors, whole-eye context-guide planes and initial student state identical. Only the three context RGB channels change. This isolates RGB context extent at inference; it is not a matched training experiment, not a complete swap to the new crop cache contract, and not temporal or held-out acceptance.

Tool: `tools/diagnose_context_extent.py`. Output: `C:/OpenNR/Training/context_extent_primary_train_20260908`. A positive result would motivate a controlled context-input training study; a negative inference result would not prove global context is uninformative after training. No source captures or existing caches are altered.

## Completed result

All52 selected source patches and whole-eye RGB thumbnails reproduced the cache exactly. Across26 training sequences, mean MAE with true full-eye RGB context was0.0170574854, versus0.0196208764 with crop-thumbnail RGB context. Mean prediction difference between variants was0.0067181897. Thus the true context reduced this training-subset error by about13.1% under the fixed model and guide/context-guide conditions.

This is a meaningful RGB-context sensitivity result and considerably larger than the tiny recent continuation gains. It does not establish held-out generalization, a complete cause for the gap, or the0.011 target. The current new crop recordings do not contain the missing full-eye RGB outside the crop, so that context cannot be reconstructed exactly from those files. Preserve the audited spatial masters for a matched context-training study; do not delete them as obsolete training data.

## Registered held-out diagnostic follow-up

Apply the same fixed comparison to the four primary validation sequences, first eye row and first fixed patch per sequence/eye (eight patches). No fitting or model selection occurs, and no test data is read. This tests whether the direction of the RGB-context effect transfers to a small existing spatial holdout. It still cannot establish temporal or scene-disjoint acceptance and does not compare trained context variants. Output: `C:/OpenNR/Training/context_extent_primary_validation_20260908`.

## Held-out result: training direction did not replicate

All eight source input/teacher patches and global RGB thumbnails verified exactly. Mean validation-patch MAE is0.0336673732 with true full-eye context RGB versus0.0329101463 with crop RGB context: the global variant regresses by0.00075722695. Mean prediction difference between variants is0.0075818694.

The training-set13.1% reduction must not be reported as a general quality improvement. This small spatial holdout does not support simply swapping context thumbnails in the existing model. The result establishes strong context sensitivity with inconsistent error direction; a properly matched training study and adequate scene coverage would still be needed. No model was trained or promoted by this diagnostic, and no runtime or capture setting was changed.

## Capture decision for the active goal

More full-resolution captures may be useful, but the next action should first use the existing full-resolution pilot to train a controlled whole-eye-context arm. The pilot already occupies about117GiB on C: (approximately88.5GiB binary data and28.9GiB PNGs). The training-patch gain did not transfer to the eight-patch holdout, so another large capture is not yet justified by evidence.

A capture sampled one frame every three seconds can support a spatial/global-context study, but it is not a normal temporal burst for the recurrent student. It must remain a separate spatial-context cohort. A temporal cohort requires contiguous frames, both eyes, native full-eye RGB plus the crop, Feature18 teacher output, depth, motion vectors and validity masks, with immutable sequence and split manifests. If a later existing-data study shows held-out benefit, start with an8–12-sequence pilot and reserve storage for derived caches/checkpoints; do not replace the current temporal cohorts or mix sparse snapshots into their 64-frame contract.

## Current semantic-model follow-up

The verified seed812 joint-parent update-1200 checkpoint was evaluated on all 352
patches in the four sequence-disjoint spatial validation sequences. With the
input crop, teacher crop, native guides, context-guide planes and reset state
fixed, replacing only the three RGB context planes with a true whole-eye
thumbnail reduced MAE from `0.026236650` to `0.025728718` (`1.936%`). The
sequence-level direction was positive on three sequences and negative on one.

To test the effect after fitting, two arms started from that same checkpoint and
used an identical deterministic 800-step schedule over the 7,712 training
patches. The full-eye arm ended at validation MAE `0.025302864`; the matched
crop-context arm ended at `0.025424943`, a `0.480%` full-eye advantage. The
advantage remained mixed by sequence (two improved, two regressed), and this was
still an independent spatial reset study, not recurrent temporal acceptance.
The complete paired record is `C:/OpenNR/Training/semantic_context_pair_20260908`;
the read-only diagnostic is
`C:/OpenNR/Training/context_extent_semantic_joint1200_20260908`.

This strengthens the case for measuring global context in a future bounded
full-eye temporal pilot, but does not justify a large sparse capture yet. A
three-second cadence remains spatial evidence, not temporal training data. The
pilot must be separate, contiguous, both-eye, reset-qualified and storage
budgeted before any capture settings are changed.
