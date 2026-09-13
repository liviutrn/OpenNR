# Runpod Arm-C seed confirmation — OpenNR 0.5.5 — 2026-09-07

Status: complete. The secure RTX 5090 completed the 1,000-step seed-338
confirmation, artifacts were recovered and SHA-256 verified, and the Pod was
deleted. Seed 337 Arm C remains the selected candidate because seed 338 did
not beat it on both validation cohorts. This was a confirmation run for the
first recipe that produced a real two-cohort validation gain, not a new blind
width ladder.

## Question and gate

Does the selected `192/6 + 96/3` capacity recipe reproduce its validation gain
under a different random seed when the data, loss, sampling, initialization,
architecture, and step budget remain fixed?

The run passes only if its recovered `best_mae.pt` independently beats the
exact v65 parent on both the prior and new validation cohorts. A result that
improves only one cohort is rejected. A result that beats v65 but loses
materially to the seed-337 Arm C result on either cohort is retained as
diagnostic evidence and is not used to justify a longer cloud run.

Test data remains untouched during the run. No production or MO2 installation
is allowed.

## Candidate and fixed recipe

| Field | Value |
| --- | --- |
| Parent | v65 `best_mae.pt`, SHA `5672252b438669169d8b2fed9ffb16f20768270f01d79dc924f32b9318fbc3e3` |
| Capacity | width `192`, blocks `6`, extra width `96`, extra blocks `3` |
| Initialization | `--fresh-capacity-init`; common inherited base/temporal function; zero output heads |
| New seed | `338` (seed 337 remains the completed reference) |
| Steps | `1,000`, validation every `100` |
| Window / burn-in / batch | `8 / 2 / 2` |
| Temporal mixture | prior cache plus new clean temporal cache at probability `0.35` |
| Spatial mixture | new all-crop spatial-only cache at probability `0.25` |
| Loss | v65 recipe: feature `.05`, VGG `.10`, tone `.10`, effect power `.10` with power `4`, identity `.75` threshold `.05`, micro-identity `1.0` threshold `.01`, delta `.12` |
| Rates | base `1e-7`, temporal `1e-6`, capacity `2.5e-6` |
| Gates | residual and final gate enabled; delta scale `.12` |
| Test | not read; validation selection only |

The source cache manifests are immutable and remain the same as the completed
width run:

- prior rows SHA-256: `0aeffc9bfce46e2a9d8da05a7039e3ca73df3fa083c0db0daa01984f058b5410`;
- new temporal rows SHA-256: `030a856cdcf4bc0cb8b5eac1bdf3dd4015dfbb79ed7726e4d80a266b4cbeb2bd`;
- spatial rows SHA-256: `74351fc4c6e3e83816e6be45a8d3f607c62b96a6183dcdb663974248a345af46`.

The seed-337 Arm C reference is preserved at
`E:\OpenNR_Training\runpod_latest_cache_width_ablation_0.5.5_20260907\arm_C\best_mae.pt`.
Its local independent validation is `0.019690728` prior and `0.019369167`
new; its frozen merged test is `0.021328798`.

## Hardware and cost guard

The first choice is a secure RTX 5090: 32 GB, catalog price `$0.99/hr`,
current availability `MEDIUM`. The same selected model used about 24.35 GB of
device memory on the previous L40S run with batch 2, so the 5090 is expected to
fit, but a short calibration is mandatory. If it cannot initialize or sustain
the recipe, stop and fall back to a secure L40S (48 GB, `$1.09/hr`, current
availability `HIGH`).

Use one temporary `120 GB` Pod volume mounted at `/workspace`. Create the
volume before uploading data, transfer the three caches and parent, and verify
every uploaded cache file plus the parent checkpoint before training. The
temporary volume is disposable and must not be treated as the only archive.

The incremental guard for this confirmation is approximately `$2` including
upload/setup, calibration, 1,000 steps, artifact recovery, and cleanup. Stop
the GPU immediately after verified recovery. The account-level Runpod billing
snapshot after the previous experiment was `$2.0670` across the recent Pods;
the exact wallet balance is not exposed by the MCP readout.

## Acceptance and follow-up

Recover `run.json`, `history.jsonl`, `status.json`, `best_mae.pt`,
`best_feature.pt`, `best_old_domain.pt`, `best_new_domain.pt`, and `last.pt`.
Verify sizes and SHA-256 before deleting the Pod. Evaluate the selected
checkpoint independently on both validation cohorts and record effect bins.

- If seed 338 beats seed 337 and v65 on both cohorts, use the better robust
  Arm-C recipe for a longer continuation or a carefully initialized depth test.
- If it beats v65 but not seed 337, keep seed 337 as the selected candidate and
  do not spend on a longer run until the training variance is understood.
- If it fails v65 on either cohort, reject the capacity-only direction and
  reserve the remaining budget for new renderer-derived conditioning/data.

All results are offline research evidence. They do not establish Feature 18
semantics, stereo delivery, headset quality, compositor behavior, or VR
frame-time acceptance.

## Live staging record — 2026-09-07 UTC

The confirmation Pod was created only after this plan was written:

- Pod `10quqrgy0m9e5n`, secure RTX 5090, catalog `$0.99/hr`;
- actual runtime reports `32,607 MiB` GPU memory and CUDA `13.0`;
- temporary `120 GB` `/workspace` volume and `20 GB` container disk;
- direct SSH route `217.138.104.123:10207`;
- source and v65 parent staged first; parent SHA-256 matches the immutable
  v65 hash exactly;
- the three cache transfers are running as 24 bounded SCP streams;
- no training process has been started while the cache transfer is incomplete.

At `08:59:37 UTC`, the new temporal cache was complete. The old and spatial
RGB arrays were still transferring (`7,050,100,736` and `7,936,704,512`
bytes respectively); `/workspace` was at `37 GB` used of `120 GB`. The Pod
remains inside the cost guard while staging continues.

## Cache verification and code-bundle correction — 2026-09-07 UTC

Staging completed after the progress note above. The three large RGB arrays
now match their expected byte sizes exactly:

- prior RGB: `58,586,038,400` bytes;
- new temporal RGB: `5,637,144,704` bytes;
- spatial RGB: `25,769,803,904` bytes.

The transferred prior/new/spatial RGB SHA-256 values match the local source
hashes (`355b1ac3...417f`, `407fec79...35ef5`, and `89ccd217...8abe`,
respectively). The immutable row-manifest hashes also match the three source
cache contracts listed above.

The first cache smoke check exposed a code-bundle omission: the trainer's
import graph required `student_v4.py`, which in turn required `student_v3.py`.
Those two source files were uploaded without changing the local tree or the
cache. The smoke check then passed, confirming 94 prior validation streams,
10 new validation streams, 10,240 spatial training patches, and the expected
RGB/guide shapes. No training process has started yet; the Pod remains inside
the cost guard.

## Calibration and launch — 2026-09-07 UTC

A fresh 50-step calibration completed on the RTX 5090 before the confirmation
run. It used the exact seed-338 recipe and reached `17.60 GiB` peak allocated
VRAM with no OOM, NaN, or data-loader error. The calibration's step-50
validation was `0.019894638` prior and `0.019933221` new, with merged
validation MAE `0.019898348`; these values are a fit/readiness check, not the
confirmation result.

The full 1,000-step seed-338 run was launched in
`/workspace/runs/seed338` at approximately `12:16 UTC`. Its step-0
independent-in-trainer validation reproduced the expected initialization
within run-to-run evaluation noise: `0.019960047` prior and `0.020019995`
new. The Pod remains active only for this pre-registered run and subsequent
artifact recovery/verification.

## Recovered result and independent decision — 2026-09-07 UTC

The run completed at 1,000 steps in `717.88` seconds including its final
validation. The trainer's selected checkpoint is step `500`, recovered at
`E:\OpenNR_Training\runpod_arm_C_seed338_confirmation_0.5.5_20260907\seed338\best_mae.pt`.
Its SHA-256 is
`d5b2f50062e8750f0fda78f0de5d3f267205bba870806eb66060c5671aaa99d2`.
All eight requested artifacts were recovered and each matched its remote
SHA-256 before Pod deletion.

Independent local validation used the same streaming evaluator and immutable
source row manifests:

| Candidate | Prior validation MAE | New validation MAE | Decision context |
| --- | ---: | ---: | --- |
| v65 parent | `0.019805003` | `0.019977055` | baseline |
| Seed-337 Arm C | `0.019690728` | `0.019369167` | selected reference |
| Seed-338 Arm C | `0.019714982` | `0.019330343` | beats v65; does not beat seed 337 on both |

Seed 338 therefore passes the broad v65 two-cohort gate but fails the stronger
replication gate against the seed-337 Arm C reference: it is `0.000024253`
worse on the prior cohort and `0.000038824` better on the new cohort. The
seed-337 Arm C checkpoint remains the selected offline research artifact, and
no longer cloud continuation is justified by this run.

Effect-band results preserve the reason for that decision. For the prior/new
cohorts respectively, seed 338 gives student MAE `0.007083` / `0.007556` in
the `0–0.01` band versus identity MAE `0.004619` / `0.004720`; the low-effect
regression remains. In the `0.05–0.1` band it gives `0.041275` / `0.038103`,
and in the `>=0.1` band `0.073737` / `0.075670`. These are broadly consistent
with seed 337, not evidence of a new capacity regime.

A matched frame-32 new-validation visual sheet is retained at
`E:\OpenNR_Training\runpod_arm_C_seed338_confirmation_0.5.5_20260907\visuals\new_validation_frame32\seed338.png`.
At sheet scale it shows no obvious teacher-resemblance regression, but this
is offline visual evidence only; it does not establish Feature 18 semantics,
stereo delivery, headset quality, compositor behavior, or VR frame-time
acceptance.

The Pod was deleted only after recovery and verification. The latest billing
snapshot attributes about `$3.445` to Pod `10quqrgy0m9e5n`; the long cache
upload window dominated this cost. The earlier `$3.024` figure was a lagging
partial snapshot. No active Pods remain.
