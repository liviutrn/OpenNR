# Semantic mixture continuation and whole-eye context study — 2026-09-08

The active goal remains unmet: no ordinary 1× model reaches MAE `<=0.011`, and
teacher-like color, material detail, stereo and temporal acceptance remain open.
This report records the current hard-cohort continuation and the matched use of
the existing full-resolution masters. The subsequent bounded capture setup is
documented in the [full-eye temporal pilot report](FULL_EYE_TEMPORAL_PILOT_SETUP_20260908.md).

## Hard-cohort mixture continuation

The paired arms started from the independently verified seed812 joint-parent
checkpoint at absolute update 1,200 (`C:/OpenNR/Training/semantic_parent_seed812_joint1200_20260908/last.pt`, SHA-256
`fa8a2497e0f89c25dada3d1007fbbf7981fe1c9a2fe2f8fb6c5200ec3ab75bb9`). Both arms
restored optimizer and RNG state and first reproduced the update-1,600
predecessor. The original arm kept cohort probabilities
`0.40/0.15/0.10/0.15/0.10/0.10`; the candidate used
`0.25/0.10/0.10/0.15/0.20/0.20`, oversampling renderer-state and new-pairs.
The objective, parent/head learning rates, eight-frame windows, and six ordinary
validation cohorts stayed unchanged. No test rows were used.

At absolute update 3,200 the original arm improved five of six MAEs from the
common start and all six temporal deltas, but renderer-state remained above its
common-start MAE. The rebalanced candidate improved MAE on all six cohorts from
the common start and brought renderer-state below that baseline, but two temporal
deltas regressed slightly and three cohorts were worse than the matched original
arm. The candidate therefore remains an experiment, not a promoted checkpoint.

| Cohort | Common-start MAE | Original 3200 MAE | Rebalanced 3200 MAE | Rebalanced temporal delta |
|---|---:|---:|---:|---:|
| Prior |0.019231266|0.017937146|0.018280216|0.008433883|
| High-effect |0.017656344|0.014999785|0.014782214|0.007433727|
| Older renderer |0.014859464|0.012293988|0.012515421|0.009458993|
| Fresh session |0.016249614|0.014216284|0.013633489|0.005299556|
| Renderer-state |0.020117967|0.020581142|0.019923122|0.007437541|
| New pairs |0.029031637|0.025266718|0.026916588|0.010888387|

The rebalanced endpoint is still well above the `0.011` target on every cohort.
Its prior and fresh-session temporal deltas are higher than their common-start
values by about `0.0000032` and `0.0000259`; the other four improve. The endpoint
and paired histories are preserved under
`C:/OpenNR/Training/semantic_mixture_rebalanced_pair_20260908`.

## Existing full-eye context evidence

The current crop caches contain crop-derived RGB context. The audited spatial
masters under `C:/OpenNR/TrainingCache/student_v1` retain true whole-eye RGB
thumbnails, aligned guides, input crops and teacher crops. I ran two controlled
studies without reading the test split:

1. On all 352 patches from four sequence-disjoint validation sequences, the
   verified semantic joint update-1,200 model scored MAE `0.025728718` with
   whole-eye RGB context versus `0.026236650` with crop-thumbnail RGB context,
   a `1.936%` improvement. The direction was positive on three sequences and
   negative on one.
2. Two spatial arms then started from the same checkpoint, consumed the same
   deterministic 800-step schedule over 7,712 training patches, and differed
   only in those three RGB context planes. At step 800 the full-eye arm scored
   `0.025302864` on validation versus `0.025424943` for the crop arm, a
   `0.000122080` (`0.480%`) advantage. The sequence-level direction remained
   mixed: full-eye context improved two of four sequences and regressed two.

This is evidence that the model can respond to global RGB context, but not yet
evidence that a new sparse capture will improve the recurrent student. The
spatial pilot is not reset-qualified temporal data, and a three-second cadence
would not supply contiguous temporal history. A future capture should therefore
be a small, separate full-eye temporal pilot only after a storage budget and
manifest contract are fixed; it must carry both eyes, native guides, teacher,
validity, exact resets and contiguous IDs. It must not be mixed into the current
crop cohorts as if it were equivalent data.

## Storage triage

C: reached about 1 GiB free while the continuation and runtime export were active.
I removed only two unreferenced derived caches after checking the active training
inputs and preserving their metadata:

- `C:/OpenNR/TrainingCache/dynamic_guides_v1` — 3.77 GiB, superseded by the
  audited `student_v1` cache;
- `C:/OpenNR/TrainingCache/RendererPairsAligned_20260908` — 5.54 GiB, an
  aligned duplicate whose active strict training input is
  `RendererPairsStrict_20260908`.

The deletion manifest, copied metadata and post-delete absence verification are
under `out/storage_triage_20260908`. The full-resolution source masters and the
current strict cache were retained. C: returned to roughly 117 GiB free before
the next study.

## Superseded next experiment

The planned matched temporal-delta continuation from the rebalanced endpoint is
complete. Doubling the temporal-delta weight produced a small mixed change and
neither arm passed the all-six-cohort retention gate. The exact endpoint table,
schedule and hashes are in the [temporal-delta continuation report](SEMANTIC_DELTA_CONTINUATION_20260908.md).

The rebalanced step-3,200 endpoint remains a research reference rather than a
quality promotion. The next evidence-backed data step is a small, separately
budgeted full-eye temporal pilot; a three-second full-frame cadence can test
global spatial/color context but cannot provide contiguous recurrent history.
The full-eye pilot proposal remains disabled by default, and the result does
not authorize a large new capture or Runpod spend.
