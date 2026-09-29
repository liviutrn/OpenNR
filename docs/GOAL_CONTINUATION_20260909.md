# OpenNR student goal continuation — 2026-09-09

## Decision first

The tightened goal remains unmet: no current ordinary 1× checkpoint reaches
MAE `<= 0.007`. The strongest result from this continuation is a verified
pixel-only semantic joint-parent checkpoint that improves all six ordinary
validation cohorts and all six recorded temporal-delta values relative to its
stable-U-Net starting point. Its lowest cohort MAE is `0.013283715`, and its
unweighted six-cohort mean is `0.017770065`; it is an offline research
candidate, not a production or runtime promotion.

The three additional probes were kept separate:

1. A native-resolution detail residual learned a measurable correction but
   regressed the fresh-session and new-pairs cohorts. It has no eligible
   checkpoint.
2. An optimizer/RNG-preserving continuation of the pixel-only candidate
   improved several cohorts at absolute update 1600 but regressed
   renderer-pilot and new-pairs relative to its common start. It has no
   eligible checkpoint.
3. A strict native renderer-conditioning overlay was built from the retained
   full-eye pilot. The semantic stem branch learned a nonzero response, but
   the arm was worse than its matched zero-conditioning control on the new
   full-eye validation and did not improve the old-cohort mean. It has no
   eligible checkpoint.

The current evidence therefore supports preserving the pixel-only step-800
candidate for further offline analysis, retaining the full-eye renderer
overlay as a measured negative arm, and collecting broader paired temporal
evidence before another material architecture change. Repeating the same
pixel-only objective, adding a small local residual, or injecting the same
G-buffer channels at the same single stem is not justified as a route to
`0.007`.

## Intake and scope

Before training, the current local reports, checkpoint inventories, capture
audits, storage report, and the latest related Codex tasks were reviewed. The
active local GPU was confirmed idle, the working tree was found to contain
user-owned research changes, and those changes were preserved. No SkyrimVR,
MGO, MO2, SteamVR, capture, or production OpenNR profile was launched or
edited during this continuation.

The active six-cohort ordinary 1× semantic contract remained:

| Cohort | Validation streams | Input role |
| --- | ---: | --- |
| `prior` | 47 sequences / 94 eyes | existing strict temporal cohort |
| `high_effect` | 5 / 10 | existing strict temporal cohort |
| `renderer_pilot` | 2 / 4 | existing aligned renderer pilot |
| `fresh_session` | 5 / 10 | existing fresh-session aligned cohort |
| `renderer_state` | 6 / 12 | strict renderer-state cohort |
| `new_pairs` | 3 / 6 | strict renderer-pair cohort |

Training probabilities stayed at `0.40 / 0.15 / 0.10 / 0.15 / 0.10 / 0.10`,
with eight-frame windows, two burn-in frames, batch one, and no frozen-test
rows. The temporal caches still use crop-derived RGB context. The recent
full-eye pilot has true full-frame artifacts only at its anchor samples, so it
is not silently treated as a whole-eye recurrent training cache.

## Experiment A — ordinary-L1 objective alignment

### Recipe

The compound objective was isolated from ordinary MAE by adding a
`--pixel-only` mode to the local semantic ablation and joint-parent trainers.
The paired run started from the independently verified stable-U-Net warm head
at:

`E:\OpenNR_Training\stable_unet_broad_20260907\best_all_cohorts.pt`

Warm-start SHA-256:

`e240963bdf7d6cb61cafb0cc0445757af4c661b91e57217d5ef031b06c57c962`

Both arms used seed `909`, 800 updates, learning rate `1e-4`, and the same
draw schedule. The control trained only the semantic head with the causal
parent frozen. The joint arm trained the semantic head and causal parent.
The new `--frozen-parent` switch exists only to make that control explicit;
it does not alter the existing runtime path.

Outputs:

- Control: `C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\control`
- Joint: `C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint`
- Independent joint replay and fixed sheets:
  `C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint_independent_replay`

### Control result

The frozen-parent control selected step 400 under its all-six-cohort rule:

| Step | Prior | High-effect | Renderer pilot | Fresh | Renderer state | New pairs | Gate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 0.019231320 | 0.017656091 | 0.014859179 | 0.016249634 | 0.020117862 | 0.029031382 | start |
| 400 | 0.018948840 | 0.017028159 | 0.014744885 | 0.015376793 | 0.019995059 | 0.025865943 | all six improved |
| 800 | 0.019407521 | 0.016726496 | 0.013908000 | 0.015180087 | 0.020555095 | 0.025374711 | rejected |

The step-800 control regression on prior and renderer-state shows that even
ordinary-L1 training can overfit the mixture at this budget.

### Joint result

The joint step-800 checkpoint improved every cohort against the common
stable-U-Net start and also improved every temporal-delta value against that
start:

| Cohort | Common start MAE | Joint step 800 MAE | MAE change | Joint temporal delta |
| --- | ---: | ---: | ---: | ---: |
| Prior | 0.019231320 | 0.019004597 | -0.000226723 | 0.008317676 |
| High-effect | 0.017656091 | 0.015705697 | -0.001950394 | 0.007663593 |
| Renderer pilot | 0.014859179 | 0.013283715 | -0.001575464 | 0.009722360 |
| Fresh session | 0.016249634 | 0.014562632 | -0.001687002 | 0.005272257 |
| Renderer state | 0.020117862 | 0.019688752 | -0.000429110 | 0.007381576 |
| New pairs | 0.029031382 | 0.024374998 | -0.004656384 | 0.010872573 |

The unweighted six-cohort mean moved from `0.019524245` to `0.017770065`,
an `8.985%` reduction, with mean relative ratio `0.914363254`. Against the
matched step-800 frozen-parent control, the joint arm is lower on all six
cohorts. Against the control's selected step-400 checkpoint, it is lower on
five of six and is higher on prior by about `0.0000558`; that tradeoff is
retained rather than hidden.

Joint checkpoint:

`C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`

SHA-256:

`40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`

The independent replay matched MAE, PSNR, and temporal delta for all six
cohorts with zero recorded difference. The report is under
`joint_independent_replay\result.json`, and the fixed native-size samples are
available in its `index.html` gallery. Two inspected sheets still show the
student close to the input rather than reproducing the teacher's facial
shading, skin/material detail, and local highlight structure. Code-value tone
metrics were recorded, but they do not establish physical color or visual
teacher equivalence.

This candidate is not the global project promotion. The earlier seed-812
joint checkpoint still has a lower older-renderer cohort value around
`0.012690`, while the new pixel-only candidate is materially better on the
new-pairs and renderer-state cohorts. The candidate also remains above
`0.007` on every cohort.

## Experiment B — native-resolution detail residual

This ablation added a zero-initialized, width-32 native-resolution residual on
top of the Experiment-A joint step-800 checkpoint. The inherited causal
parent and semantic head were frozen, the residual scale was `0.08`, and the
compound L1 + pooled + temporal-delta loss was used. At initialization the
child reproduced the base output; the base and all parent state tensors were
left unchanged.

Output:

`C:\OpenNR\Training\semantic_detail_ablation_20260909`

| Step | Prior | High-effect | Renderer pilot | Fresh | Renderer state | New pairs | Gate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 0.019004597 | 0.015705697 | 0.013283715 | 0.014562632 | 0.019688752 | 0.024374998 | base |
| 400 | 0.018829472 | 0.015495803 | 0.013188988 | 0.014697184 | 0.019676371 | 0.025520484 | rejected |
| 800 | 0.018884198 | 0.015530542 | 0.013195700 | 0.014873624 | 0.019786533 | 0.027882859 | rejected |

The branch improved four cohorts at step 400 and four at step 800, but
fresh-session and especially new-pairs regressed. Temporal deltas were mixed
as well. The endpoint was independently replayed exactly; no `best.pt` was
created because neither evaluation passed the all-cohort gate. A final JSON
serialization bug when representing an empty best score was repaired in the
writer and the generated status was corrected to `complete`; the training
itself had finished without nonfinite values or OOM.

## Experiment C — optimizer/RNG-preserving continuation

The Experiment-A joint step-800 optimizer, NumPy RNG, Torch RNG, and CUDA RNG
state were restored exactly and continued for 800 updates using the same
pixel-only objective and schedule. Resume replay matched all six starting
MAEs, PSNR values, and temporal deltas exactly.

Output:

`C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\continuation_800_1600`

| Absolute step | Prior | High-effect | Renderer pilot | Fresh | Renderer state | New pairs | Gate vs step 800 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 800 | 0.019004597 | 0.015705697 | 0.013283715 | 0.014562632 | 0.019688752 | 0.024374998 | start |
| 1200 | 0.018708246 | 0.015111664 | 0.012929946 | 0.014848773 | 0.020240446 | 0.026915891 | rejected |
| 1600 | 0.018496163 | 0.015420452 | 0.013443214 | 0.014398757 | 0.019231393 | 0.024822098 | rejected |

The endpoint improved prior, high-effect, fresh-session, and renderer-state
against step 800, but renderer-pilot and new-pairs regressed. Temporal delta
also failed the all-not-worse check. There is no selected continuation
checkpoint. The preserved endpoint was independently reloaded and replayed
with zero recorded difference; its SHA-256 is
`C519BE0F88E8245FAA3459BCE8DD0E2BFAD4BCA456BFA45C3E9EC99619997BCC`.

## Acceptance separation

| Axis | Current state |
| --- | --- |
| Source/config/package health | Training sources compile; new experiment scripts are present in the dirty user worktree. |
| Offline ordinary MAE | Experiment-A step 800 passes its six-cohort improvement gate versus the warm start, but every cohort is above `0.007`. |
| Temporal stability | Experiment-A step 800 improves all six temporal-delta values versus its common start; no strict renderer reset/warm pair has been established for the 0.5.7 tranche. |
| Teacher visual/color match | Not accepted. Fixed sheets remain input-like with unresolved teacher facial shading, skin/material detail, highlights, and local shadows. |
| Stereo / headset / audible / UI | Not tested in this continuation. |
| Runtime / deployment / VR budget | No export, engine replacement, Skyrim launch, or live frame-budget claim was made. |

## Storage and Runpod

End-of-run free space:

| Drive | Free |
| --- | ---: |
| C: | 304.48 GiB |
| D: | 37.85 GiB |
| E: | 31.05 GiB |
| G: | 18.88 GiB |

No files were deleted or moved. The raw full-eye pilot, strict caches,
checkpoints, and provenance were retained. The failed/untrusted H: device and
the read-only WDC ext4 volume were not used for writes or cold-storage moves.

Runpod was rechecked and no active pod was present. No new pod, volume, upload,
or billable resource was created; the remaining credit is untouched. The
local 5070 Ti handled these runs within roughly 4.3–9.5 GiB allocated VRAM,
so a remote GPU would not have improved the comparability or the current
conditioning limitation.

## Next evidence-led step

Do not deploy either the detail branch or the unpaired step-1600 endpoint.
Keep the Experiment-A step-800 checkpoint as a reproducible offline reference
for later comparisons. The next high-value quality step is a small, separately
budgeted full-eye temporal capture with true full-eye RGB available on every
contiguous frame, both eyes, native Feature 18 guides, validity masks,
renderer conditionings, exact reset metadata, and sequence-disjoint splits.
The existing pilot cannot supply that contract because only anchor frames have
full-frame artifacts. Any future capture remains a user-launched Skyrim
operation; this continuation did not launch the game.

Until that information gap is addressed, additional capacity scaling, another
small native residual, or cloud rental is unlikely to close the remaining gap
from approximately `0.013`–`0.024` down to `0.007` while preserving temporal
and visual acceptance.

## Prepared next-capture contract — 2026-09-09

Before this re-arm, the live profile was the already-used anchor pilot: it
captured a contiguous 240-sample crop sequence and one full-eye anchor at
sample 240. It was not sufficient for full-eye temporal supervision on every
frame. The live profile is now switched, reversibly, to the every-frame
contract below. The game and VR processes were absent for the edit.

A separate disabled-by-default example is now prepared at
`config/opennr_capture_full_eye_temporal_every_frame_20260909.example.json`.
The live `SettingsUser.json` now requests one 64-sample sequence at an 80 Hz eligibility cadence, full-frame
artifacts on every accepted sample, both eyes, one center crop, raw Feature 18
depth and motion, raw teacher, and all six renderer conditionings. It writes
to the new root `C:\OpenNR_Captures_FullEyeTemporalEveryFrame_20260909` and
uses `capture_full_frame_sequence=true` and `full_frame_every_samples=0`.
The edited live profile SHA-256 is
`ccde5515081396076715fba06ff66430456adf50a4995ef273ba77de76762dd0`.
The byte-identical pre-edit backup is
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-full-eye-every-frame-20260909\SettingsUser.before.json`,
with SHA-256
`260c185ade91e832c408852e2ed87cb7047d46ddb7d3c74b2d78a21815cd19a9`.
`Rollback.ps1` is beside that backup.

This is intentionally a bounded first tranche. The 2026-09-04 full-resolution
audit measured about 0.25 GiB per full-frame stereo record before any derived
cache, so a 64-frame sequence can approach 16 GiB; the actual next run must
be measured and stopped if queue pressure or storage use is abnormal. Start
with at most four varied scenes until the first sequence is audited. Require
an initial `[true, true]` reset, no later reset, contiguous frame/sample/host
IDs, complete full-frame left/right input and teacher, native guides and
validity, all renderer stages, and sequence-disjoint train/validation/test
assignment. Do not train on a sequence until the ordinary validator,
full-frame temporal gate, alignment/content audit, and storage accounting pass.

The user must launch Skyrim/VR and trigger the burst. No game or VR runtime
was launched while preparing this contract.

## Experiment D — strict full-eye renderer conditioning

The retained full-eye pilot was re-inspected rather than treated as crop-only
data. Every frame in the 11 reset-qualified sequences has committed crop
readbacks for all six renderer stages on both eyes, not only the periodic
full-eye anchor frames. The frame metadata reports renderer conditioning as
requested, all stages available, `copy_queued=true`, `texture_present=true`,
and `deferred_refresh_status=targets_match_main`. The native renderer source
rectangles and the teacher crop rectangles are compatible with the existing
audited affine alignment.

The sampled content probe found the aligned albedo had approximately `0.55`
correlation with the teacher RGB on two sequences and three frames per eye;
the decoded normals and all packed unsigned stages were finite. This is a
diagnostic signal check, not a claim that albedo is the teacher target: the
teacher includes lighting and learned appearance that the exposed G-buffers
do not directly contain.

### Cache and model

The new overlay was built without changing the raw capture or the source
strict cache:

- Overlay: `C:\OpenNR\TrainingCache\full_eye_renderer_conditioning_strict_20260909_retry2`
- Schema: `opennr-full-eye-renderer-conditioning-v1`
- Shape: `1408 x 17 x 128 x 128`, float16
- Split: 6 train / 2 validation / 3 test sequences; 768 / 256 / 384 eye rows
- Channel order: albedo RGB; decoded view-space normal XYZ plus roughness;
  masks RGB; masks2 R; specular RGB; reflectance RGB
- Normalization: unchanged UNORM albedo, decoded signed normals, and fixed
  `x/(1+x)` compression for the nonnegative HDR stages
- Alignment: native renderer crop to teacher crop, then fixed BOX downsampling
- Conditioning payload SHA-256:
  `0303f738267aeab1683de7f34f981ed5ed2821c7e0016cba6040f7de7e038df0`
- Overlay `complete.json` SHA-256:
  `b8af401dcd7d65f23ac7eeed40cc51b4c3ebce6972275f0d043244e33ca3f395`
- Source strict-cache row identity:
  `efbd159ad069fbd128fb28a890ff53a07fa968ae67f1182ad259fc6ef47e13a1`
- `test_used_for_tuning=false`; test rows were materialized for row identity
  only and are prohibited from the trainer and verifier.

The model is a separate semantic joint-parent research arm. Its first stem
expands from 19 to 36 input channels, copying the existing 19-channel weights
and zero-initializing the 17 renderer slices. The base AdamW moments were
retained; the widened renderer moments were zero-padded. The matched control
and arm used the same seed `912`, schedule, 8-frame windows, 2-frame burn-in,
BF16 path, parent/head learning rates, and compound temporal objective. The
renderer cohort probability was `0.15`; only the arm supplied real G-buffers
for that cohort, while both arms supplied zeros to the six older cohorts.

### Held-out result

The base step-800 values are the common zero-branch starting point. Lower MAE
is better; the full-eye renderer cohort is an additional validation cohort,
not a replacement for the six ordinary cohorts.

| Validation cohort | Base / step 800 | Control / step 1,200 | Arm / step 1,200 | Control / step 1,600 | Arm / step 1,600 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Prior | 0.019004597 | 0.018388137 | 0.018408371 | 0.017752501 | 0.017754517 |
| High-effect | 0.015705697 | 0.016189257 | 0.016128846 | 0.015688589 | 0.015728973 |
| Renderer pilot | 0.013283717 | 0.014106521 | 0.014155826 | 0.013587408 | 0.013693441 |
| Fresh session | 0.014562631 | 0.014562923 | 0.014562815 | 0.014148775 | 0.014131934 |
| Renderer state | 0.019688750 | 0.020619877 | 0.020533783 | 0.020137314 | 0.020152252 |
| New pairs | 0.024374999 | 0.029353385 | 0.029641408 | 0.025296319 | 0.025579328 |
| Full-eye renderer | 0.019079776 | 0.018713259 | 0.019008374 | 0.019049668 | 0.019884635 |

At step 1,200 the arm was `+0.000295115` worse than the control on the
full-eye cohort; at step 1,600 it was `+0.000834967` worse. The unweighted
old-six mean was also worse by `+0.000035158` and `+0.000071590` at those
steps. No evaluation passed the all-seven strict improvement rule, so neither
run produced a promoted checkpoint. The best ordinary 1x value in this pair
remains the common base renderer-pilot value `0.013283717`, which is
`0.006283717` above the goal `0.007`.

The learned renderer stem was not dead: at the arm endpoint its 17-channel
weight slice had L2 `0.4423448`, maximum absolute weight `0.0261880`, and
nonzero fraction `1.0`. On the four held-out full-eye streams, replacing the
real G-buffers with zeros changed predictions by mean absolute `0.00288336`
(maximum `0.0612690`), but the real-conditioning endpoint was `0.019884635`
MAE versus `0.018931382` with zeros. The branch therefore learned a material
but misdirected response under this data, alignment, single-stem injection,
and training mixture; more steps on this exact arm are not evidence-backed.

As a cheaper cross-check, a train-only ridge fit on 537,600 sampled 128x128
pixels was used to predict teacher-minus-input residuals. An input-only fit
gave downsampled held-out MAE `0.0350676`; adding all 17 G-buffer channels
gave `0.0364022` (worse by `0.0013347`). This is not an official 512x512
acceptance metric, but it is consistent with the trained arm's material yet
misdirected response and argues against immediately widening the same
conditioning path on this small session.

### Reproducibility and decision

The arm endpoint was independently replayed with exact metrics:

- Checkpoint: `C:\OpenNR\Training\semantic_renderer_conditioned_pair_20260909\arm\last.pt`
- Checkpoint SHA-256:
  `ba98700b0d28fd518f03679aa8e43b8a7c2a6617adcfc12e085d1fa0e5a13263`
- Independent verifier result:
  `C:\OpenNR\Training\semantic_renderer_conditioned_pair_20260909\arm_independent_replay\result.json`
- Independent `max_difference`: `0.0`
- Control endpoint SHA-256:
  `536e104382dd4a64b59a01411888c3e61102d95f3350120c6c67f95cdbf479ef`

This arm is rejected for promotion but retained as a useful negative result:
native G-buffer content is present and learnable, yet a small single-stem
semantic injection does not solve the teacher color/appearance gap or the
ordinary MAE target. No production model, Feature 18 resource, runtime DLL,
MGO profile, or Skyrim capture path was changed.

## Superseding acceptance snapshot — 2026-09-09

| Axis | Current state after Experiment D |
| --- | --- |
| Source/config/package health | New cache builder, semantic renderer head, matched trainer, and independent verifier compile and complete. Existing source captures/caches remain hash-bound and unchanged. |
| Offline ordinary 1x MAE | Goal unmet. Best current ordinary cohort remains `0.013283717`; no current checkpoint reaches `<=0.007`. |
| Temporal stability | The base joint candidate still has the strongest six-cohort temporal-delta evidence. Experiment D arm deltas were mixed and is not promoted. No same-current-frame renderer reset/warm pair exists for the 0.5.7 tranche. |
| Teacher visual/color match | Not accepted. The G-buffer arm changed outputs materially but worsened held-out full-eye MAE; no visual promotion is justified. |
| Stereo / headset / audible / UI | Not tested in this continuation. |
| Runtime / deployment / VR budget | No export, engine replacement, Skyrim launch, or live frame-budget claim. |

## Storage and Runpod after Experiment D

The renderer overlay added about `0.73 GiB` to C:. The successful training
pair added about `1.11 GiB` including two 592 MiB checkpoints and reports. C:
still had approximately `300.3 GiB` free at the end of the run; D:, E:, and
G: remained approximately `37.9`, `31.1`, and `18.9 GiB` free respectively.
No raw capture, accepted cache, checkpoint, or provenance directory was
deleted. The first failed overlay preflight left an incomplete scratch
directory at `C:\OpenNR\TrainingCache\full_eye_renderer_conditioning_strict_20260909`;
it was not used, and it was retained rather than risking an unverified cleanup.

The local RTX 5070 Ti completed both matched arms and the independent replay
within the available VRAM. Runpod remained unused: the experiment did not
need more VRAM, and renting a remote GPU would not address the observed
conditioning/data mismatch. The stated remaining credit is preserved.

## Next evidence-backed move

Do not deploy the Experiment D endpoint or spend the remaining Runpod credit
on another copy of this training arm. The next quality experiment should use a
new, broader user-launched capture contract with true full-eye RGB, native
Feature-18 guides, renderer conditionings, exact reset metadata, and
sequence-disjoint scene/session diversity on every contiguous frame. The
capture should also preserve the teacher's relevant carried-state inputs or a
validated state-distillation target if that becomes available; the current
G-buffer metadata explicitly exposes neither teacher history nor a single
lighting-only tensor. Until that evidence exists, more local steps, width
scaling, or another blind cloud run are unlikely to close the gap from
`0.013283717` to `0.007` while preserving temporal and visual acceptance.

## Superseding capture audit and lower-I/O temporal re-arm — 2026-09-09

The user-launched full-eye every-frame contract completed two 64-frame
sequences:

| Sequence | Frames | Size | Strict temporal audit |
| --- | ---: | ---: | --- |
| `seq-1788993098503-1` | 64/64 | 13.59 GiB | rejected; host gaps through 188; backpressure 47; drops 0 |
| `seq-1788993615492-2` | 64/64 | 13.41 GiB | rejected; host gaps through 179; backpressure 94; drops 0 |

Both have initial `[true, true]` reset, contiguous `frame_id` and
`sample_index`, complete full-frame input/teacher/depth/motion for both eyes,
and six renderer-conditioning crop stages. They are retained as full-eye
spatial/teacher/color evidence, not promoted as temporal training clips. The
corrected exhaustive byte validator passes both sequences with zero errors,
missing files, duplicate IDs or duplicate hashes. It reports three all-zero
motion-vector crop warnings in sequence 1 and 67 in sequence 2, retained for
static-scene review. The renderer-conditioning stages remain explicitly
crop-only in the audit contract.

The live profile was then changed, after a byte-identical backup and with
Skyrim/SteamVR closed, to a separate crop-temporal contract. It keeps both
eyes, one 512-pixel center crop, 80 Hz, raw pre/post input and teacher, native
depth/motion, and all six renderer-conditioning crops, but sets
`capture_full_frame=false`, `capture_full_frame_sequence=false`, and
`queue_capacity=32`. The new output root is
`C:\OpenNR_Captures_TemporalCrops_EveryFrame_20260909`.

The live profile validates with no errors or warnings and has SHA-256
`6e770b9b9a193bd959b7bc404e4583ddd1472ede7c9dd00c1034ce3f97193c6d`.
Its byte-identical pre-edit backup is
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-crop-temporal-20260909\SettingsUser.before.json`
with SHA-256
`ccde5515081396076715fba06ff66430456adf50a4995ef273ba77de76762dd0`.
The disabled template is
`config/opennr_capture_temporal_crops_every_frame_20260909.example.json`.
The next burst must be audited with `validate_temporal_capture.py --mode crop`
before it is used for temporal training.

## Superseding crop-temporal capture acceptance — 2026-09-09

The lower-I/O crop-temporal contract produced two complete user-launched
sequences under C:\OpenNR_Captures_TemporalCrops_EveryFrame_20260909:

| Sequence | Frames | Measured size | Strict crop-temporal state |
| --- | ---: | ---: | --- |
| seq-1788995597432-1 | 64/64 | 1.19 GiB | accepted |
| seq-1788995726335-2 | 64/64 | 1.19 GiB | accepted |

The live monitor observed 128/128 committed and complete records, initial
[true, true] reset for both eyes in both sequences, reset index [0], no
mid-sequence reset, contiguous frame/sample/host IDs, host gaps exactly 1,
zero backpressure events, and zero dropped frames. The strict validator was
run with --mode crop --expected-pass-count 1 and returned
temporal_ready_sequences=2, temporal_ready=true, with zero errors and zero
warnings. The exhaustive byte validator found 2,560 artifacts with no missing
files, duplicate IDs, duplicate hashes, or all-zero images/raw payloads.

These two sequences are now eligible for the crop temporal cache/materializer
and temporal training preparation. This is a structural temporal acceptance
only; it does not yet establish temporal image quality, teacher color match,
stereo equivalence, live headset behavior, or the Ordinary 1x MAE target.
The Skyrim process was still open at audit time, so the sequences remain
provisional until the user finishes the session normally; no files should be
removed or moved before that final flush check.

## Superseding 18-sequence collection, cache, and continuation result — 2026-09-09

The earlier two-sequence section above is historical. The user finished the
capture session, and the authoritative root now contains 18 complete
crop-temporal sequences:

C:\OpenNR_Captures_TemporalCrops_EveryFrame_20260909

The strict crop validator accepted 18/18 sequences and 1,152/1,152 frames.
Every sequence has the required initial [true, true] reset, no mid-sequence
reset, contiguous frame/sample/host IDs, zero backpressure, and zero dropped
frames. Both eyes are present for 2,304 eye rows. The exhaustive validator
checked 23,040 artifacts with zero missing files, duplicate IDs, duplicate
hashes, all-zero primary images, or errors. Its eight all-zero raw warnings
are low-information auxiliary records; raw-content audit found zero all-zero
or invalid motion eye rows. Conditioning audit found 18,432 records with zero
nonfinite values and one localized eight-record gbuffer_specular outlier.

The all-18 cache is complete and hash-bound at:

C:\OpenNR\TrainingCache\crop_temporal_every_frame_20260909_all18

It is schema 2, has RGB shape [2304, 2, 3, 512, 512], guide shape
[2304, 5, 128, 128], context shape [2304, 8, 96, 96], and a sequence-disjoint
11/3/4 train/validation/test split. Invalid depth and motion values are zero,
all arrays are finite, and temporal training is allowed. The candidate manifest
and cache hashes, plus the complete audit details, are in the
[crop-temporal continuation report](CROP_TEMPORAL_CONTINUATION_20260909.md).

Two matched local continuation probes were then completed from the protected
step-800 base checkpoint. The 15% arm ran to absolute step 1,600; the
conservative 5% arm ran to step 1,200. Neither passed the protected
all-cohort no-regression gate:

| Run | Renderer-pilot MAE | New-crop MAE | Old-six mean | Decision |
| --- | ---: | ---: | ---: | --- |
| Protected base, step 800 | 0.013283715 | 0.016768350 | 0.017770065 | Active best |
| 15% control, step 1,600 | 0.013494855 | 0.017329732 | 0.018232937 | Rejected |
| 15% arm, step 1,600 | 0.014186551 | 0.016979217 | 0.019845464 | Rejected |
| 5% control, step 1,200 | 0.013707421 | 0.017779784 | 0.017882933 | Rejected |
| 5% arm, step 1,200 | 0.014096768 | 0.017965010 | 0.018169616 | Rejected |

The independent held-out crop replay gives the 15% arm at step 1,600 the best
isolated crop MAE, 0.018912105, but its protected validation regression and
slightly worse temporal delta prevent promotion. The 5% control is marginally
better than its paired arm on the held-out crop test, so the small signal is
not robust enough to attribute to the new data.

The ordinary 1x target remains MAE <= 0.007. The active best is unchanged;
no capture, checkpoint, runtime, profile, or deployment was promoted. The
capture is structurally ready, but the visual/color, stereo, live-headset,
runtime, and VR-budget axes remain unaccepted. The detailed tables, exact
checkpoint identities, independent replay values, and next experiment are in
the [authoritative crop-temporal continuation report](CROP_TEMPORAL_CONTINUATION_20260909.md).

## Sparse full-eye anchors and paired training result — 2026-09-09

The live profile was corrected after Skyrim/SteamVR were closed to avoid the
unusable full-eye-every-frame I/O pattern. The current profile is documented in
the [sparse full-eye anchor capture record](SPARSE_FULL_EYE_ANCHOR_CAPTURE_20260909.md)
and writes to:

`C:\OpenNR_Captures_TemporalCrops_SparseFullEye_20260909`

The tranche contains 8 complete 64-frame sequences (512 frames, 1,024 eye
rows, approximately 11.03 GiB). Crop mode accepted all 8 sequences with the
required initial `[true,true]` reset, contiguous frame/sample/host IDs, zero
drops, and zero backpressure. The exhaustive byte audit found no missing files,
duplicate IDs, duplicate hashes, or hard errors. One sequence,
`seq-1789007322591-8`, was excluded from training after the decoded raw-motion
audit found 7 invalid motion eye rows and 1,550,054 invalid motion pixels.
It remains preserved as diagnostic/test-side material. The remaining clean-7
manifest and raw-crop cache are:

- `C:\OpenNR\Training\sparse_full_eye_anchor_candidate_manifest_clean7_20260909.json`
- `C:\OpenNR\TrainingCache\sparse_full_eye_anchor_crop_clean7_20260909`

The clean-7 cache has 7 sequence-disjoint sequences, 448 frames, 896 eye rows,
and train/validation/test eye-row counts of 512/128/256. Invalid depth and
motion values are zero in the cache, `temporal_training_allowed=true`, and the
test split was not read by training. The periodic profile provides one native
full-eye anchor at sample 64 of each burst; intervening samples provide the
normal 512-pixel crop resources. Consequently this is useful crop-temporal
training data with occasional whole-eye anchors, not continuous full-eye
supervision on all 64 frames.

Two paired arms were trained from the protected step-800 best checkpoint with
the same 800-step schedule (absolute endpoint 1,600), six immutable old
cohorts, and no test usage:

| Arm | Renderer-pilot MAE | Sparse clean-7 MAE | Old-six mean | Gate |
| --- | ---: | ---: | ---: | --- |
| Protected step-800 base | 0.013284013 | 0.025991588 | 0.017770116 | Active control |
| Control, no new samples | 0.012795801 | 0.027260228 | 0.017518655 | Isolated control |
| Arm, 15% sparse clean-7 samples | 0.013300810 | 0.015459851 | 0.018101156 | Rejected |

The new data therefore carries real learnable signal: the sparse clean-7
validation MAE improved by about 40.5% relative to the starting base. It is not
yet enough to meet the ordinary target, and the arm is not a broad no-regression
improvement: renderer-pilot is slightly worse than the base, renderer-state
and fresh-session are also worse, and the prior/new-pairs tradeoff is not
uniform. The control also improved renderer-pilot, so the renderer-pilot gain
cannot be attributed to the new tranche. Neither checkpoint was promoted; the
protected best remains immutable at
`C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`.

Run artifacts and hashes are retained under:

`C:\OpenNR\Training\semantic_sparse_full_eye_anchor_clean7_pair_20260909`

- control step-1,600 checkpoint SHA-256:
  `9B7AFD23CF9E91D3F21B03614F20D9AB327105D64FBA248228317B6344BC71C8`
- arm step-1,600 checkpoint SHA-256:
  `2C30C45E3710CD87FCBE96CCCAE9DB3FD8A81F315F75F57EEE4B46839D9E59E7`
- clean-7 manifest SHA-256:
  `580B11D69AD2908B1571AD8D1DA21C3DDFB7ADE37313D3A86337249D219B7A57`

The result supports a targeted follow-up rather than blind repetition: either
continue the isolated arm at a lower adaptation rate/replay ratio to test
whether the old-cohort regressions recover, or collect more sequence- and
scene-disjoint anchors with repeated native full-eye checkpoints within a
burst. Do not switch to full-eye-every-frame capture; its timing/I/O profile
was already rejected. No Runpod credit was used, and no raw control or
checkpoint was deleted.

The registered initialization study is documented in the
[scratch-versus-fine-tune plan](SCRATCH_VS_FINETUNE_PLAN_20260909.md). It will
compare an identity-safe fresh trainable parent/head against a matched
protected-best fine-tune on the same seven-cohort schedule after the current
long continuation completes.

## Long sparse-anchor continuation result — 2026-09-10

The 15% clean-7 sparse-anchor arm was extended from the protected step-800
checkpoint to absolute step 2,400, with a paired no-new-data control. Both
arms used the same six old cohorts, the same precomputed window schedule, the
same 800-step starting replay, and the same validation-only evaluation. Peak
training allocation was approximately 9.92 GiB; no Runpod credit was used.

The extension confirms that the new tranche is learnable but not yet a broad
replacement for the protected best. The arm reached its best renderer-pilot
value at the intermediate absolute step 2,000 (0.012765102), then moved to
0.012384929 at step 2,400. The sparse clean-7 validation continued improving
to 0.013534428, but renderer-state and new-pairs remained above their
protected references. The apparent renderer-pilot improvement is also not
uniquely attributable to clean-7 because the paired control improved on that
cohort as well.

| Arm / absolute step | Renderer-pilot | Sparse clean-7 | Old-six mean | Renderer-state | New-pairs | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Protected step 800 reference | 0.013284013 | 0.025991588 | 0.017770116 | 0.019688772 | 0.024375100 | Active control |
| Control, step 2,000 | 0.012387305 | 0.028663357 | 0.017848102 | 0.020038451 | 0.026751464 | No broad gate |
| Arm, step 2,000 | 0.012765102 | 0.015450717 | 0.017994706 | 0.020662519 | 0.026598332 | No broad gate |
| Control, step 2,400 | 0.013167436 | 0.027897461 | 0.017514416 | 0.019124722 | 0.024679124 | No broad gate |
| Arm, step 2,400 | 0.012384929 | 0.013534428 | 0.017738588 | 0.019751414 | 0.026890481 | Rejected |

Relative to the protected step-800 reference, the step-2,400 arm improved
prior by 4.96%, high-effect by 3.52%, renderer-pilot by 6.77%, fresh-session
by 2.55%, and clean-7 by 47.93%. It regressed renderer-state by 0.32% and
new-pairs by 10.32%, so it fails the predeclared old-cohort no-regression
gate. The non-monotonic 2,000-to-2,400 movement is additional evidence
against an unmonitored 50,000-step fit on this small tranche.

The exact continuation artifacts are retained under:

`C:\OpenNR\Training\semantic_sparse_full_eye_anchor_clean7_long_pair_20260909`

- control step-2,400 checkpoint SHA-256:
  `E45F61D934744ACB987D5FB3107FFED37C71946DA432C01142E1F485829FB3EB`
- arm step-2,400 checkpoint SHA-256:
  `8255DA2093C8284B459004AF7907FAE4E3E4B1A0A24353EE94614196D58F7C76`
- control history SHA-256:
  `445FE8792A9BBB6A884FD486773BB54A6C32A84589CF71F2D990597312A61BB3`
- arm history SHA-256:
  `421BA151808D127071175133AACF829780FCD6649CEBED770D876930550077F2`

No continuation checkpoint was promoted. The protected best remains
immutable. The next experiment is the isolated initialization study described
in the scratch plan, implemented by
`tools/train_semantic_scratch_vs_finetune.py`.
