# Full-eye pilot training and pause record — 2026-09-09

The newly collected full-eye material is now validated, used in bounded local
experiments, and preserved. Training is paused at the user's instruction. No
checkpoint from the paused arm is promoted, no runtime profile was changed, no
test split was used, and no Runpod credit was spent.

## Data used

The raw temporal pilot is
`C:\OpenNR_Captures_FullEyeTemporalPilot_20260908` (19 sequences × 240 frames,
about 88.38 GiB). The strict cache is
`C:\OpenNR\TrainingCache\full_eye_temporal_pilot_strict_20260908`. It contains
11 selected sequences split 6/2/3 across train/validation/frozen-test, 704
frames and 1,408 eye rows. It preserves the required initial `[true, true]`
reset, contiguous identifiers and native depth/motion guides. Eight source
sequences were excluded for host/backpressure gaps; they remain on disk and in
the audit rather than being silently discarded. The completed cache hash is
`efbd159ad069fbd128fb28a890ff53a07fa968ae67f1182ad259fc6ef47e13a1`.

The separate spatial anchor cache is
`C:\OpenNR\TrainingCache\full_eye_periodic_spatial_20260909`. It uses one
full-resolution frame per sequence at frame 240 (roughly every three seconds
at the current 80 FPS headset setting): 38 eye rows and 240 patches, split
176/32/32 by sequence for train/validation/test. It is explicitly marked
`temporal_training_allowed=false`; the frozen test rows were not used for
tuning. Its completion hash is
`2a2fbfae728921fcd6cfafa6ef643c1660ab73082efe5f5df810da9e94774886`.

The periodic capture audit reports the expected limitation of this mode:
non-anchor frames do not contain complete full-frame artifacts, so that root
is suitable for spatial/global-context supervision and anchor checks, not as a
continuous temporal sequence. The raw source and all excluded material remain
intact.

## Completed paired temporal pilot

The first paired run used the verified semantic joint step-1200 checkpoint as
the common initializer. The control kept the old six-cohort schedule; the arm
replaced a bounded 15% of draws with the strict full-eye temporal pilot. The
comparison is recorded in
`out/semantic_full_eye_pilot_paired_20260909/comparison.json`.

| Evaluated step | Control old-cohort mean MAE | Arm old-cohort mean MAE | Control full-eye MAE | Arm full-eye MAE | Old cohorts won by arm |
|---:|---:|---:|---:|---:|---:|
| 1,200 baseline | 0.018179 | 0.018179 | 0.019256 | 0.019256 | 0/6 |
| 1,600 | 0.017710 | 0.017644 | 0.018288 | 0.018273 | 4/6 |
| 2,000 | 0.017285 | 0.017587 | 0.018675 | 0.018533 | 1/6 |

The arm briefly improved the new pilot and several old cohorts at step 1,600,
then lost the broad old-cohort gate by step 2,000. It is therefore a useful
diagnostic run, not a promoted model. Ordinary 1× MAE `<= 0.011` remains
unmet.

## What the full-eye context experiment established

The independent spatial context pair compared full-eye conditioning with the
current crop-derived context on sequence-disjoint periodic anchors. At its
best checkpoint (step 600), full-eye MAE was `0.021339` versus `0.023012` for
crop context; at step 800 the values were `0.021453` and `0.023085`. This is a
roughly 7% spatial improvement, but it is not temporal or runtime acceptance
evidence. The result is recorded in
`out/semantic_full_eye_pilot_paired_20260909/spatial_context_result.json`.

A read-only transfer probe loaded those context weights into the temporal
model while still feeding crop-derived temporal context. The full-eye pilot
was `0.018516` MAE, but renderer-pilot and fresh-session cohorts moved to
`0.013298` and `0.015169`; the mixed result does not justify promotion. The
probe is recorded in
`out/semantic_periodic_context_temporal_transfer_20260909/result.json`.

## Paused continuation

The next run initialized the temporal pair from the full-eye context arm and
used a bounded 10% new-data probability. Its control completed step 2,000;
the control's old-cohort mean was `0.018142` and its full-eye-pilot MAE was
`0.018526`, with no broad promotion gate. The arm was stopped after its status
write at step 1,425. The last persisted arm checkpoint is the exact common
start at step 1,200 (`last.pt`, SHA-256
`6bcb6b449eea2c70a4cd4ab0bc68b7e1e2aeba35ea5ee36d5ef011b5b70ebdab`); no
step-1,600 checkpoint exists. The pause record is
`C:\OpenNR\Training\semantic_periodic_context_temporal_paired_20260909\pause_record.json`.

The pause was verified by process inspection: no matching training process
remains and `nvidia-smi` reports no active compute workload. The partial run,
history, baseline and source data are preserved. The arm's `status.json`
still says `training` because it is the last writer's status snapshot; the
separate pause record is the authoritative interruption marker.

## Storage and precision guardrails

At pause time the fast-drive free space was approximately C: 307.32 GiB,
D: 37.87 GiB, E: 31.06 GiB and G: 18.88 GiB. The new Linux USB drive is
mounted read-only at `/mnt/wsl/wd_elements_20tb`, with about 9.0 TiB free. Its
read-only filesystem check reported metadata advisories, so no cold-storage
move, repair or deletion was attempted. The storage triage record remains in
`docs/STORAGE_TRIAGE_20260909.md`.

The accepted runtime path remains TensorRT FP16-I/O/FP16 tactics with requested
FP32 reductions. The failed FP8 Q/DQ attempt is not part of the training
contract. FP8 in the external DLSS-NR teacher/runtime is a precision choice
inside that inference path; it does not require the student to be FP8. The
student remains FP16 until quality, temporal behavior and live acceptance are
established, after which quantization can be evaluated as a separate matched
experiment.

## Superseding continuation addendum — 2026-09-09

The pause described above was superseded by the explicit goal continuation.
The retained raw pilot was re-inspected and found to contain all six committed
renderer G-buffer crop stages on every frame of the 11 strict selected
sequences, both eyes. A separate overlay was built at
`C:\OpenNR\TrainingCache\full_eye_renderer_conditioning_strict_20260909_retry2`
with schema `opennr-full-eye-renderer-conditioning-v1`, 17 aligned float16
channels at 128x128, and exact source/payload hashes. The source raw capture,
strict RGB/guides/context cache, and all excluded sequences were left
unchanged. Test rows were materialized only for row identity and were not
used by training or replay.

A matched semantic joint-parent pair then started from the verified step-800
pixel-only checkpoint, using the same deterministic schedule and adapted base
AdamW state. The control supplied zero renderer channels; the arm supplied
the real G-buffer overlay only to the new full-eye temporal cohort at a 15%
draw probability. Both completed absolute step 1,600 locally on the RTX 5070
Ti. The arm's learned renderer stem was nonzero, but its full-eye MAE was
`0.019008374` at step 1,200 and `0.019884635` at step 1,600, versus control
values `0.018713259` and `0.019049668`. The old-six mean was also worse by
`0.000035158` and `0.000071590` at those steps. No all-seven checkpoint was
created or promoted.

The arm endpoint was independently replayed with `max_difference=0.0` in
`C:\OpenNR\Training\semantic_renderer_conditioned_pair_20260909\arm_independent_replay`.
The branch changed held-out predictions materially, but substituting zeros
for the real renderer channels improved full-eye validation from
`0.019884635` to `0.018931382`; this is a learned but misdirected response,
not an inert branch. A train-only linear residual probe likewise found no
simple cross-sequence G-buffer gain. The single-stem renderer arm is therefore
rejected for promotion and is not being extended with more steps.

The tightened project target for this continuation is ordinary 1x MAE
`<=0.007`, with temporal stability and convincing teacher/color match. The
best current ordinary cohort remains `0.013283717`, so the target remains
unmet. The complete decision, exact cohort table, source hashes, storage
state, and next capture contract are recorded in
`docs/GOAL_CONTINUATION_20260909.md`.

## Superseding capture audit and crop-temporal re-arm — 2026-09-09

The user then ran the prepared full-eye every-frame contract and produced two
complete sequences under
`C:\OpenNR_Captures_FullEyeTemporalEveryFrame_20260909`:

| Sequence | Complete frames | Size | Result |
| --- | ---: | ---: | --- |
| `seq-1788993098503-1` | 64/64 | 13.59 GiB | full-eye artifacts complete; strict temporal gate rejected host gaps up to 188 and backpressure 47 |
| `seq-1788993615492-2` | 64/64 | 13.41 GiB | full-eye artifacts complete; strict temporal gate rejected host gaps up to 179 and backpressure 94 |

Both sequences retain initial `[true, true]` reset, contiguous frame/sample
IDs, no dropped records, both-eye full-frame input/teacher/depth/motion, and
six renderer-conditioning crop stages. They are useful spatial/teacher/color
masters but are not temporal-ready. The corrected exhaustive byte validator
passes both with zero errors, missing files, duplicate IDs or duplicate hashes.
It reports three all-zero motion-vector crop warnings in sequence 1 and 67 in
sequence 2, retained for review rather than silently removed. The six
renderer-conditioning stages remain explicitly crop-only.

Because full-frame readback could not sustain the required host cadence, the
live profile was re-armed after the game and SteamVR closed for the separate
lower-I/O crop-temporal contract. It retains both eyes, one 512-pixel center
crop, 80 Hz, raw pre/post input and teacher, native depth/motion and all six
renderer-conditioning crops, while disabling full-frame capture and raising
the bounded queue from 16 to 32. The new root is
`C:\OpenNR_Captures_TemporalCrops_EveryFrame_20260909`.

The live profile validates with no errors or warnings. Its SHA-256 is
`6e770b9b9a193bd959b7bc404e4583ddd1472ede7c9dd00c1034ce3f97193c6d`; its
byte-identical backup is
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-crop-temporal-20260909\SettingsUser.before.json`
with SHA-256
`ccde5515081396076715fba06ff66430456adf50a4995ef273ba77de76762dd0`.
The next crop burst must pass the crop-mode strict gate before training.

## Superseding completed collection and paired continuation — 2026-09-09

The user finished the lower-I/O crop-temporal collection. The authoritative
root now contains 18 complete sequences, not just the two-sequence preparation
snapshot described above:

C:\OpenNR_Captures_TemporalCrops_EveryFrame_20260909

Strict audit result: 18/18 temporal-ready sequences, 1,152/1,152 complete
frames, 2,304 eye rows, initial [true, true] reset in every sequence, contiguous
frame/sample/host IDs, zero backpressure, zero drops, and no mid-sequence
resets. Exhaustive validation checked 23,040 artifacts with zero missing files,
duplicate IDs, duplicate hashes, all-zero primary images, or errors. Raw motion
content is valid for all eye rows. Conditioning content contains 18,432
records with zero nonfinite values; one sequence has a localized eight-record
all-zero/duplicate gbuffer_specular auxiliary outlier. These findings are
documented and the source data is retained.

The all-18 cache was materialized and tested at:

C:\OpenNR\TrainingCache\crop_temporal_every_frame_20260909_all18

It is schema 2 with RGB [2304, 2, 3, 512, 512], guides
[2304, 5, 128, 128], context [2304, 8, 96, 96], sequence-disjoint
11/3/4 train/validation/test splits, zero invalid depth/motion values, finite
arrays, and temporal training allowed. The test split was held out from
training.

Two matched local continuation runs were completed from the verified step-800
semantic joint-parent checkpoint. The 15% arm ran to step 1,600 and the
conservative 5% arm ran to step 1,200. Neither passed the protected
all-cohort no-regression gate:

| Run | Renderer-pilot MAE | New crop MAE | Old-six mean | Decision |
| --- | ---: | ---: | ---: | --- |
| Protected base, step 800 | 0.013283715 | 0.016768350 | 0.017770065 | Active best |
| 15% control, step 1,600 | 0.013494855 | 0.017329732 | 0.018232937 | Rejected |
| 15% arm, step 1,600 | 0.014186551 | 0.016979217 | 0.019845464 | Rejected |
| 5% control, step 1,200 | 0.013707421 | 0.017779784 | 0.017882933 | Rejected |
| 5% arm, step 1,200 | 0.014096768 | 0.017965010 | 0.018169616 | Rejected |

Independent held-out crop replay found the 15% arm at step 1,600 had the best
isolated crop MAE, 0.018912105, but its protected validation regression and
slightly worse temporal delta block promotion. The 5% control was slightly
better than its paired arm on the held-out test, so the crop-data signal is not
robust enough to attribute to the new tranche.

The active best remains unchanged, ordinary 1x MAE <= 0.007 remains unmet, and
no student, runtime, profile, or deployment was promoted. The complete evidence
and next-step recommendation are in
[CROP_TEMPORAL_CONTINUATION_20260909.md](CROP_TEMPORAL_CONTINUATION_20260909.md).
