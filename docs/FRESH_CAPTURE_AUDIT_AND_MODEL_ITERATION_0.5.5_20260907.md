# OpenNR-VR fresh high-effect capture and training result — 2026-09-07

## Current outcome

The fresh high-effect cohort is valid and useful. It is now included in a new
immutable combined training cache together with the complete prior strict
corpus. The data improves coverage of the intended difficult domain, but the
first controlled continuation did not improve the current model, so the known-
good v65 checkpoint remains selected. No trained model candidate was installed
into the SkyrimVR/MO2 runtime; the explicitly requested renderer-conditioning
capture probe is now installed as the active diagnostic DLL after a rollback
backup.

The MAE `0.011` target remains open. The evidence continues to point to a
conditioning/representation gap rather than a need for more blind steps on the
same RGB/depth/native-motion recipe.

## Fresh capture validation

Source root:

`C:\OpenNR_Captures_VariedHighEffect_0.5.5_20260907`

The root contains 32 exact 64-frame sequences: 2,048 complete frames and
65,536 crop-eye-stage artifacts. The raw tree is approximately 68.75 billion
bytes (64.03 GiB) and remains intact.

The byte-level validator returned success with:

- 32 sequences and 2,048/2,048 complete frames;
- zero partial frames, failed frames, missing files, duplicate IDs, duplicate
  hashes, all-zero images, or all-zero raw tensors;
- zero validator errors and zero warnings.

The compact byte-audit authority is
`D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_20260907_byte_audit_summary.json`.
The full validator is `tools\validate_capture.py`.

The temporal audit passed all 32 sequences. Every sequence had 64 contiguous
frames, contiguous sample/host order, one initial `[true, true]` reset, no
mid-clip reset, no backpressure, no dropped frame, and `temporal_ready=true`.
Its authority file is
`D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_20260907_temporal_audit.json`.

The all-crop content audit covered 16,384 eye/crop rows. It found:

- zero all-zero-motion rows;
- 61 rows with at least one invalid native-motion pixel;
- 6,934,311 invalid motion pixels in total;
- four sequences with a severe sequence-level invalid-motion fraction:
  `seq-1788754633708-20`, `seq-1788754796040-25`,
  `seq-1788754948773-30`, and `seq-1788754969033-31`.

Those four sequences are preserved in the raw capture and the all-crop
spatial-only cache, but are excluded from recurrent temporal loss. The other
28 sequences are clean for the selected center crop: the built cache records
zero invalid depth values and zero invalid motion values. This is a
conservative native-guide quarantine, not a deletion or claim that the four
captures are visually useless.

The content-audit authority is
`D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_20260907_content_audit.json`.
The exact clean candidate manifest is
`D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_20260907_candidate_manifest_clean.json`.

Every promoted frame retains the established capture contract: stereo Feature
18 route, 100% single pass, both eyes, pre-NR input, teacher output, raw native
depth, raw native Feature 18 motion vectors, four 512x512 crops, and strict
initial history reset. The native motion-vector contract remains
`exact_feature18_bound_resource`; optical flow was not substituted.

## How the prior data is included

The older data was not replaced or discarded. The new merge has two explicit
source records:

| Source | Sequences | Rows/patches | Role |
| --- | ---: | ---: | --- |
| Prior all-cohort parent | 291 | 37,248 | Historical 73 + prior fresh 126 + next-grid clean 92; strict temporal source |
| New high-effect clean temporal cohort | 28 | 3,584 | New train/validation/test sequence cohort |
| **Combined cache** | **319** | **40,832** | Self-contained strict temporal training cache |

The new clean cohort keeps a deterministic chronological sequence split of 17
train, 5 validation, and 6 untouched test sequences. The combined cache keeps
the prior source-level splits and adds the new split without frame-level
reshuffling:

- train: 25,728 rows;
- validation: 6,656 rows;
- test: 8,448 rows;
- `strict_initial_reset=true`;
- `temporal_training_allowed=true`;
- `test_used_for_tuning=false`;
- combined `rows_sha256`:
  `8363da3e04b58f66cd4acadb8e60648f593aacaad51945ad9cea0d59a8871e18`.

The active combined cache is
`C:\OpenNR_Cache_StrictAllCohortsVariedHighEffect_0.5.5_20260907`.
Its cache helper test passes. The new center-crop temporal cache is
`E:\OpenNR_RawCropCache_VariedHighEffectTemporalClean_0.5.5_20260907` and its
cache helper test also passes.

All 32 fresh sequences, including the four temporal quarantine sequences, are
represented in the separate all-crop spatial cache
`C:\OpenNR_Cache_VariedHighEffectSpatialAllCrops_0.5.5_20260907`.
It is explicitly spatial-only and passes the cache helper test. The four
sequences are therefore still available for appearance coverage and future
row-level investigation without contaminating the recurrent stream.

## Storage organization

The 65.50 GiB prior merged parent was copied from E: to
`G:\OpenNR_ColdStorage\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906`.
It was tested and all 8 files passed exact SHA-256 verification before the E:
source was released. The combined cache was then built from this verified G:
parent and the new E: temporal cache; it is self-contained on C:.

Three older derived caches were also copied, tested, and verified file by file
before their E: copies were released:

`G:\OpenNR_ColdStorage\OpenNR_Archive_DerivedCaches_20260907`

- `OpenNR_RawCropCache_StrictCombinedFresh_0.5.5_20260906` — 44.79 GiB;
- `OpenNR_RawCropCache_NextGridTemporalClean_0.5.5_20260906` — 20.71 GiB;
- `OpenNR_RawCropCache_StrictTemporal_0.5.5_20260906` — 16.43 GiB.

These are derived subsets already represented in the prior all-cohort parent;
they are archived, not lost. No raw capture tree, selected checkpoint, new
cache, or experiment checkpoint was deleted.

Final free-space readings after the move:

- C: `68.90 GiB` free;
- E: `163.93 GiB` free;
- G: `248.24 GiB` free.

The active capture root, new spatial cache, combined C: cache, new E: temporal
cache, v65 checkpoint, G: parent, and G: derived archive were all present at
the final audit.

## Controlled training iteration v72

Parent checkpoint:

`E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt`

The parent SHA-256 is
`5672252b438669169d8b2fed9ffb16f20768270f01d79dc924f32b9318fbc3e3`.
The v65 architecture/capacity and its proven loss recipe were held fixed so
the data/coverage change could be measured without confounding it with a new
network design. v72 used the combined cache as its temporal stream and both
the combined center data and new four-crop cache as training-only spatial
sources, with spatial probability 0.25.

Output:

`E:\OpenNR_Training\varied_high_effect_allcohort_v72_probe_0.5.5_20260907`

The validation history was:

| Step | Merged validation MAE | First-frame feature distance | Result |
| ---: | ---: | ---: | --- |
| 0 | `0.0198215459` | `0.0899783000` | inherited v65; best |
| 100 | `0.0198453080` | `0.0900430742` | regression |
| 200 | `0.0198891780` | `0.0902112189` | continued regression |

The run was stopped at step 250 after the sustained regression. Its status is
explicitly marked `interrupted` with `step_0_retained`; the step-0
`best_mae.pt` is functionally the inherited v65 result, while `last.pt` is the
step-200 checkpoint. Peak allocated GPU memory was 12.31 GiB.

On the six new held-out sequences (768 frames), the unchanged v65 and the v72
step-0 best checkpoint both measured:

- MAE `0.0199684061`;
- PSNR `30.4509561` dB;
- temporal-delta MAE `0.0073129247`.

The v72 step-200 checkpoint measured MAE `0.0201936149` on the same new test
split, so it was not promoted. On the expanded 66-sequence merged test (8,448
frames), v65/v72 step 0 measured MAE `0.0214273864`, PSNR `29.5402320` dB, and
temporal-delta MAE `0.0098032324`. The merged v65 baseline and v72 step-0
result are identical because step 0 is the inherited function.

The frozen test result files are:

- `D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_v65_baseline_test_0.5.5_20260907\result.json`;
- `D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_v65_baseline_merged_test_0.5.5_20260907\result.json`;
- `D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_v72_step200_new_test_0.5.5_20260907\result.json`;
- `D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_v72_best_new_test_0.5.5_20260907\result.json`;
- `D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_v72_best_merged_test_0.5.5_20260907\result.json`.

Decision: do not promote v72 and do not install it. Keep v65 as the selected
offline research candidate. The new cohort is still retained as part of the
future training corpus and as a high-effect held-out domain.

## Visual validation

The sequential visual A/B gallery is:

`D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_v65_v72_visual_gallery_0.5.5_20260907`

Each sheet contains Input, v65 selected, v72 step-200 probe, and Feature 18
teacher for one eye at frames 1, 32, or 64. Representative sample:

`D:\.CODEX_Projects\OpenNR-VR\out\varied_high_effect_v65_v72_visual_gallery_0.5.5_20260907\seq-1788754788625-24_f32_e0.jpg`

The selected student and step-200 probe are visually near-identical in this
sample, while the teacher has the expected stronger local tone, shadow, and
material response. This agrees with the measured regression and confirms that
the update did not create an obvious visual win. The gallery is crop-space
evidence only; it is not headset, compositor, stereo-comfort, or VR-budget
acceptance.

## Current decision and next high-value step

The new data has done its job as a distribution/coverage test and has been
added to the prior corpus through explicit cache provenance. More same-recipe
steps are not justified by this run: v68-v72 already show early flat or
regressing validation, while width increases approach the local 16 GiB GPU
limit without evidence of a productive trajectory.

The next useful improvement is a representation/target iteration:

1. Keep the current exact RGB/depth/native Feature 18 motion contract and the
   new high-effect capture cohort.
2. If the renderer boundary can expose them safely, add auditable albedo,
   normals, illumination/light features, material/object/light masks,
   artistic-direction controls, or the exact carried teacher history. Record
   tensor shape, coordinate space, range/sign, reset behavior, and per-sample
   hashes before admitting any channel to training.
3. If those channels remain unavailable, run a deliberately weighted
   high-effect specialist/mixture experiment against the immutable v65 parent,
   with a frozen old-domain test and the six-sequence new test kept untouched.
   Select by both domain-specific and merged validation, not by training loss.
4. Use a larger GPU only for a controlled width ladder after the conditioning
   path is improved; local v70 evidence does not support an automatic capacity
   increase as the next move.

This report supersedes the 2026-09-06 capture/training status for the current
cohort. Earlier reports remain historical evidence and are not reclassified as
new data.

## 2026-09-07 preparation update

The renderer-boundary conditioning probe is prepared and compiled in isolation.
The detailed contract, pilot procedure, storage estimate, and unavailable
signals are recorded in
`docs\RENDERER_DERIVED_CONDITIONING_PROBE_0.5.5_20260907.md`.

The probe exposes six opt-in raw deferred G-buffer stages:
`gbuffer_albedo`, `gbuffer_normal_roughness`, `gbuffer_masks`, `gbuffer_masks2`,
`gbuffer_specular`, and `gbuffer_reflectance`. It records the same per-eye
Feature 18 source rectangle and explicit availability metadata. Clean
illumination-only data, semantic IDs, and the opaque carried teacher history
remain unavailable; reset metadata is already captured. The isolated build is
`out\renderer_conditioning_probe_0.5.5_20260907\CommunityShaders.dll` and is
now installed as the active MGO diagnostic DLL after a verified backup. Its
SHA-256 is `A50B62C955ACE36AC52800921646F53B8500BE6CDBEB7028F6DFB3362EF4D817`.
The previous active DLL is retained at
`G:\OpenNR_Capture_Setup_Backups\active-renderer-conditioning-pilot-0.5.5-20260907-0210\CommunityShaders.dll`.

The old-domain temporal cache was staged from the verified G: archive to
`E:\OpenNR_TrainingInputs\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906`
for faster reads. All 8 files / 65.500 GiB passed size and SHA-256 verification;
the G: archive remains intact. The new-domain cache remains at
`E:\OpenNR_RawCropCache_VariedHighEffectTemporalClean_0.5.5_20260907`.

The capacity trainer is prepared for a 0.35 new-domain temporal sampling
probability plus 0.25 spatial sampling probability, with old/new/merged
validation reported independently. GPU training and GPU evaluation are paused
because another Codex task is using the GPU. The new old/new mixture recipe is
renamed v75 below because separate v73/v74 specialist probes already exist in
this report; no v75 mixture checkpoint has been started by this preparation
update.

## 2026-09-07 active MGO conditioning-pilot preparation

At the user's request, the active profile
`E:\MGO-RC3-fresh` / `MGO NSFW - 4.0 BETA` is now configured for the bounded
renderer-conditioning pilot. SkyrimVR, MO2, SteamVR, `vrserver`, and
`vrcompositor` were closed before the change.

The active `OpenNR Capture` values are now:

- `burst_frames=8`, `crop_count=1`, `crop_size=512`;
- both eyes, pre-NR input, post-NR teacher, raw teacher, native depth, and
  exact Feature 18 motion vectors;
- `capture_renderer_conditionings=true`;
- raw tensors only (`write_color_previews=false`), no full-frame copies;
- `queue_capacity=16`, `max_samples=8`, `capture_rate_fps=90`;
- output:
  `C:\OpenNR_Captures_RendererConditioningPilot_0.5.5_20260907`;
- existing hotkeys retained: `[` = 219, `]` = 221, `\` = 220.

The newly built probe DLL is the sole active `CommunityShaders.dll` owner and
has SHA-256
`A50B62C955ACE36AC52800921646F53B8500BE6CDBEB7028F6DFB3362EF4D817`.
The resulting active `SettingsUser.json` SHA-256 is
`F4938BCB975120ECC627A42BDA3EA69C3F3AEE9837EFED6C51203469A2BA6234`.
The former active DLL
`751401C26DF6B9FCD7F6F3DD906EE6D57ED69D6F3C6EE6305D1C445C49E3FFD4` and the
pre-edit `SettingsUser.json` are preserved and hash-verified under
`G:\OpenNR_Capture_Setup_Backups\active-renderer-conditioning-pilot-0.5.5-20260907-0210`.

This is a build/configuration acceptance state, not live Feature 18 acceptance.
When the user wakes, the next action is to launch the selected MGO profile,
allow the scene to settle, request three bounded bursts in the documented
material/shadow and motion cases, and validate the resulting `frames.jsonl`
before any new conditioning channel is admitted to training.

The offline capture validator was also updated for this pilot: it requires a
non-empty per-frame renderer-conditioning availability list when the opt-in is
enabled, requires the reported available stages, and checks the raw byte sizes
for the new `R11G11B10_FLOAT` and `R16_UNORM` readbacks. Both the live settings
file and the disabled-by-default pilot example pass the configuration validator;
no pilot capture directory exists yet, so live Feature 18 availability remains
an explicit morning capture gate.

## 2026-09-07 follow-up: specialist probes and Runpod preflight

The preparation note above was followed by two local specialist probes on the
5070 Ti. Both used the immutable v65 parent and kept the prior and new test
splits untouched.

### v73 widened replacement branch — rejected as an unfair comparison

Output:

`E:\OpenNR_Training\high_effect_adapter_v73_local_0.5.5_20260907`

The probe changed the extra branch width from the v65 value of 64 to 96. The
initializer only copies shape-compatible tensors, so the inherited v65 extra
branch was not loaded. Although the replacement branch was zero-initialized,
this also removed the parent's existing extra contribution at step 0. It is
therefore not a parent-preserving capacity test and is rejected as a fair
comparison.

Its best checkpoint was step 300:

`E:\OpenNR_Training\high_effect_adapter_v73_local_0.5.5_20260907\best_mae.pt`

The checkpoint SHA-256 is
`521a1527e9111fd2f2b6b7101984f8ef4a935b5cb00e2985fb6f213c47173f71`.
Even on its own terms it did not beat v65:

| Validation cohort | v65 MAE | v73 best MAE | Change |
| --- | ---: | ---: | ---: |
| New clean high-effect validation | `0.0199770549` | `0.0200056444` | `+0.0000285905` |
| Prior validation | `0.0198050034` | `0.0198083859` | `+0.0000033825` |

The new-domain effect-band audit also still showed a negative low-effect band
relative to identity (`-46.7%` improvement), so this branch did not repair the
small-effect behavior that is relevant to the `0.011` target.

### v74 exact-parent specialist — no promotion

Output:

`E:\OpenNR_Training\high_effect_specialist_v74_parent_preserve_0.5.5_20260907`

This was the corrected parent-preserving test. It retained the v65 architecture
and the existing 64-wide extra branch, froze every inherited branch, and trained
only that existing extra branch using the clean new temporal cohort plus prior
spatial regularization. Its step-0 function matched v65 exactly. The run
completed all 1,200 steps in 282.5 seconds, but its new-validation MAE drifted
steadily upward:

| Step | New validation MAE | Interpretation |
| ---: | ---: | --- |
| 0 | `0.0199770553` | exact v65 function; best |
| 500 | `0.0199951990` | regression |
| 600 | `0.0200007465` | regression |
| 1,000 | `0.0200250905` | regression |
| 1,200 | `0.0200346887` | regression |

The saved best checkpoint is
`E:\OpenNR_Training\high_effect_specialist_v74_parent_preserve_0.5.5_20260907\best_mae.pt`
with SHA-256
`41ff437bf4222ad9d257bdb35c3111efd4cf774d058a3a0fb79614c565abb2e7`.
Its independent evaluations are:

| Validation cohort | MAE | PSNR | Frames | Result |
| --- | ---: | ---: | ---: | --- |
| New clean high-effect validation | `0.0199770549` | `29.8691` dB | 640 | exact v65 result |
| Prior validation | `0.0198050034` | `29.9379` dB | 6,016 | exact v65 result |

The v74 specialist is therefore not promoted. The selected offline candidate
remains v65; no v73 or v74 checkpoint was installed into SkyrimVR/MO2.

### Runpod upload preflight — failed the upload gate

A temporary secure A40 Pod was created only for a real client-to-Pod upload
measurement:

- Pod: `go0b4oahh29yzd`, secure A40 48 GB in `CA-MTL-1`;
- catalog GPU price: `$0.49/hr`;
- storage: temporary 100 GB Pod volume at `/workspace`;
- direct SSH route: `69.30.85.44:22030`;
- synthetic payload: 256 MiB = 2.147 Gbit;
- transfer: 8.148 seconds via SCP;
- effective upload: `263.6 Mbit/s` = `0.264 Gbit/s`.

This is far below the required `2.5 Gbit/s` effective client-to-Pod gate for
future upload-heavy work. The result is a route/transport measurement, not a
claim about Runpod's internal 10 Gbit/s fabric. The Pod was deleted immediately
after the test, no experiment data was uploaded, and Runpod now reports zero
active Pods. No Runpod training spend is authorized from this preflight result.

Runpod remains useful only if a future data-center/transport combination passes
the live upload gate, or if the data is already staged in cloud storage and the
job does not depend on a large local upload. The current `CA-MTL-1` route is not
approved for the planned cache transfer.

## Updated decision after the follow-up

The width/capacity hypothesis has not been supported by the available
parent-preserving evidence. The widening v73 test was not a valid function-
preserving comparison, and the corrected v74 test learned no useful residual
without degrading the new domain. Do not spend the remaining Runpod balance on
another blind width ladder or on re-running unchanged v72.

The next high-value move remains the renderer-derived conditioning probe already
prepared above. If its channels can be captured with a complete contract, use a
small local pilot first; only then consider a larger GPU for a controlled width
ladder. This keeps the cloud budget available for a recipe that has first shown
an offline validation gain toward MAE `0.011`.

## Superseding latest-cache width result — 2026-09-07

The preceding width conclusion predates the dedicated latest-cache three-arm
run. That run is documented in
`D:\.CODEX_Projects\OpenNR-VR\docs\RUNPOD_LATEST_CACHE_WIDTH_ABLATION_0.5.5_20260907.md`.
It used the immutable prior cache, the new clean temporal cache, and the new
spatial-only auxiliary cache on one secure L40S Pod in `US-NC-1`. The Pod was
deleted only after all 32 recovered artifacts were SHA-256-verified against
the remote files.

The three fresh-capacity arms used the same inherited base/temporal function,
loss, sampling, seed, and 1,000-step budget. Local independent validation at
the same recovered checkpoint (`step 500`) was:

| Arm | Capacity | Parameters | Runtime | Prior validation MAE | New validation MAE |
| --- | --- | ---: | ---: | ---: | ---: |
| A | `128/6 + 64/3` | `2,936,659` | `746.7 s` | `0.019705133` | `0.019378331` |
| B | `160/6 + 80/3` | `3,188,083` | `826.5 s` | `0.019696995` | `0.019372930` |
| C | `192/6 + 96/3` | `3,480,979` | `1,052.4 s` | **`0.019690728`** | **`0.019369167`** |

The exact v65 parent was `0.019805003` on prior validation and `0.019977055`
on new validation. All three arms beat v65 on both cohorts; Arm C is the
combined-MAE winner. The gain is real but small and does not explain the full
gap to MAE `0.011`.

Effect bins show that Arm A is slightly better than C in the extreme `>=0.1`
band (`0.074500` vs `0.075726` new; `0.072297` vs `0.073795` prior), while C
wins the full image and middle bands. Every arm still regresses relative to
identity in the `0–0.01` band. This makes selective effect conditioning or
loss/sampling work more attractive than another blind width ladder.

After validation selection was frozen, Arm C's one merged-test evaluation
measured `0.021328798` versus the existing v65 result `0.021427386`, a
`0.460%` MAE reduction and `+0.0975 dB` PSNR. Temporal-delta MAE was slightly
worse (`0.009894529` vs `0.009803232`), so this is a modest transfer gain with
a stability tradeoff. Arm C is now the selected offline research candidate;
it has not been installed into SkyrimVR/MO2 and is not live VR acceptance.

The recovered evidence and matched visual sheets are under
`E:\OpenNR_Training\runpod_latest_cache_width_ablation_0.5.5_20260907`.
Runpod's post-deletion billing snapshot attributes approximately `$0.9541`
to the experiment Pod and reports zero active Pods. A local 5070 Ti pilot is
testing the existing high-frequency effect loss from Arm C at zero cloud cost;
its result will choose between an effect-aware continuation and a depth
expansion for the next Runpod spend.

## Zero-cloud local follow-up: global residual calibration rejected

An offline calibration diagnostic was run on the selected Arm-C checkpoint
before authorizing any further Runpod work. It fitted a single scalar `alpha`
on the combined old/new training streams and applied the frozen correction
`rgb + alpha * (prediction - rgb)` to both validation cohorts. The fit was
`alpha=1.0390703622`.

The prior validation cohort was `0.019690745` at the uncalibrated output,
`0.019687008` at its best grid value `alpha=0.980`, and `0.019716425` at the
frozen train-fit alpha. The new cohort was `0.019369241` uncalibrated,
`0.019359838` at its best grid value `alpha=1.030`, and `0.019360261` at the
frozen train-fit alpha. Because the cohort optima point in opposite
directions, the global calibration fails the two-cohort rule and is rejected.
The result is retained at
`E:\OpenNR_Training\arm_C_effect_calibration_0.5.5_20260907\result.json`;
the frozen test split was not read.

The next local experiment is a parent-preserving depth expansion of Arm C,
`192/8 + 96/4`. Its new blocks will be identity-initialized by zeroing their
residual scales, so the step-0 function is exactly Arm C before any learning.
It will be independently evaluated on both validation cohorts and will not be
promoted on a one-cohort gain.

## Zero-cloud local follow-up: parent-preserving depth expansion rejected

The `192/8 + 96/4` Arm-C child completed 400 local steps in `485.63 s` on
the RTX 5070 Ti with no OOM or non-finite loss. The three appended block
residual scales were zero-initialized, and step 0 reproduced Arm C exactly.
The best new-domain point at step 400 measured `0.019810200` prior and
`0.019321325` new under independent streaming evaluation; it improved only
the new cohort and regressed the prior by `0.000119472`. The trainer's
step-100 point showed the same direction (`0.019719531` prior /
`0.019348730` new). The depth expansion is rejected and no frozen test or
production/MO2 evaluation was made.

The complete pre-registration and result are in
`docs/LOCAL_ARM_C_DEPTH_EXPANSION_PILOT_0.5.5_20260907.md` and
`E:\OpenNR_Training\local_arm_C_depth_expansion_0.5.5_20260907`. With scalar
calibration, effect-frequency loss, identity weighting, style modulation, and
depth expansion all failing the two-cohort gate, another blind Runpod
capacity run is not justified. The pending renderer-conditioning capture is
now the next high-value information gain.

## Capture handoff checkpoint — 2026-09-07

The isolated Open Shaders profile has renderer-conditioned capture enabled:
depth, motion vectors, raw teacher, pre-NR, post-NR, both eyes, eight-frame
bursts, and one `512x512` crop. Full-frame capture remains disabled to limit
transfer and storage. The intended output is
`C:\OpenNR_Captures_RendererConditioningPilot_0.5.5_20260907`.

The root was rechecked after the latest model pilots and still contained no
capture data. The next action is user collection of the bounded interior,
exterior/high-contrast, and motion/high-effect bursts. Validation must pass for
all six renderer-conditioning stages, eye/crop/source-rectangle alignment,
raw format/size, finite values, and sequence ordering before cache construction
or another Runpod rental.

Runpod was also rechecked: zero pods and zero network volumes are present, so
there is no active cloud drain. The exact resource and billing checkpoint is
recorded in `docs/OPENNR_TRAINING_STATUS_0.5.5_20260907.md`.
