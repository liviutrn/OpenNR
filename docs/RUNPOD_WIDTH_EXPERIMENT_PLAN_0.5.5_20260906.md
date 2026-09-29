# Runpod Capacity-Width Experiment Plan — OpenNR 0.5.5

Status: first pass complete. The pre-registered A/B/C ladder, fixed validation visual checks, and one frozen test evaluation ran on the temporary secure A6000 Pod in `CA-MTL-3`. The Pod and temporary volume were deleted after SHA-256-verified artifact recovery. C was the combined validation winner at step 500 (`0.01783012` MAE) and scored `0.01920839` MAE on the untouched test split. Full width support remains provisional because C did not improve the historical validation cohort and effect-band metrics were not logged in this first pass.

## Question

Does giving the learned capacity branch more channels at each layer improve
imitation of the DLSS 5 teacher, when the base renderer-facing student,
temporal branch, data, objective, sampling, initialization function, and
training budget are held constant?

The primary factor is capacity-branch width. Block depth is held constant in
the first experiment so that a result can be attributed to width rather than a
width-plus-depth change.

## Hard cost guard

- The authenticated Runpod console showed **$10.00** before storage
  provisioning and now shows **$9.99**; the latter is the live balance used
  for the remaining budget guard.
- The Runpod billing API reports **$0.00 usage in the current monthly window**;
  that endpoint does not expose the wallet balance, so the console balance is
  the authoritative balance check used here.
- The experiment must stay below the original $10 balance. The working gate
  is a maximum of **6 hours of billable Pod lifetime** at the conservative
  **$0.54/hour all-in estimate**, with a reserve for storage, setup, transfer,
  and cleanup. No second GPU or larger model is started if the measured pilot
  projects beyond that gate.
- The volume is temporary. After result files have been copied back and
  verified locally, it should be deleted so a short experiment does not become
  a continuing storage charge.

## Current, verified inputs

Parent checkpoint:

- `E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt`
- SHA-256: `5672252B438669169D8B2FED9FFB16F20768270F01D79DC924F32B9318FBC3E3`
- Architecture: `context_v7_capacity_temporal`
- Current parent configuration: base width 64 / 3 blocks; temporal hidden 64,
  downsample 8; capacity width 128 / 6 blocks; extra capacity width 64 / 3
  blocks; residual and final gates enabled.
- Parameters: 2,936,659.

Strict combined cache:

- `E:\OpenNR_RawCropCache_StrictCombinedFresh_0.5.5_20260906`
- 25,472 eye rows: 16,128 train / 4,096 validation / 5,248 test.
- Strict reset and sequence provenance are retained; `test_used_for_tuning`
  remains false.
- Local size: approximately 44.79 GiB.

Spatial auxiliary cache used by the selected v65 recipe:

- `E:\OpenNR_FullResMasterSpatialAux_0.5.5_20260906`
- Local size: approximately 1.67 GiB.
- It is training-only spatial auxiliary data; it is not a temporal validation
  or test source.

The raw capture roots are not copied to Runpod. The cache, auxiliary cache,
parent checkpoint, source tools, manifests, and experiment metadata are
sufficient for this training/evaluation run.

## Hardware and storage choice

Live Runpod catalog observations used for this design:

- NVIDIA RTX A6000, 48 GB, community Pod rate **$0.33/hour** and secure Pod
  rate **$0.53/hour**; its live per-data-center availability is LOW in
  `CA-MTL-3`.
- RTX 4090, 24 GB, community Pod rate **$0.34/hour** and secure Pod rate
  **$0.74/hour**; it is a consumer card and is not the selected professional
  path.
- RTX 5090, 32 GB, community Pod rate **$0.69/hour** and secure Pod rate
  **$0.99/hour**; its live stock is in European data centers, not alongside the
  selected North American standard volume.
- The A40 is professional and has 48 GB, but its U.S. stock is in `US-MO-1`,
  which has no network-volume tier, so it cannot satisfy the persistent-storage
  requirement here.
- The earlier local 192-wide/8-block plus 96-wide/4-block attempt reached a
  measured allocator peak of about 17.08 GiB on a 16-GB-class GPU and was
  interrupted after step 1. A 48-GB A6000 provides substantial headroom for
  the first width-only ladder and is a more professional platform.
- 16-GB and 20-GB choices are excluded. A 4090 or 5090 is not a fallback for
  this volume because the selected professional/storage pairing must remain
  co-located.

Storage is created before compute:

- 64 GB **STANDARD** network volume.
- Data center: `CA-MTL-3`, selected because it supports standard network
  volumes and is one of the live A6000 data centers.
- Created volume id: `wr75h57ivf`, name
  `opennr-width-0-5-5-20260906-camtl3`.
- Pod mount: `/workspace`.
- Payload estimate: 44.79 GiB combined cache + 1.67 GiB spatial cache + less
  than 1 GiB of code, checkpoints, logs, and manifests, leaving roughly 13 GiB
  on a 64-GB decimal volume.
- Standard storage is shown in the Runpod console as **$0.07/GB/month for the
  first 1 TB**. A 64-GB volume is therefore about $4.48/month if retained for
  a full month; the short-run charge is expected to be prorated. The volume
  is deleted after verified artifact recovery.

The current deployment form, with the existing volume attached, quotes the
Pod at **$0.53/hour** (GPU line shown as $0.53/hour, container disk line
$0.004/hour, with the network-volume storage rate separately shown as about
$0.007/hour in the create/attach flow). The conservative budget calculation
uses **$0.54/hour** so rounding and the separate storage meter cannot push the
run over the guard.

## Width ladder

All arms use base width 64 / 3 blocks, temporal hidden width 64 with downsample
8, the same gates, the same delta scales, and the same loss/sampling recipe.
Only the capacity and capacity-extra channel widths change. Depth remains 6 /
3 for every arm.

| Arm | Capacity width | Capacity blocks | Extra width | Extra blocks | Parameters | Role |
|---|---:|---:|---:|---:|---:|---|
| A | 128 | 6 | 64 | 3 | 2,936,659 | current-width control |
| B | 160 | 6 | 80 | 3 | 3,188,083 | intermediate width |
| C | 192 | 6 | 96 | 3 | 3,480,979 | wide width |

The guide's former v54 shape, 192 / 8 plus 96 / 4, is approximately 3.76M
parameters but changes depth as well as width. It is deliberately reserved as
a follow-up confirmation, not mixed into this first causal width test.

## Initialization and training controls

Each arm uses the same v65 parent checkpoint only for its inherited
base/temporal function. The capacity and extra-capacity branches are rebuilt
from their deterministic constructor initialization with the same seed (337),
and their zero-initialized output heads keep the starting function equal to the
inherited base/temporal parent. No learned v65 capacity tensor is loaded into
one arm but not another.

The local trainer's `--fresh-capacity-init` path records this choice in
`run.json` and fails if a non-capacity parent tensor is incompatible. This is a
controlled continuation initialization, not a claim that the width arms start
with the full v65 capacity solution.

Fixed recipe, copied from the current v65 schedule:

- strict temporal cache, `train` split only;
- validation on the untouched `validation` split; test is not used for
  selection;
- spatial auxiliary sampling at probability 0.5, training-only;
- window 8, burn-in 2, batch 2;
- base LR `1e-7`, temporal LR `1e-6`, capacity LR `2.5e-6`;
- feature weight 0.05, VGG weight 0.10, tone weight 0.10;
- signed effect-power weight 0.10 with power 4;
- identity weight 0.75 at threshold 0.05;
- micro-identity weight 1.0 at threshold 0.01;
- delta weight 0.12; residual delta scale 0.12;
- validation every 100 steps; seed 337; no `--fit-all-nontest`.

## Execution stages

1. Create and verify the 64-GB standard network volume. Do not create a GPU
   Pod before this succeeds.
2. Place one RTX A6000 Pod in the volume's data center and attach the volume at
   `/workspace`. Use the official Runpod PyTorch 2.8 image and verify the final
   on-demand checkout quote before deployment.
3. Copy only the declared inputs and source files; verify sizes and SHA-256
   before training.
4. Run a short, unscored calibration (50 steps of arm C) to measure actual
   seconds/step, peak GPU memory, data throughput, and checkpoint health.
5. If the measured projection for A+B+C at the target budget plus setup stays
   within the 6-hour Pod-lifetime gate, run **1,000 steps per arm** with the
   same Pod, sequentially. Otherwise run the pre-declared 500-step ladder or
   stop before exceeding the cost gate; do not silently upgrade hardware.
6. Select checkpoints using validation only. Record the best validation MAE,
   feature distance, loss components, and the full validation effect bands:
   0–0.01, 0.01–0.025, 0.025–0.05, 0.05–0.1, and >0.1 teacher-effect magnitude.
7. Only after selection is frozen, evaluate each selected checkpoint once on
   the 5,248-row test split, broken out into fresh and historical cohorts.
8. Benchmark parameter count and mixed-precision inference milliseconds for A/B/C. This
   is a quality/compute comparison; it is not evidence of live stereo,
   headset, compositor, or VR-budget acceptance.
9. Copy checkpoints, manifests, metrics, logs, and hashes back to the local
   workspace. Stop/delete the Pod and delete the temporary network volume only
   after the local copies verify.

## Observed results

All validation scores below use the same 4,096-frame / 32-sequence / 64-eye-
stream validation split and select the best checkpoint by validation MAE. The
test split was not used to choose the arm.

| Arm | Capacity shape | Parameters | Best step | Best validation MAE | Validation feature distance |
|---|---|---:|---:|---:|---:|
| A | 128 / 6 + 64 / 3 | 2,936,659 | 500 | 0.017835582 | 0.0879* |
| B | 160 / 6 + 80 / 3 | 3,188,083 | 500 | 0.017831308 | 0.0879* |
| C | 192 / 6 + 96 / 3 | 3,480,979 | 500 | **0.017830116** | 0.0877 |

`*` The archived per-step feature values are retained in each arm's
`history.jsonl`; the primary selection metric for this ladder is validation
MAE. C improves over A by approximately `0.0306%` relative and over B by
approximately `0.0067%` relative. The direction is consistent with a small
capacity benefit, but the C-versus-B margin is very small and should not be
treated as a large visual-quality gain.

At the common best step (500), the validation cohort breakdown is not
directionally consistent: A/B/C score fresh strict MAE of `0.015554553`,
`0.015541384`, and `0.015525845`, but historical strict MAE of `0.021637298`,
`0.021647849`, and `0.021670569`, respectively. C therefore gains on the
fresh cohort while regressing on the historical cohort; the combined-set win
is driven by the fresh-cohort weighting rather than a uniform improvement.

The selected C checkpoint was evaluated once on the untouched test split:

- 5,248 frames, 41 sequences, and 82 eye streams;
- MAE `0.019208391`, PSNR `30.3644 dB`;
- input identity baseline MAE `0.026455051`;
- improvement over identity `27.3923%`;
- temporal-delta MAE `0.010315937`.

Using the immutable `cache_source` field in `rows.json`, the same C test
result breaks down to fresh strict data at MAE `0.015798842` (26 sequences,
3,328 frames) and historical strict data at MAE `0.025118279` (15 sequences,
1,920 frames). This cohort gap is much larger than the A-to-C width gain, so
cohort difficulty currently dominates the capacity signal.

The fixed validation visual sheets show A, B, and C remaining visually close
to one another and close to the input on the sampled frame; the teacher has
larger face/material/tone changes than any of these short-run students. The
sheets are offline crop-space evidence only and do not establish live stereo,
headset quality, compositor delivery, or VR frame-time acceptance.

The first pass did not log the pre-registered teacher-effect bands
(`0–0.01`, `0.01–0.025`, `0.025–0.05`, `0.05–0.1`, `>0.1`), so the formal
effect-band portion of the decision rule remains open for a follow-up run.

The A6000 run was healthy: the 50-step calibration measured approximately
`9.7 GiB` GPU use for C, and none of A/B/C encountered an out-of-memory error.
The complete 44.79-GiB combined cache and 1.67-GiB spatial auxiliary cache
were transferred and hash-verified on the volume. Recorded Runpod spend was
`$0.44496` in the available billing bucket (`$0.43562` Pod GPU, `$0.00312`
Pod disk, `$0.00622` standard storage), versus the `$10` wallet guard.

The local RTX 5070 Ti forward-only diagnostic also loaded all three best
checkpoints successfully under BF16 autocast at batch 2. Independent 100-
iteration repeats reported median batch times of approximately `18.845 ms`
for A, `17.732 ms` for B, and `18.767 ms` for C, with peak allocated memory
of `0.181`, `0.207`, and `0.235 GiB`, respectively. The runs showed large
host timing outliers, so these figures are diagnostic rather than a VR frame-
time acceptance result. They establish that forward inference is not the
same constraint as the earlier training attempt on the 5070 Ti.

Recovered artifacts are under
`E:\\OpenNR_Training\\runpod_width_a6000_0.5.5_20260906`.

## Decision rule

Width is supported only if the wider arm improves validation on the combined
set and does not merely trade away low-effect identity preservation. The result
must be directionally consistent on fresh and historical validation cohorts,
show a useful effect-band change, and be weighed against parameter count,
inference milliseconds, peak memory, and cost.

- If C clearly wins, B is an intermediate Pareto point and the v54
  width-plus-depth shape can be tested later as a separate experiment.
- If B/C are flat or regress against A, the evidence favors a conditioning,
  data, or objective change over more same-branch width.
- A good cloud MAE result remains an offline model result until a controlled
  in-headset A/B verifies temporal delivery, stereo output, visual quality,
  and VR frame-time behavior.
