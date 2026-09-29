# Scratch-v2 versus protected-best finetune — plan — 2026-09-10

## Purpose

This is a second, bounded initialization experiment for the OpenNR student. It
tests whether a better training curriculum can make a genuinely fresh
OpenNR parent/head initialization competitive with a matched finetune of the
current overall best checkpoint.

The experiment is not allowed to replace the protected model, consume the
frozen test streams, or turn a narrow renderer-pilot improvement into a
temporal or runtime claim.

## Immutable reference

The control checkpoint is:

`C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`

Protected checkpoint SHA-256:

`40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`

The recorded parent is the `context_v7_capacity_temporal` graph:

- base width `64`, `3` base blocks, scale `4`;
- temporal hidden `64`, downsample `8`, delta scale `0.12`;
- capacity width `192`, `6` blocks, extra width `96`, extra blocks `3`;
- inherited residual/final gates, style modulation disabled.

The protected parent and all six protected cohort manifests are verified by
their recorded hashes before the run. The 18-sequence cache, clean7 cache,
all previous checkpoints, and the invalid `seq8` stream remain controls and
are not modified or appended implicitly.

## Why this differs from scratch-v1

Scratch-v1 established that a random trainable parent/head was materially
behind the learned initialization after 1,600 steps. Its finetune arm reached
renderer-pilot MAE `0.012460920`; its scratch arm reached `0.016137965`.
Scratch-v1 also exposed three failure modes:

1. adding clean7 at 15% was too aggressive, and a paired 5% recovery arm was
   slightly worse than old-only control;
2. raising renderer-pilot exposure to 25% improved the narrow metric to
   `0.011838914` but lost broad MAE/temporal preservation;
3. freezing the learned temporal parent did not recover the broad behavior
   and removed the ordinary-metric gain.

Scratch-v2 therefore keeps the exact current graph and frozen pretrained DINO
encoder, excludes clean7 from the primary parity corpus, and changes the
optimization schedule rather than changing width or silently using a new
target.

## Paired arms

### S2 — identity-safe scratch

Construct the exact recorded graph with newly initialized trainable parent and
semantic/tone head weights. Retain only the verified pretrained DINOv2 encoder
and its provenance. Preserve the architecture's zero residual/output
initialization so the initial function is an RGB identity. Record parameter
counts, finite tensors, identity error, temporal-state presence, and the seed.

### F2 — matched protected-best finetune

Load the immutable protected-best weights, create a fresh AdamW optimizer, and
train under the identical sample schedule, learning-rate schedule, objective,
validation cadence, and step budget as S2. The optimizer is intentionally not
restored from the protected checkpoint: this isolates initialization from old
Adam moments while preserving an apples-to-apples comparison.

## Corpus and leakage contract

Use exactly the six cohorts recorded by the protected checkpoint, in their
recorded order:

1. `E:\OpenNR_TrainingInputs\AlignedGuides_AllCohorts_20260907`
2. `E:\OpenNR_TrainingInputs\AlignedGuides_HighEffect_20260907`
3. `E:\OpenNR_TrainingInputs\AlignedGuides_RendererPilot_20260907`
4. `E:\OpenNR_TrainingInputs\RendererConditioningFreshSession_20260907_2114`
5. `D:\OpenNR_TrainingInputs\RendererStateDistillationStrict_20260908`
6. `C:\OpenNR\TrainingCache\RendererPairsStrict_20260908`

Only sequence-disjoint train rows are sampled. Existing validation rows are
used for checkpoint selection and no test rows are loaded. The runner checks
cross-cohort train/validation sequence collisions and verifies each cache's
`complete.json` hash before starting.

The sparse clean7 cache is deliberately validation-only in this experiment's
interpretation: it is not mixed into the six-cohort training schedule because
the prior paired recovery did not show a benefit. It may be evaluated later as
an explicitly named external stress cohort, never as an unlabelled part of the
old-corpus gate.

## Schedule and objective

The primary run has 3,200 optimizer updates, with validation at steps
`0, 400, 800, 1,200, 1,600, 2,000, 2,400, 2,800, 3,200`. Both arms consume the
same serialized window IDs.

Each update uses one contiguous eight-frame temporal window, burns in the
first two frames, trains with batch `1`, and uses the protected-best-compatible
pixel-only per-frame L1 objective. Batch `1` is intentional: the earlier
batch-4 calibration failed during large-stream cuDNN evaluation while the
batch-1 calibration and full run were stable.

The cohort distribution is staged:

| Stage | Updates | prior | high_effect | renderer_pilot | fresh_session | renderer_state | new_pairs | Purpose |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Broad acquisition | 1,600 | 0.40 | 0.15 | 0.10 | 0.15 | 0.10 | 0.10 | Learn the full old-corpus mapping from identity |
| Target-balanced | 800 | 0.30 | 0.15 | 0.20 | 0.15 | 0.15 | 0.05 | Increase ordinary exposure while retaining state supervision |
| Broad restoration | 800 | 0.35 | 0.15 | 0.15 | 0.15 | 0.15 | 0.05 | Recover broad/state behavior before selection |

The 20% renderer-pilot stage is intentionally below the rejected 25% focus
recipe, while renderer-state exposure is raised to 15%. The final restoration
stage is a predeclared guard against selecting a transient narrow optimum at
the end of the target-focused stage.

Use a recorded global learning-rate schedule for both arms: 200-update linear
warm-up from 20% of the nominal rates, followed by cosine decay to 20% of the
nominal rates. Nominal rates are head `1e-4` and parent `1e-5`, with AdamW
weight decay `1e-4` and gradient clipping at `1.0`. The schedule is a stability
change for the longer scratch trajectory, not permission to tune against the
validation result mid-run.

## Stopping and extension rule

Run a 400-update paired calibration first using the same code path and batch-1
evaluation. Check CUDA stability, identity initialization, finite loss,
gradient reachability, replay reload, and peak VRAM. The calibration is
discarded as a selection candidate and retained as a diagnostic artifact.

Then run the 3,200-update pair. Do not extend automatically. Extension to
6,400 updates is allowed only if:

- S2 and F2 remain finite and independently reloadable;
- the scratch curve is still improving at the latest two checkpoints;
- S2 is closing the renderer-pilot gap to F2 rather than merely lowering its
  training loss;
- neither arm has an early broad/temporal collapse that makes more steps
  uninterpretable.

There is no blind 50,000-step run. If S2 remains materially behind F2 after
3,200 updates, the result is evidence for retaining learned initialization,
not a reason to spend more compute on random weights.

## Acceptance gates

An S2 checkpoint is an improvement only if the same checkpoint satisfies all
of the following:

1. ordinary renderer-pilot validation MAE `<= 0.007`;
2. beats F2 on the ordinary target under the identical schedule;
3. old-six mean is no worse than the protected best and no individual old
   cohort regresses beyond the declared tolerance;
4. all protected temporal-delta metrics are no worse than the protected best;
5. left/right eye balance, first/steady-frame behavior, and color-error
   summaries do not regress;
6. independent replay reproduces the checkpoint exactly;
7. a broad fixed visual A/B sheet shows convincing teacher resemblance and
   color match with no material identity, geometry, material, or stereo error;
8. runtime and VR-budget acceptance are measured separately before any
   promotion.

F2 is a comparison arm, not an automatic promotion candidate. A lower narrow
   MAE with a broad or temporal regression is diagnostic only.

## Outputs and storage

Primary output root:

`C:\OpenNR\Training\semantic_scratch_v2_vs_finetune_20260910`

The root will contain immutable run metadata, the paired schedule and digest,
calibration diagnostics, arm histories, validation checkpoints, replay
artifacts, and a result report. The protected checkpoint and source caches are
read-only inputs.

At the current measured free space of approximately `161.6 GiB` on C:, no
cleanup is justified. If free space approaches the existing `100 GiB` guard,
triage will first identify unreferenced failed calibration artifacts and
duplicate rendered previews; controls, source caches, reports, and all
checkpoints referenced by a manifest will be preserved until their references
are removed and the replacement evidence is verified. Runpod is not needed for
this graph: the prior local run fit under roughly `10 GiB` peak, so the
remaining credit is reserved for a genuinely VRAM-bound experiment.

## Decision matrix

| Outcome | Decision |
|---|---|
| S2 beats F2 and passes all broad gates | Freeze, replay, render A/B, then consider an offline promotion candidate |
| S2 improves ordinary MAE but loses broad/temporal gates | Reject promotion; retain as a diagnostic focus candidate |
| S2 remains behind F2 | Keep learned initialization as the production path; stop scratch expansion |
| Both arms plateau well above `0.007` | Prioritize new scene/sequence-disjoint native-guide full-eye data or a validated target/objective change |

