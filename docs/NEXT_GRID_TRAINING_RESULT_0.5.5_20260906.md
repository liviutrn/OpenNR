# Next-grid capture and training result — 2026-09-06

## Outcome

The new four-crop capture cohort is structurally valid and has been fully
materialized into auditable caches. It improves spatial coverage, but the
current RGB/depth/native-Feature-18-motion representation did not produce a
measurable improvement over the v65 parent in controlled local training. The
best known checkpoint therefore remains unchanged:

`E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt`

The requested MAE `0.011` target remains open. The current v65 checkpoint is
offline crop-space research evidence only; it has not been installed into the
active SkyrimVR/MO2 runtime.

## Capture validation

Source root:

`C:\OpenNR_Captures_NextGridPilot_0.5.5_20260906`

The root contains 105 complete 64-frame sequences: 6,720 frames and 215,040
crop-eye-stage artifacts. Structural validation passed with zero missing files,
duplicate IDs, duplicate hashes, partial sequences, or validator errors. Crop
temporal validation passed for all 105 sequences with contiguous frame IDs,
initial `[true, true]` reset, no mid-clip reset, no backpressure, and no frame
drops.

Authority reports:

- `out\next_grid_capture_validate_20260906.json`
- `out\next_grid_temporal_validate_20260906.json`
- `out\next_grid_candidate_manifest_20260906.json`
- `out\next_grid_content_audit_all_crops_20260906.json`
- `out\next_grid_candidate_manifest_clean_20260906.json`

Every frame kept the exact `feature18_stereo` route, 100% single-pass model
resolution, native Feature 18 bound motion-vector contract, both eyes, raw
pre/post color, native depth, and raw motion vectors. The teacher settings were
consistent with the existing default corpus: intensity 2.0, local structure
2.0, local tone 2.0, skin structure -1.0, style 0, automatic masking enabled,
and UI correction disabled.

The all-crop content audit found 1,327 all-zero-motion eye rows and 118 rows
with invalid motion pixels. To keep bad motion from entering recurrent loss,
the following 13 sequences are excluded from the strict temporal cache:

`seq-1788740186666-3`, `seq-1788740201946-4`,
`seq-1788740213427-5`, `seq-1788740216872-6`,
`seq-1788741745307-86`, `seq-1788741885498-91`,
`seq-1788742005659-94`, `seq-1788742012334-95`,
`seq-1788742054737-96`, `seq-1788742076816-97`,
`seq-1788742102196-98`, `seq-1788742123662-99`, and
`seq-1788742159442-101`.

They remain preserved in the raw source and all-crop spatial-only cache for
audit/appearance use. They are not silently treated as valid temporal motion.

## Cache organization

The clean center-crop temporal cache is on the fast E: path:

`E:\OpenNR_RawCropCache_NextGridTemporalClean_0.5.5_20260906`

It contains 92 sequences, 5,888 frames, and 11,776 eye rows split into 58
train, 15 validation, and 19 test sequences. Its `complete.json` records:

- `rows_sha256`: `165dde16ade966fe73ba6adc385cccd43f2ead21e671bdaa175226193869f898`
- `training_role`: `strict_temporal_crop_cache`
- `temporal_training_allowed`: `true`
- `strict_initial_reset`: `true`

The all-crop spatial auxiliary cache is on C: because it is the larger,
non-recurrent representation:

`C:\OpenNR_Cache_NextGridSpatialAllCrops_0.5.5_20260906`

It contains all 105 sequences, 53,760 eye/crop rows, and crop indices 0, 1, 2,
and 3. Its `complete.json` records:

- `rows_sha256`: `71a0c690776ca10cf911af03b1722b32621d37350a7c7499d00757498b9292f4`
- `training_role`: `spatial_only_auxiliary`
- `temporal_training_allowed`: `false`
- `strict_initial_reset`: `true`

The builder now supports explicit crop selection and rejects multi-crop output
unless it is marked `--spatial-only`. `StrictTemporalCache` also rejects a
cache marked `temporal_training_allowed=false`, preventing accidental use of
the duplicate-crop cache as a recurrent stream. The changes are in:

- `tools\build_raw_crop_cache.py`
- `tools\train_temporal_student.py`
- `tools\test_raw_crop_cache.py` (existing spatial-only test handling)

The all-cohort strict cache combines the prior accepted 73-sequence historical
cache, the prior 126-sequence fresh cache, and the new 92-sequence clean grid
cache:

`E:\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906`

It contains 291 sequences, 18,624 frames, and 37,248 eye rows. The preserved
source-level splits produce 368 train streams, 94 validation streams, and 120
test streams. Its `rows_sha256` is
`0aeffc9bfce46e2a9d8da05a7039e3ca73df3fa083c0db0daa01984f058b5410`, with
`training_role=strict_temporal_combined`, `temporal_training_allowed=true`,
and `test_used_for_tuning=false`. Both raw-cache helper tests and direct
strict-stream construction passed.

## Controlled training results

All runs initialized from the unchanged v65 best-MAE checkpoint unless noted.
The v65 parent measured `0.023306393` validation MAE and `0.027438652` new-grid
test MAE on the clean new-grid cache. On the complete merged held-out test it
measured `0.021573284` over 60 sequences, 120 eye streams, and 7,680 frames.

| Run | Controlled change | Validation / transfer result | Decision |
|---|---|---:|---|
| v68 | New-grid-only temporal stream; all-crop spatial probability 0.50; 1,200-step plan | 0.023306393 at step 0; 0.023313994 at 100; 0.023325711 at 200; 0.023356511 at 300 | Interrupted after regression; step 0 retained |
| v68b | New-grid-only stream; spatial probability 0.15; 800-step plan | 0.023306393 at step 0; 0.023337226 at 100; 0.023379729 at 200 | Interrupted after regression; step 0 retained |
| v69 | All 291 clean sequences; spatial probability 0.15; 1,200-step plan | 0.019805015 at step 0; 0.019812350 at 100; 0.019863331 at 200 | Interrupted after regression; step 0 retained |
| v70 | Width 160/6 with 80/3 extra branch; fresh capacity initialization | 0.019960045 at step 0; first post-update validation became impractical | Interrupted; peak 13.584 GiB, not promoted |
| v71 | Fixed all-non-test fit over the merged cache; 1,000 steps | Merged test 0.021731749; new-grid test 0.027926762 | Rejected; worse than v65 |

The v71 comparison is against the untouched v65 baseline:

- merged test: `0.021573284` → `0.021731749` (`+0.000158464`)
- new-grid test: `0.027438652` → `0.027926762` (`+0.000488110`)

The v71 checkpoint SHA-256 is
`4eb499c2271223e90babd8b58e9e38c70c445656a76951bef6a6aafd1e576c0f`.
Its all-non-test fit completed without non-finite loss or gradient, but a
completed fit is not automatically a quality improvement.

The interrupted run artifacts are preserved and explicitly marked
`state=interrupted` with reasons in their status files:

- `E:\OpenNR_Training\next_grid_v68_capacity_temporal_probe_0.5.5_20260906`
- `E:\OpenNR_Training\next_grid_v68b_temporal_dominant_probe_0.5.5_20260906`
- `E:\OpenNR_Training\next_grid_v69_allcohort_temporal_dominant_probe_0.5.5_20260906`
- `E:\OpenNR_Training\next_grid_v70_width160_allcohort_probe_0.5.5_20260906`

The completed but rejected fixed-fit artifact is preserved at
`E:\OpenNR_Training\next_grid_v71_allnontest_fit_0.5.5_20260906`.

## Visual validation

A representative new-grid validation gallery is preserved at:

`D:\.CODEX_Projects\OpenNR-VR\out\next_grid_v65_visual_gallery_0.5.5_20260906`

It shows input, the earlier v8 spatial output, v65, and the captured Feature
18 teacher for both eyes at frames 1, 32, and 64. The sampled stone/wood,
rock, and dark character scenes confirm the numerical result: v65 remains
visually close to the input, while the teacher applies broader local tone,
shadow, contrast, and material-detail changes. The gallery is direct
crop-space visual evidence only, not headset or live-runtime acceptance.

Representative sheet:

`out\next_grid_v65_visual_gallery_0.5.5_20260906\seq-1788741378140-67_f32_e0.jpg`

## Decision and next step

Do not install v68, v68b, v69, v70, or v71. Keep v65 as the known-good
offline checkpoint and preserve the raw captures, caches, and interrupted
run evidence.

The local evidence now favors a conditioning/target and distribution problem
over more same-recipe steps. The new grid and prior corpora use the same
teacher controls, but their scene and motion distributions differ materially;
the new-grid test has lower motion magnitude and higher error than the older
fresh cohort. Increasing local capacity to width 160 approaches the 16-GiB
GPU limit and does not establish a productive trajectory.

The highest-value next iteration is therefore:

1. Keep the exact native Feature 18 RGB/depth/motion contract and four-crop
   capture path.
2. Capture deliberate high-effect cases and independent environments with a
   balanced scene/environment split, while continuing to quarantine zero or
   invalid motion from recurrent loss.
3. If the renderer boundary permits it, add auditable renderer-derived
   conditionings that the teacher can use for tone/material/shadow decisions:
   albedo, normals, illumination/light features, material/object/light masks,
   artistic controls, and the carried teacher history state. Record shape,
   coordinate space, sign/range, reset behavior, and hashes for every new
   tensor before training.
4. Use RunPod only if an authorized cloud budget is available for the already
   documented width ladder. A larger GPU can test width 160/192, but it does
   not replace the missing conditioning evidence and is not permission to
   spend automatically.

This result is offline crop-space training evidence. It does not establish
Feature 18 runtime replacement, stereo delivery, headset image quality,
temporal compositor behavior, or VR frame-time acceptance.
