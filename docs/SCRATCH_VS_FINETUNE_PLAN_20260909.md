# Scratch initialization versus protected-best fine-tune — plan — 2026-09-09

## Decision question

Does a newly initialized OpenNR student trained on the audited corpus learn a
better ordinary 1x teacher match than continuing the protected best model, or
is the existing learned representation materially valuable?

This is an initialization experiment. It is not a license to replace the
active best, consume the frozen test split during tuning, or treat a lower
training loss as a quality improvement.

## Current reference

The protected best remains:

`C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`

Its current semantic-joint family is the completed wide parent configuration:

- causal capacity parent: width `192`, six main blocks, extra width `96`,
  three extra blocks, with the inherited residual/final gates;
- trainable parent parameters: `3,480,979`;
- trainable semantic/tone head parameters: `38,502,124`;
- frozen pretrained DINOv2 encoder parameters: approximately `22.06M`;
- total serialized model parameters: approximately `64.04M`;
- current protected renderer-pilot validation MAE: approximately `0.013284`;
- ordinary target: MAE `<= 0.007`.

The current long sparse-anchor continuation is a separate same-architecture
optimization study. It must finish and be recorded before the scratch run is
interpreted; it is not the scratch comparator.

## Primary arms

### S — identity-safe scratch student

Construct the exact current graph from its recorded `base_config`,
`temporal_config`, and `capacity_config`, but do not load the learned parent or
semantic head weights. Keep only the pretrained DINOv2 encoder and its exact
source/checkpoint provenance frozen. Randomly initialize all trainable parent
and semantic-head weights using a recorded seed.

Because the OpenNR graph is residual, the output heads and residual/gate heads
remain zero-initialized as an architectural stability contract. This is still
a scratch model: no learned OpenNR parent/head tensor is copied. The
zero-output initialization makes the initial function an RGB identity instead
of producing an uncontrolled random image, allowing the experiment to measure
learning rather than startup garbage.

### F — matched protected-best fine-tune

Use the protected best weights as the initialization, with the same exact
architecture, same fresh optimizer convention, same seed-controlled sample
schedule, same data, and same step/evaluation budget as S. A separate metadata
field will identify whether the optimizer is fresh or restored; the primary
scratch comparison uses a fresh optimizer so the weight-initialization effect
is not hidden by old Adam moments.

The already-running restored-optimizer continuation remains a useful secondary
reference for the practical production path, but it is not substituted for F
when judging the causal scratch question.

## Corpus and split contract

The primary parity corpus consists of the six cohorts that produced the
protected best plus the audited clean-7 sparse full-eye-anchor cache:

1. `E:\OpenNR_TrainingInputs\AlignedGuides_AllCohorts_20260907`
2. `E:\OpenNR_TrainingInputs\AlignedGuides_HighEffect_20260907`
3. `E:\OpenNR_TrainingInputs\AlignedGuides_RendererPilot_20260907`
4. `E:\OpenNR_TrainingInputs\RendererConditioningFreshSession_20260907_2114`
5. `D:\OpenNR_TrainingInputs\RendererStateDistillationStrict_20260908`
6. `C:\OpenNR\TrainingCache\RendererPairsStrict_20260908`
7. `C:\OpenNR\TrainingCache\sparse_full_eye_anchor_crop_clean7_20260909`

The clean-7 cache is the 7-sequence, 448-frame, 896-eye-row cache derived
from the sparse-anchor tranche. The motion-invalid eighth sequence,
`seq-1789007322591-8`, is excluded from training and remains preserved for
diagnostics. The 18-sequence cache remains an immutable historical control; it
will not be silently appended to this parity experiment. If it is tested later,
both S and F must receive the same explicitly named train split and a new
manifest.

Training uses only sequence-disjoint train rows. Validation is the existing
sequence-disjoint validation rows for all seven cohorts. Test rows remain
unread until validation selection is frozen. Raw capture roots are never loaded
directly by the trainer.

The primary schedule keeps the old six cohort probabilities used by the
protected model and replaces a predeclared `15%` of old draws with clean-7
draws, matching the current sparse-anchor arm. S and F receive the identical
serialized schedule and sample digest.

## Training stages

The run is staged so that a poor scratch trajectory is informative without
turning into a blind long fit:

1. Build the scratch/F manifest and run/cache identity records. Verify all
   source hashes, parameter counts, finite tensors, and test exclusion.
2. Run a short 50–100-update CUDA calibration for S. Check identity-safe
   initialization, loss finiteness, gradient reachability, peak VRAM, and
   checkpoint reload equivalence.
3. Run S and F with the same 400-step evaluation cadence to an initial
   absolute budget of 1,600 updates. Save every evaluation checkpoint and
   evaluate all seven validation cohorts, per-eye values, temporal-delta MAE,
   first/steady-frame MAE, and training exposure counts.
4. Extend only if the validation curves remain meaningfully improving. The
   next staged budget is 3,200, then at most 8,000 for this first scratch
   study. There will be no unmonitored 50,000-step run.
5. Independently reload and replay any checkpoint that clears the broad
   validation gate. Only after selection is frozen may one frozen-test replay
   be performed.

The local RTX 5070 Ti is the default because the current graph already fits
within its measured training VRAM. Runpod remains a contingency for a failed
local calibration or a deliberately larger graph; no cloud rental is needed
for the primary scratch test and the remaining credit is preserved.

## Acceptance and interpretation

The scratch model is an improvement only if, at one predeclared validation
checkpoint, it satisfies all of these conditions:

- beats the protected best on the ordinary/renderer validation target and
  improves the broad old-corpus mean;
- is no worse on any protected old cohort, including renderer-state and
  fresh-session cohorts;
- improves or preserves temporal-delta MAE, first/steady-frame behavior, and
  left/right eye balance;
- beats the matched F arm under the same schedule, not merely a favorable
  aggregate or training loss;
- reproduces under an independent reload/replay and shows no teacher color or
  spatial-resemblance regression in the fixed visual comparison;
- leaves the frozen test split untouched until all of the above are frozen.

Possible outcomes are deliberately diagnostic:

| Result | Interpretation |
| --- | --- |
| S beats F and the protected best broadly | Initialization/optimization was a real limitation; S becomes an offline candidate for deeper verification. |
| F beats S, but both improve the new cohort only | Existing representation is useful; the limiting issue is data/conditioning distribution or objective balance. |
| Both converge near the same result | Capacity/initialization is not the dominant limitation. |
| S has lower training loss but worse validation/temporal behavior | Scratch overfit or lost the useful learned prior; reject it. |
| S fails to learn or becomes nonfinite | Keep the protected model; diagnose initialization/learning-rate issues without changing the controls. |

No result is promotable from MAE alone. Live Feature 18 behavior, stereo
delivery, teacher color match, headset visual quality, runtime ownership, and
VR frame budget remain separate acceptance axes.

## Isolation and retention

Planned output root:

`C:\OpenNR\Training\semantic_scratch_vs_finetune_20260909`

The output will contain separate `scratch` and `finetune` directories, the
serialized schedule, source/manifest hashes, calibration result, histories,
checkpoint identities, and independent replay results. The protected best,
all old caches, the clean-7 cache, the 18-sequence cache, raw captures, and
previous rejected runs remain immutable. No runtime/profile/MO2 change is part
of this experiment.

The dedicated trainer is now implemented at
`tools/train_semantic_scratch_vs_finetune.py`. It constructs the
identity-safe scratch graph, starts the fine-tune arm with a fresh AdamW state,
serializes one identical paired schedule for both arms, checks the source and
split identities, and fails closed if any source cache or protected checkpoint
changes. Its step-zero scratch identity check is performed before training;
the trainer writes `test_used=false` metadata at every stage.

The preceding 2,400-step sparse-anchor continuation completed on 2026-09-10
without passing the broad gate. The scratch study is therefore the next
controlled initialization test, not a promotion of that continuation.
