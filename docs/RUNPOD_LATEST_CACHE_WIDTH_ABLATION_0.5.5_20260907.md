# Runpod latest-cache width ablation — OpenNR 0.5.5 — 2026-09-07

Status: completed on one secure L40S Pod in `US-NC-1`; the Pod was deleted
after verified artifact recovery. It was intentionally shared by all three
arms so setup and storage cost were paid once.

## Question and decision rule

This run asks whether a wider learned capacity branch improves imitation of the
Feature 18 teacher when the renderer-facing base, temporal path, data, loss,
sampling, initialization, and step budget are held constant.

The three arms differ only in capacity-branch width. Depth stays fixed at six
blocks for the main branch and three blocks for the extra branch. Every arm
uses `--fresh-capacity-init`: the parent supplies only the inherited base and
temporal function, while the capacity branches start from the same seeded
constructor state and zero-initialized output heads. This is a fair width
comparison, but not a claim that the arms start with the full learned v65
capacity solution.

Promotion requires all of the following:

1. The candidate must beat the exact v65 parent on both the prior and new
   validation cohorts, not only on their pixel-weighted merge.
2. Neither cohort may be traded away for a small merged-set gain.
3. Effect-band and visual checks must not show a low-effect identity regression
   or an obvious teacher-resemblance regression.
4. Test data remains untouched until selection is frozen; no test metric is
   used to choose an arm.

The exact v65 parent baselines on the current validation caches are:

| Cohort | Frames | v65 MAE |
| --- | ---: | ---: |
| Prior validation | 6,016 | `0.0198050034` |
| New clean high-effect validation | 640 | `0.0199770549` |

## Cloud and cost guard

Hardware:

- secure NVIDIA L40S, 48 GB class, `US-NC-1`;
- quoted GPU rate: `$1.09/hr`;
- one Pod, sequential arms, no parallel GPU rental;
- temporary 120-GB Pod volume mounted at `/workspace`;
- Pod id: `d0i8ml0q56kcug`.

The latest source caches total approximately 108.0 GB before code,
checkpoints, and logs. The original 100-GB volume could not be resized in
place, so the synthetic-only preflight Pod was terminated and this 120-GB Pod
was created before data transfer. The volume is not a persistent user archive.

The transfer route is direct SCP with AES-GCM and bounded parallel streams.
Single-stream throughput was about 0.393 Gbit/s; larger 16-stream repeats
were about 1.365 and 1.023 Gbit/s. Any speed is acceptable for this run, but
the transfer is monitored for cost. At roughly 1 Gbit/s, the declared cache
payload should take on the order of 15 minutes. The three 1,000-step arms,
calibration, evaluation, and cleanup must remain within approximately `$3–4`
of incremental experiment spend. If the projected total approaches the cap,
stop before starting the next arm and retain the completed evidence.

## Immutable inputs and staged layout

| Input | Local source | Bytes | Rows-manifest SHA-256 / checkpoint SHA-256 |
| --- | --- | ---: | --- |
| Prior strict temporal cache | `E:\OpenNR_TrainingInputs\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906` | 70,330,153,978 | `0aeffc9bfce46e2a9d8da05a7039e3ca73df3fa083c0db0daa01984f058b5410` |
| New clean temporal cache | `E:\OpenNR_RawCropCache_VariedHighEffectTemporalClean_0.5.5_20260907` | 6,767,573,396 | `030a856cdcf4bc0cb8b5eac1bdf3dd4015dfbb79ed7726e4d80a266b4cbeb2bd` |
| New all-crop spatial auxiliary cache | `C:\OpenNR_Cache_VariedHighEffectSpatialAllCrops_0.5.5_20260907` | 30,937,397,742 | `74351fc4c6e3e83816e6be45a8d3f607c62b96a6183dcdb663974248a345af46` |
| v65 parent `best_mae.pt` | `E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt` | 47,475,229 | `5672252b438669169d8b2fed9ffb16f20768270f01d79dc924f32b9318fbc3e3` |

The remote layout is:

```text
/workspace/data/old/       prior temporal cache
/workspace/data/new/       new clean temporal cache
/workspace/data/spatial/   new all-crop spatial-only auxiliary cache
/workspace/code/            selected trainer and model source files
/workspace/parent/          v65 parent checkpoint
/workspace/runs/            calibration and A/B/C outputs
```

The spatial cache is used only for training. Its `complete.json` declares
`temporal_training_allowed=false`; validation and test selection use the two
strict temporal caches only.

## Arms and fixed recipe

| Arm | Capacity width / blocks | Extra width / blocks | Approx. parameters | Role |
| --- | ---: | ---: | ---: | --- |
| A | 128 / 6 | 64 / 3 | 2,936,659 | current-width control |
| B | 160 / 6 | 80 / 3 | 3,188,083 | intermediate width |
| C | 192 / 6 | 96 / 3 | 3,480,979 | wide width |

All arms use:

- old temporal cache as `--cache`;
- new clean temporal cache with `--new-temporal-prob 0.35`;
- all-crop spatial cache with `--spatial-prob 0.25`;
- window 8, burn-in 2, batch 2;
- 1,000 steps, validation every 100 steps;
- base LR `1e-7`, temporal LR `1e-6`, capacity LR `2.5e-6`;
- feature weight `0.05`, VGG appearance weight `0.10`, tone weight `0.10`;
- signed effect-power weight `0.10`, power 4;
- identity weight `0.75` at threshold `0.05`;
- micro-identity weight `1.0` at threshold `0.01`;
- delta weight `0.12`, residual delta scale `0.12`;
- residual gate and final gate enabled;
- seed 337 and no `--fit-all-nontest`.

A 50-step arm-C calibration precedes the ladder. It records peak memory,
seconds per step, data/loader health, and checkpoint creation. A calibration
failure or projected cost breach stops the cloud run without silently changing
the declared arms.

## Recovery and acceptance

After all arms finish, recover `run.json`, `history.jsonl`, `status.json`,
`best_mae.pt`, `best_feature.pt`, `best_old_domain.pt`, `best_new_domain.pt`,
and `last.pt` for each arm. Verify file size and SHA-256 locally before Pod
deletion. Evaluate selected checkpoints on both validation cohorts and record
the effect bins `0–0.01`, `0.01–0.025`, `0.025–0.05`, `0.05–0.1`, and `>=0.1`.
Only after selection is frozen may a separate one-time test evaluation run.

Any promoted artifact remains an offline research candidate. It does not prove
Feature 18 live semantics, stereo delivery, headset quality, compositor
behavior, or VR frame-time acceptance.

## Calibration result

The 50-step Arm-C calibration completed successfully before the ladder:

- runtime: `182.8 s` including initialization and validation;
- peak allocated VRAM: `8.30 GiB` on the L40S;
- step-0 merged validation MAE: `0.0199657511`;
- step-50 old-domain MAE: `0.0199053185`;
- step-50 new-domain MAE: `0.0199315361`;
- step-50 merged MAE: `0.0199078394`;
- cache/helper contracts remained healthy and no OOM or non-finite loss
  occurred.

The measured steady training rate and validation duration project the
sequential 1,000-step A/B/C ladder, artifact recovery, and cleanup well below
the `$3–4` incremental spend guard at the quoted `$1.09/hr` GPU rate. The
calibration output is retained at `/workspace/runs/calibration_C_50` until
local recovery is verified.

## Live ladder status (2026-09-07 UTC)

Arm A (128/6 + 64/3) completed 1,000 steps in `746.7 s` without OOM or
non-finite loss. Its trainer-reported best merged validation MAE is
`0.0196736599`, with best per-domain records of `0.0197050298` on the prior
cohort and `0.0192818435` on the new cohort. These are provisional until the
same recovered checkpoint is independently evaluated locally.

Arm B (160/6 + 80/3) completed 1,000 steps in `826.5 s` without OOM or
non-finite loss. Its trainer-reported best merged validation MAE is
`0.0196658207`, with best per-domain records of `0.0196969602` on the prior
cohort and `0.0192969276` on the new cohort. The final step-1,000 evaluation
was `0.0198656868` prior, `0.0193183657` new, and `0.0198130597` merged; the
best-checkpoint records—not the final step—remain the selection candidates.

Arm C (192/6 + 96/3) completed with the identical recipe and seed. All three
arms completed without OOM or non-finite loss. The 32 recovered files match
the remote SHA-256 values exactly. The Pod was deleted only after that
verification; Runpod reports no active Pods.

## Independent validation result

The local evaluator loaded each recovered `best_mae.pt` and evaluated it at
the same selected checkpoint step (`500` for all three arms). All arms beat
the exact v65 parent on both validation cohorts:

| Candidate | Prior validation MAE | Change vs v65 | New validation MAE | Change vs v65 |
| --- | ---: | ---: | ---: | ---: |
| v65 parent | `0.019805003` | — | `0.019977055` | — |
| Arm A, 128/6 + 64/3 | `0.019705133` | `-0.000099871` (`0.504%`) | `0.019378331` | `-0.000598723` (`2.997%`) |
| Arm B, 160/6 + 80/3 | `0.019696995` | `-0.000108008` (`0.545%`) | `0.019372930` | `-0.000604125` (`3.024%`) |
| Arm C, 192/6 + 96/3 | **`0.019690728`** | **`-0.000114275` (`0.577%`)** | **`0.019369167`** | **`-0.000607888` (`3.043%`)** |

The independent result files are under
`E:\OpenNR_Training\runpod_latest_cache_width_ablation_0.5.5_20260907\local_eval`.
The selected checkpoint for every arm is a single recovered `best_mae.pt`,
not a favorable combination of separate old- and new-domain checkpoints.

## Effect-band and visual checks

Effect-bin result files are under
`E:\OpenNR_Training\runpod_latest_cache_width_ablation_0.5.5_20260907\effect_bins`.
Arm C has the best overall MAE on both cohorts, but the extreme-effect tail
is not monotonic with width:

| Cohort / band | v65 | Arm A | Arm B | Arm C |
| --- | ---: | ---: | ---: | ---: |
| New `0.05–0.1` | `0.041496` | **`0.037813`** | `0.037918` | `0.038058` |
| New `>=0.1` | `0.081168` | **`0.074500`** | `0.075043` | `0.075726` |
| Prior `0.05–0.1` | `0.043321` | **`0.040923`** | `0.041036` | `0.041193` |
| Prior `>=0.1` | `0.079527` | **`0.072297`** | `0.072936` | `0.073795` |

Every candidate still has a low-effect identity regression in the `0–0.01`
band; Arm C's new-cohort band is student MAE `0.007580` versus identity MAE
`0.004720` (`-60.6%` relative improvement). The width gain therefore improves
the full image and the middle bands, but it does not solve the low-effect
correction problem and Arm A is slightly stronger in the extreme tail.

Matched frame-32 new-validation sheets for v65 and Arms A/B/C are in
`E:\OpenNR_Training\runpod_latest_cache_width_ablation_0.5.5_20260907\visuals\new_validation_frame32`.
They replay the same three validation sequences and both eyes from a strict
reset. At the available sheet scale, no obvious teacher-resemblance regression
is visible in Arm C; this remains offline visual evidence, not live VR
acceptance.

## Frozen test transfer and decision

After validation selection was frozen, Arm C was evaluated once on the merged
test cache (`8,448` frames; rows SHA-256
`8363da3e04b58f66cd4acadb8e60648f593aacaad51945ad9cea0d59a8871e18`). The
result is
`E:\OpenNR_Training\runpod_latest_cache_width_ablation_0.5.5_20260907\test_eval_arm_C_merged\result.json`.

| Metric | v65 merged test | Arm C merged test | Change |
| --- | ---: | ---: | ---: |
| MAE | `0.021427386` | **`0.021328798`** | **`-0.000098588` (`0.460%`)** |
| PSNR | `29.5402` dB | `29.6377` dB | `+0.0975` dB |
| Temporal-delta MAE | `0.009803232` | `0.009894529` | `+0.000091297` (worse) |

Arm C is the selected offline research candidate because it is the lowest
same-checkpoint MAE on both validation cohorts and transfers a modest MAE
gain to the frozen merged test. It is not installed into SkyrimVR/MO2, and it
does not establish Feature 18 semantic correctness, stereo delivery, headset
quality, compositor behavior, or VR frame-time acceptance.

Runpod's post-deletion billing snapshot attributes approximately `$0.9541`
to Pod `d0i8ml0q56kcug` (`$0.9363` GPU plus `$0.0178` disk); billing can lag
slightly. The eight-hour Pod query total across the account's four recent Pods
was `$2.0670`, and `list_pods` returned zero active Pods.

## Next experiment direction

The width question is answered provisionally: capacity helps, but the return
from 2.94M to roughly 3.48M parameters is small and the extreme-effect tail
does not improve monotonically. The next Runpod spend should therefore start
from the selected Arm C checkpoint and target the remaining failure mode:
preserve low-effect identity while improving high-effect transfer. Candidate
recipes are a short, pre-registered effect-aware loss/sampling ablation and a
depth expansion (`192/8 + 96/4`) only if its calibration beats Arm C on both
validation cohorts. No blind wider ladder or production install is justified
by this result alone.

## Local follow-up: high-frequency effect loss rejected

To choose the next cloud direction without spending cloud budget on a weak
hypothesis, the selected Arm C checkpoint was continued locally for 400 steps
on the RTX 5070 Ti with the existing recipe plus only
`--effect-high-frequency-weight 0.05`. Batch 1 fit at `7.63 GiB` peak
allocated VRAM and the run completed without numerical errors.

The selected local checkpoint is step 100, SHA-256
`50fc80a612a9d2a7a0406f5879807ea2c397f0604a1533c58b37d47a051a43e9`. Its
independent validation was `0.0196912970` prior and `0.0193518775` new,
versus Arm C's `0.0196907281` prior and `0.0193691671` new. It improves the
new cohort but is marginally worse on the prior cohort, so it fails the
two-cohort rule and is rejected for the next Runpod run. The local pilot
artifacts are retained at
`E:\OpenNR_Training\local_effect_high_frequency_from_arm_C_0.5.5_20260907`.

The pilot's effect-band readout is retained under its `effect_bins` directory.
On the prior validation cohort, the `0–0.01` band was `0.007012` student MAE
versus `0.004619` identity MAE; on the new cohort it was `0.007520` versus
`0.004720`. The same pilot reached `0.041256` / `0.074100` in the prior
`0.05–0.1` / `>=0.1` bands and `0.038106` / `0.075968` in the new bands.
This confirms that the high-frequency auxiliary term did not repair the
low-effect identity gap without giving back whole-frame prior-cohort MAE.

## Local follow-up: doubled micro-identity rejected

While the 5090 was staging, the selected Arm C checkpoint was continued locally
for 400 steps with only `--micro-identity-weight 2.0` instead of the recipe's
`1.0`. The step-0 checkpoint independently reproduced Arm C at
`0.0196907281` prior and `0.0193691673` new. The final step-400 trainer
evaluation degraded to `0.0199544549` prior and `0.0195108640` new, so the
stronger micro-identity term is rejected as a general continuation recipe.
The complete local run and independent results are retained at
`E:\OpenNR_Training\local_micro_identity2_from_arm_C_0.5.5_20260907`.
This zero-cloud-cost pilot reinforces that the remaining error is not solved by
simply increasing the low-effect penalty; the next cloud gate remains the
pre-registered seed-338 Arm C confirmation.

## Local follow-up: conservative continuation rejected

After the two rejected loss probes, a zero-cloud-cost continuation was run on
the RTX 5070 Ti. It kept the Arm C architecture, data mixture, loss, and
sampling fixed and halved all three learning rates to
`5e-8 / 5e-7 / 1.25e-6` for 400 steps from the selected Arm C checkpoint. The
trainer kept step 0 as best; the final step-400 values were `0.0197196` prior
and `0.0193749` new, both worse than the starting point. The independent
step-0 confirmation is retained under
`E:\OpenNR_Training\local_conservative_continuation_from_arm_C_0.5.5_20260907`.
The low-LR continuation is rejected, so there is no evidence for spending more
time on the current-corpus Arm C cooldown while the seed-338 cloud gate runs.

## Seed-338 staging gate — 2026-09-07 UTC

The secure RTX 5090 confirmation Pod completed cache staging with exact byte
sizes and source-matching SHA-256 hashes for all three large RGB arrays. A
missing transitive source dependency (`student_v4.py` -> `student_v3.py`) was
found by the pod-side smoke check and corrected before training. The corrected
smoke check passed against the expected validation streams, spatial patch
count, and array shapes. The 50-step 5090 calibration has since passed and the
full seed-338 confirmation has since completed, been independently validated,
and been recovered before Pod deletion. Its result is recorded in
`docs/RUNPOD_ARM_C_SEED_CONFIRMATION_0.5.5_20260907.md`.

## Seed-338 confirmation outcome — 2026-09-07 UTC

The same `192/6 + 96/3` Arm-C recipe was repeated with seed `338` on a secure
RTX 5090. The trainer selected step `500`. Independent local validation gave
`0.019714982` prior and `0.019330343` new, compared with seed-337 Arm C at
`0.019690728` prior and `0.019369167` new. Seed 338 improves the new cohort
slightly but gives back a small amount on the prior cohort, so it does not
beat the seed-337 candidate on both cohorts and is not promoted.

The confirmation still beats v65 on both cohorts (`0.019805003` prior and
`0.019977055` new), which strengthens the conclusion that the capacity recipe
is useful. The non-replication against seed 337, together with the persistent
`0–0.01` identity regression, means the next spend should target data,
conditioning, or a loss that addresses the low-effect behavior—not another
blind width/depth continuation. The remaining Runpod budget is reserved for
the first such recipe that passes the two-cohort gate.

The seed-338 visual sheet is retained at
`E:\OpenNR_Training\runpod_arm_C_seed338_confirmation_0.5.5_20260907\visuals\new_validation_frame32\seed338.png`.
No production or MO2 installation was changed.

## Zero-cloud local follow-up: context-style modulation rejected

To use the local RTX 5070 Ti while preserving the remaining cloud budget, a
400-step pilot added the existing zero-initialized global context-style
modulation path to Arm C. Its independently selected step-300 checkpoint
measured `0.019704359` prior and `0.019328705` new, versus Arm C at
`0.019690728` and `0.019369167`. The new-domain gain (`0.000040463`) came
with a prior-domain regression (`0.000013631`), so the two-cohort gate rejects
the recipe. Artifacts and the pre-registration are retained in
`docs/LOCAL_ARM_C_STYLE_MODULATION_PILOT_0.5.5_20260907.md` and
`E:\OpenNR_Training\local_style_modulation_from_arm_C_0.5.5_20260907`.

## Zero-cloud local follow-up: global residual calibration rejected

An offline calibration diagnostic was run on the selected Arm-C checkpoint
before authorizing any further Runpod work. It fitted a single scalar `alpha`
on the combined old/new training streams and applied the frozen correction
`rgb + alpha * (prediction - rgb)` to both validation cohorts. The fit was
`alpha=1.0390703622`.

The validation result shows a cohort-specific optimum rather than a robust
global correction:

| Cohort | Arm C (`alpha=1`) | Best grid alpha | Best grid MAE | Frozen train-fit alpha | Frozen-fit MAE |
| --- | ---: | ---: | ---: | ---: | ---: |
| Prior | `0.019690745` | `0.980` | `0.019687008` | `1.039` | `0.019716425` |
| New | `0.019369241` | `1.030` | `0.019359838` | `1.039` | `0.019360261` |

The prior cohort therefore regresses by `0.000025680` under the frozen
train-fit value even though the new cohort improves by `0.000008980`. The
grid optima also point in opposite directions, so scalar effect calibration is
rejected as a general recipe and will not consume Runpod budget. The complete
train-only diagnostic is
`E:\OpenNR_Training\arm_C_effect_calibration_0.5.5_20260907\result.json`;
the frozen test split was untouched.

The next zero-cloud test is a parent-preserving depth expansion from Arm C:
`192/8 + 96/4`. Existing Arm-C blocks will be loaded, newly added block
residual scales will start at zero so the step-0 function remains Arm C, and
the candidate will be retained only if independent prior and new validation
both improve. This is a fairer capacity test than replacing a learned branch
with a fresh one.

## Zero-cloud local follow-up: depth expansion rejected

The parent-preserving `192/8 + 96/4` child completed 400 steps locally in
`485.63 s` on the RTX 5070 Ti with no OOM or non-finite loss. Step 0 was an
exact Arm-C function. The step-400 `best_new_domain.pt` was independently
evaluated at `0.019810200` prior and `0.019321325` new, versus Arm C at
`0.019690745` and `0.019369241`. The new cohort improved by `0.000047916`,
but the prior regressed by `0.000119455`; the depth expansion is rejected.
No frozen test evaluation or production/MO2 change was made. Full evidence is
in `docs/LOCAL_ARM_C_DEPTH_EXPANSION_PILOT_0.5.5_20260907.md` and
`E:\OpenNR_Training\local_arm_C_depth_expansion_0.5.5_20260907`.

## Runpod budget guard recheck — 2026-09-07 09:28 EDT

The authoritative Runpod MCP billing snapshot for the last 12 hourly buckets
(`2026-09-07T01:00:00Z` through `13:00:00Z`) reports `$6.347845` total:
`$6.221048` GPU, `$0.114352` Pod disk, and `$0.012444` standard storage.
`list_pods` and `list_network_volumes` both return zero active resources.
This is spend-to-date for the queried window, not an exact wallet balance; the
MCP billing endpoint does not expose the remaining credit. No new cloud run is
authorized until a two-cohort local winner or a valid renderer-conditioned
capture creates a defensible target for the remaining budget.

## Latest resource-safety recheck — 2026-09-07

After the user requested that all Runpod resources be stopped, `list_pods`
returned zero items and `list_network_volumes` returned zero items. There was
no live pod to stop and no persistent volume to remove; Runpod is not currently
draining credit from either resource class.

The newer billing query covered `2026-09-07T10:00:00Z` through
`2026-09-07T14:00:00Z` and reported `$2.520465` across three completed hourly
records (`$2.470697` GPU and `$0.049769` pod disk). This is a historical query
window, not a wallet-balance readout. It must not be added to the earlier
01:00–13:00Z `$6.347845` query because the windows overlap.

No cloud rental is pending. The next cloud selection should prefer a measured
transfer path near 2 Gbit/s when available, but the catalog cannot be treated
as a bandwidth guarantee; test throughput before sending a large cache and
keep the run within the remaining budget.
