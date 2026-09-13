# OpenNR-VR project report — 2026-09-06 (historical)

> Latest completed full-model result: corrected native-guide training versus matched legacy-guide control, 1,200 local steps each. Corrected validation MAE prior/high-effect/latest: 0.019734763 / 0.017683441 / 0.015286623. New-cohort gains do not yet preserve the original parent on prior data, so no promotion or MAE 0.011 claim. See [completed alignment comparison](D:/.CODEX_Projects/OpenNR-VR/docs/ALIGNED_GUIDE_MULTICOHORT_TRAINING_20260907.md). No additional capture is needed to finish this comparison.

> Latest September 7 afternoon result: fresh renderer-conditioning captures were validated and used in a completed local refiner/control experiment. Eleven accepted 64-frame clips; one GPU-query-failed clip excluded and preserved. Control test MAE 0.018983047 versus parent 0.021267248 and conditioned 0.021005986. No production promotion. See [renderer-conditioned pilot results](D:/.CODEX_Projects/OpenNR-VR/docs/RENDERER_CONDITIONED_TRAINING_PILOT_20260907.md).

> Superseding status: the current 2026-09-07 capture, cache merge, storage
> organization, and v72 training result are recorded in
> [FRESH_CAPTURE_AUDIT_AND_MODEL_ITERATION_0.5.5_20260907.md](D:/.CODEX_Projects/OpenNR-VR/docs/FRESH_CAPTURE_AUDIT_AND_MODEL_ITERATION_0.5.5_20260907.md).
> The capture, runtime and v8 sections below are the earlier
> project-state record. The current fresh-capture audit and model lineage
> supersede the v45-v48/v47 wording below and are documented in
> [FRESH_CAPTURE_AUDIT_AND_MODEL_ITERATION_0.5.5_20260906.md](D:/.CODEX_Projects/OpenNR-VR/docs/FRESH_CAPTURE_AUDIT_AND_MODEL_ITERATION_0.5.5_20260906.md).

## Latest next-grid training update — 2026-09-06

The 105-sequence four-crop grid cohort is structurally and temporally valid.
Its 92 clean sequences were materialized as a strict center-crop temporal
cache, all 105 sequences were retained in a four-crop spatial-only auxiliary
cache, and the 92 clean rows were merged with the accepted historical and
prior-fresh cohorts into one 291-sequence strict cache. Full details,
validator paths, crop exclusions, cache hashes, visual samples, and training
results are in
[NEXT_GRID_TRAINING_RESULT_0.5.5_20260906.md](D:/.CODEX_Projects/OpenNR-VR/docs/NEXT_GRID_TRAINING_RESULT_0.5.5_20260906.md).

Controlled v68/v68b/v69 continuation probes regressed or stayed flat at their
first checkpoints; the width-160 v70 arm reached the local GPU memory/cost
limit before a productive post-update validation; and the completed v71
all-non-test fit transferred worse on the untouched merged test (`0.021731749`
versus v65 `0.021573284`). The v65 checkpoint remains the promoted offline
candidate. The requested MAE `0.011` target remains open, and no new model was
installed into the active SkyrimVR/MO2 runtime.

## Current superseding state

The fresh strict root was re-audited into 126 temporal-safe sequences plus 5
spatial-only quarantined sequences. The combined strict cache contains 199
sequences, 12,736 frames, and 25,472 eye rows with strict initial-reset
provenance; all three relevant raw-crop cache validations pass under the pinned
CUDA environment. The latest v65 update is recorded in
`docs/MODEL_ITERATION_UPDATE_V65_FULLRES_OVERSAMPLE_20260906.md`: its selected
step-200 checkpoint is the current minor research candidate at combined test
MAE `0.018847388`, fresh MAE `0.014935002`, and historical MAE `0.025628855`.
It is not a live runtime or headset acceptance result and remains above the
`0.011` target.

The v65 all-non-test offline research candidate is:

- Checkpoint: `E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt`
- Fresh held-out MAE: `0.014935002` over 3,328 frames
- Historical held-out MAE: `0.025628855` over 1,920 frames
- Frame-weighted two-cohort MAE: `0.018847388`
- Checkpoint SHA-256: `5672252b438669169d8b2fed9ffb16f20768270f01d79dc924f32b9318fbc3e3`

The requested `0.011` target remains open. This is crop-space streaming
evidence only; it is not live Feature 18 replacement, headset/stereo, or
frame-time acceptance. v60 is the historical-leaning fallback, v62 is a
fresh-specialist ablation, and v56 is the historical-test anchor. No candidate
has been installed into the active SkyrimVR/MO2 runtime.

## Next varied/high-effect capture setup — 2026-09-06

The active local OpenNR profile is now prepared for a new environment- and
motion-diverse capture pass. Future captures write to
`C:\OpenNR_Captures_VariedHighEffect_0.5.5_20260907`. The existing both-eye,
pre/post-NR, raw-teacher, native-depth, native-MV, four-crop, 64-frame Feature
18 contract is unchanged; the future output path is on the fast C: NVMe and
the bounded writer queue remains 64. The pre-edit settings backup is on G:.
The exact collection protocol and the source
audit of renderer-derived conditioning availability are in
[NEXT_CAPTURE_SETUP_G_VARIATION_0.5.5_20260906.md](D:/.CODEX_Projects/OpenNR-VR/docs/NEXT_CAPTURE_SETUP_G_VARIATION_0.5.5_20260906.md).

The current capture still cannot provide albedo, normals, illumination,
semantic/material buffers, the teacher's internal mask texture, or the exact
carried history tensor. The source currently exposes only the four Feature 18
resources plus scalar tuning/reset metadata. Those channels require an isolated
renderer diagnostic implementation and must not be approximated or injected
into the known-good teacher route without provenance and alignment evidence.

Storage was reorganized after this report's earlier inventory. The superseded
C: archive and two historical derived E: caches now live in verified G: cold
storage; they are existing artifacts and must not be counted as new training
data. The active strict capture, self-contained combined cache, final spatial
cache, training runs, and checkpoints remain on their fast paths. Exact source
and destination paths, byte counts, SHA-256 reports, and final free-space
readings are recorded in
[STORAGE_RELOCATION_20260906.md](D:/.CODEX_Projects/OpenNR-VR/docs/STORAGE_RELOCATION_20260906.md).

## Earlier baseline state (superseded)

The active SkyrimVR installation is running the capture-reset build of Open Shaders DLSSNR VR 0.5.5 OpenNR. The installed CommunityShaders.dll is version 0.5.5.0, 43,745,792 bytes, SHA-256 751401C26DF6B9FCD7F6F3DD906EE6D57ED69D6F3C6EE6305D1C445C49E3FFD4. The source change is vendor commit 40631c3c and requests neural history reset before each OpenNR sequence. The previous active DLL is preserved in E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-capture-reset-0.5.5-20260906_002040.

The latest capture root is E:\OpenNR_Captures_StrictTemporal_0.5.5_20260906. Skyrim exited cleanly after the root stopped growing.

## Capture findings

The final capture root contains 78 sequence directories, 4,968 complete frames, and about 41.7 GB of raw artifacts. The strict metadata audit found:

- Feature 18 stereo route on every audited frame.
- Exact Feature 18 bound motion-vector resource metadata.
- Both eyes, pre-NR input, native depth, native motion vectors, and teacher output.
- Frame, sample, and host increments of one.
- First-frame history reset [true, true] for every sequence.
- No failed or partial frames, mid-clip resets, backpressure events, or dropped-frame gaps.

The byte audit found 39,744 artifacts with no missing files, duplicate IDs, duplicate hashes, all-zero color/depth/teacher images, or validator errors. It did find 158 all-zero raw motion-vector tensors. Those warnings are concentrated in one eye while the paired color and teacher tensors change and the other eye has populated motion vectors, so those sequences are excluded from temporal supervision.

The suspected interrupted final burst is seq-1788671650398-78. It contains 40 complete frames and an empty frame_00000041 directory instead of the intended 64 frames. It is preserved but excluded.

The four full-length sequences with eye-specific all-zero motion vectors are:

- seq-1788671404795-48: right eye zero in 43 of 64 frames.
- seq-1788671414977-49: right eye zero in 14 of 64 frames.
- seq-1788671421797-50: right eye zero in 55 of 64 frames.
- seq-1788671425120-51: right eye zero in 26 of 64 frames.

The raw data remains immutable. The authority files are:

- D:\.CODEX_Projects\OpenNR-VR\out\strict_final_temporal_audit_0.5.5_20260906.json
- D:\.CODEX_Projects\OpenNR-VR\out\strict_final_byte_audit_0.5.5_20260906.json
- D:\.CODEX_Projects\OpenNR-VR\out\strict_training_manifest_0.5.5_20260906.json
- D:\.CODEX_Projects\OpenNR-VR\out\strict_temporal_candidate_manifest_0.5.5_20260906.json

## Training cache

The accepted temporal candidate consists of 73 exact 64-frame sequences and 4,672 frames. Four anomalous sequences remain available for possible spatial-only use after a separate investigation; the incomplete sequence is not used for training.

The raw crop cache is E:\OpenNR_RawCropCache_StrictTemporal_0.5.5_20260906. It contains 9,344 stereo eye rows, 9,344 patches, and about 16.4 GB of cache arrays. The chronological sequence split is 46 train sequences, 12 validation sequences, and 15 held-out test sequences. The cache has strict_initial_reset true, zero invalid depth values, and 2,682,921 native motion values masked by the cache converter because they were nonfinite or outside the supported motion range. Cache helper tests pass.

## Model and runtime work

The previous spatial candidate, context_merged_style_v7_newcapture_0.5.5_20260906, remains unchanged and is the initialization parent for the current run. Its exported best-feature checkpoint is the known-good spatial baseline; it has not been installed into Skyrim as a runtime model.

The FP8 experiment remains research-only. Full Conv and MatMul FP8 built an engine but failed the parity gate, so it was not promoted. MatMul-only FP8 calibration completed but its build was stopped to avoid contention with live capture. FP6 is not exposed by the installed TensorRT/modelopt stack, and NVFP4 would require a separate graph-aware block/dynamic quantization path. No low-bit engine has been installed or used as the active runtime.

## Historical training run (superseded)

The run in progress is:

- Output: E:\OpenNR_Training\context_strict_temporal_v8_0.5.5_20260906
- Initialization: context_merged_style_v7_newcapture_0.5.5_20260906 best_feature.pt
- Dataset: E:\OpenNR_RawCropCache_StrictTemporal_0.5.5_20260906
- Steps: 16,000
- Batch: 4
- Learning rate: 2e-6 cosine schedule
- BF16 GPU autocast, VGG appearance weight 0.05, feature weight 0.05
- Separate best-MAE and best-feature checkpoints

The run completed at step 16,000 in 2,051.10 seconds. The best validation checkpoint was step 15,000:

- MAE 0.0228810
- PSNR 29.6975 dB
- Feature distance 0.0757478
- 35.05 percent improvement over the identity baseline

The final step-16,000 weights were slightly worse on validation (MAE 0.0229376), so the best checkpoints are the selected artifacts. The frozen 15-sequence test split gave both best-MAE and best-feature checkpoints the same result: MAE 0.0267324, PSNR 27.9083 dB, identity MAE 0.0400837, and 33.31 percent improvement over identity. This is a crop-space held-out result, not a live temporal or headset result.

Checkpoint hashes:

- best_mae.pt: 179261fc63fa5adff73fefc5d4109b54e7a2523d5c8df0b475a92e5d77b098de
- best_feature.pt: 1c950536a46fe82d5a44465112a66db4ee86ca7363f7cdaf8449ad34debb89f2
- portable best-feature export OpenNR_ContextStyle_v8_strict_temporal_best_feature.pt: d3fe3196ae8bdc86426a3da803ca910550314c196ba17f3c13265f7bc34532d9

The portable export is architecture context_v4 with 2,005,139 parameters and exact_state true. No model or low-bit engine was installed into Skyrim. This training run is complete and no further training job was started.

## Historical next steps (superseded)

1. Validate the completed best-MAE and best-feature checkpoints on the held-out sequence test split and record the result beside the cache and capture hashes.
2. Render a small broad A/B gallery against teacher and input for visual review; keep appearance resemblance separate from numerical metrics.
3. Do not install a model or low-bit engine into the active Skyrim profile until a controlled in-headset A/B verifies route selection, stereo delivery, frame time, and visual resemblance.
4. Investigate the four eye-specific motion-vector anomalies at the capture/resource binding level before admitting them to any temporal loss.
5. If the spatial candidate is accepted, add a sequence-aware temporal objective and evaluate it on held-out complete clips. The current long trainer uses the sequence-clean crop rows as spatial/context samples; it is not itself proof of recurrent temporal behavior.

This report records data integrity and training progress. It does not claim headset quality, comfort, live VR frame-time acceptance, or runtime activation.
