# OpenNR Crop-Temporal Continuation — 2026-09-09

## Technical summary

The completed 18-sequence crop-temporal tranche is structurally valid and eligible
for temporal training, but it does not close the quality gap to the ordinary 1×
MAE target. Two matched continuation experiments were completed locally from the
protected step-800 semantic_joint_parent_v1 checkpoint. Neither new-data arm
passed the no-regression promotion gate, so the active best model is unchanged.

The strict temporal gate passed all 18 sequences: 1,152 complete frames and
2,304 eye rows, with the required initial [true, true] reset, contiguous
frame/sample/host IDs, zero backpressure, zero drops, and valid native motion
content. The raw tranche is 22,968,598,213 bytes, approximately 21.39 GiB.
This proves capture structure and content integrity only. It does not prove
teacher-like visual/color match, stereo equivalence, live headset behavior,
runtime deployment, or VR-budget acceptance.

The ordinary 1× target remains MAE <= 0.007. The protected best ordinary
renderer-pilot value remains 0.013283715, leaving a gap of approximately
0.006283715. No checkpoint from this tranche is promoted.

## Capture and data-quality findings

The authoritative raw root is:

C:\OpenNR_Captures_TemporalCrops_EveryFrame_20260909

The 18 captured sequence IDs are:

seq-1788995597432-1, seq-1788995726335-2,
seq-1788997829583-1, seq-1788997839389-2,
seq-1788997844997-3, seq-1788997851531-4,
seq-1788997856887-5, seq-1788997862357-6,
seq-1788997871691-7, seq-1788997916737-8,
seq-1788997939483-9, seq-1788997951530-10,
seq-1788997976141-11, seq-1788998036838-12,
seq-1788998045041-13, seq-1788998060899-14,
seq-1788998076382-15, seq-1788998088120-16.

| Check | Result | Evidence | Risk interpretation |
| --- | --- | ---: | --- |
| Strict crop-temporal readiness | PASS | 18/18 sequences | All sequences are eligible for temporal cache/training use. |
| Complete committed frames | PASS | 1,152/1,152 | No partial or failed frame records. |
| Both-eye rows | PASS | 2,304 | Two eye rows per committed frame. |
| Exhaustive byte validation | PASS with low-information warning | 23,040 artifacts | Zero missing files, duplicate IDs, duplicate hashes, all-zero primary images, or errors; eight all-zero auxiliary raw records were warned. |
| Raw motion content | PASS | 0 all-zero and 0 invalid motion eye rows | No primary motion-content exclusion is required. |
| Conditioning content | PASS with localized outlier | 18,432 records; 0 nonfinite | One sequence has eight all-zero/duplicate gbuffer_specular records; this is auxiliary and is retained/documented. |

The strict audit is
out/crop_temporal_every_frame_20260909/temporal_audit_all18.json.
The exhaustive audit is produced by tools/validate_capture.py; raw motion
content is recorded in
out/crop_temporal_every_frame_20260909/raw_content_audit_all18.json.
Conditioning content is recorded in
out/crop_temporal_every_frame_20260909/conditioning_content_audit_all18.json/audit.json.

## Materialized cache and split

The materialized cache is:

C:\OpenNR\TrainingCache\crop_temporal_every_frame_20260909_all18

It is schema 2 and hash-bound to the all-18 candidate manifest:

out/crop_temporal_every_frame_20260909/candidate_manifest_all18.json

| Property | Value |
| --- | --- |
| Source sequences / frames / eye rows | 18 / 1,152 / 2,304 |
| RGB array | [2304, 2, 3, 512, 512], uint8 |
| Guide array | [2304, 5, 128, 128], float16 |
| Context array | [2304, 8, 96, 96], float16 |
| Sequence-disjoint split | 11 train / 3 validation / 4 test |
| Invalid depth values | 0 |
| Invalid motion values | 0 |
| Finite RGB/guides/context | PASS |
| Temporal training allowed | YES |
| Manifest SHA-256 | ad04965821d974cf0a022bb0e2c035e36f4cf0f128d7fa67f64cdb38046c5306 |
| Row-identity SHA-256 | a3e79d701d423d325b356bacccf6090e59f4c3dad7a43ed9d46cde0c31a0657a |
| Cache complete SHA-256 | 7cb4716f28bf2ef217376c4f512532fd04e161f7173ca4b0dd09deced4c163b5 |

The cache builder and tools/test_raw_crop_cache.py both completed
successfully. The test sequences were held out from fitting and were used only
for the independent replay below.

## Paired training results

Both runs used the same verified base checkpoint, six protected old cohorts,
optimizer restoration, compound frame objective, and deterministic paired
control/arm design. The control sampled zero new crop data. The arms sampled the
new all-18 cache at the stated probability.

The protected baseline is:

C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt

SHA-256:

40c214a9c0bc214c6e1366872e6d9270bfe7c00d63797aefb6b3896865c15756

| Run | New-data probability | End step | Renderer-pilot MAE | New-crop MAE | Old-six mean MAE | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Protected base | 0% | 800 | 0.013283715 | 0.016768350 | 0.017770065 | Active control |
| 15% control | 0% | 1,600 | 0.013494855 | 0.017329732 | 0.018232937 | Rejected |
| 15% arm | 15% | 1,600 | 0.014186551 | 0.016979217 | 0.019845464 | Rejected |
| 5% control | 0% | 1,200 | 0.013707421 | 0.017779784 | 0.017882933 | Rejected |
| 5% arm | 5% | 1,200 | 0.014096768 | 0.017965010 | 0.018169616 | Rejected |

The 15% arm checkpoint is retained at:

C:\OpenNR\Training\semantic_crop_temporal_continuation_20260909\arm\checkpoint_1600.pt

SHA-256:

5251ab951cebdbe41e4bf224d5489171d76be4a12723e7f3908c57d21a6eb170

The 5% arm checkpoint is retained at:

C:\OpenNR\Training\semantic_crop_temporal_conservative_20260909\arm\checkpoint_1200.pt

SHA-256:

8ac71bfdb77cdd686e70c22cfdceda226236054e4974c23de6bae891855fc2ef

Neither arm passes the protected all-cohort no-regression gate. The new crop
cohort is also not enough to support a visual or color-match claim.

## Independent held-out crop replay

The sequence-disjoint test split was never used by the trainer. This replay is a
useful numeric robustness check, but it remains crop-only and is not visual,
stereo, live-headset, runtime, or VR-budget acceptance.

| Variant | Step | Held-out crop MAE | Temporal delta | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Base | 800 | 0.019259989 | 0.008016058 | Protected reference. |
| 15% arm | 1,200 | 0.020695161 | 0.008096052 | Early endpoint regressed. |
| 15% arm | 1,600 | 0.018912105 | 0.008066922 | Best crop replay, but protected validation regressed. |
| 5% control | 1,200 | 0.018968139 | 0.008017548 | Slightly better than its paired arm. |
| 5% arm | 1,200 | 0.019036918 | 0.007994613 | Slightly lower delta, but worse test MAE than control. |

The 15% endpoint is the best isolated crop-test number, but its improvement is
not sufficient for promotion because it regresses protected cohorts and does
not supply the missing teacher-match or live acceptance evidence. The 5% pair
is a direct robustness warning: its control is slightly better than its arm on
the held-out crop test.

## Methodology and acceptance boundary

The ordinary metric is mean absolute RGB error against the pinned teacher at the
declared cohort grain. The temporal delta is the mean change in consecutive
prediction error during held-out replay; lower is directionally better, but it
is not a full temporal-stability measure.

The paired design intentionally keeps the base checkpoint, old cohorts,
optimizer state, objective, evaluation schedule, and seed-controlled sampling
constant. This supports a controlled engineering comparison; it does not make
the result a causal claim about the capture in isolation.

The strict capture validator requires:

1. complete records for every expected frame;
2. initial [true, true] reset;
3. no mid-sequence reset;
4. contiguous frame, sample, and host IDs;
5. no backpressure or dropped-frame evidence; and
6. valid native depth/motion content.

Those conditions are necessary for temporal training but not sufficient for
promotion. Promotion additionally requires protected validation, held-out
replay, convincing teacher visual/color match, stereo behavior, live Skyrim
observation, and runtime/VR-budget acceptance.

The reader-facing native report artifact is:

out/crop_temporal_every_frame_20260909/crop_temporal_continuation_report_artifact.json

It passed validate_artifact and was rendered as an MCP report with one native
renderer-pilot comparison chart and exact capture/training/replay tables.

## Limitations and next step

The new tranche is crop-only at 512 pixels. It cannot prove full-frame
appearance, native-resolution composition, eye-to-eye color consistency, or
headset behavior. The validators prove completeness and content validity, not
perceptual resemblance. No visual A/B sheet, live Skyrim render, runtime export,
or VR-budget measurement was performed in this continuation.

The next high-value experiment should be a broader sequence- and scene-disjoint
full-eye capture with native Feature-18 guides, exact reset metadata, relevant
renderer conditionings, and enough carried-state or validated state-distillation
information to test whether teacher history is the missing variable. Keep this
18-sequence cache and every checkpoint immutable as controls. More steps on the
same crop mixture, or another blind Runpod run, is not justified by the paired
evidence.

## Storage and Runpod

The final read-only capacity check showed approximately:

| Drive | Free space |
| --- | ---: |
| C: | 240.77 GiB |
| D: | 37.64 GiB |
| E: | 31.02 GiB |

No raw capture, accepted cache, checkpoint, or provenance directory was deleted
or migrated. The local RTX 5070 Ti completed both arms and the replay within
available VRAM, with peak usage around 10.1 GiB. Runpod was not rented; the
remaining $3 credit is preserved because additional VRAM would not address
the observed data/conditioning mismatch.

## Further questions

1. Does a new full-eye, scene-diverse tranche with usable carried state reduce
   the protected ordinary error without destabilizing temporal deltas?
2. Can a state-aware or recurrent student explain the remaining error better
   than another static crop-data mixture?
3. Which visual/color regions dominate the approximately 0.00628 gap after
   protected cohorts and the new crop test are evaluated under the same
   manifest?
4. Can a next candidate pass independent stereo and live-headset acceptance
   without trading away the ordinary metric?
