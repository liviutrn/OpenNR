# OpenNR-VR project report — 2026-09-06

## Current state

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

## Current training run

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

## Next steps after the run

1. Validate the completed best-MAE and best-feature checkpoints on the held-out sequence test split and record the result beside the cache and capture hashes.
2. Render a small broad A/B gallery against teacher and input for visual review; keep appearance resemblance separate from numerical metrics.
3. Do not install a model or low-bit engine into the active Skyrim profile until a controlled in-headset A/B verifies route selection, stereo delivery, frame time, and visual resemblance.
4. Investigate the four eye-specific motion-vector anomalies at the capture/resource binding level before admitting them to any temporal loss.
5. If the spatial candidate is accepted, add a sequence-aware temporal objective and evaluate it on held-out complete clips. The current long trainer uses the sequence-clean crop rows as spatial/context samples; it is not itself proof of recurrent temporal behavior.

This report records data integrity and training progress. It does not claim headset quality, comfort, live VR frame-time acceptance, or runtime activation.
