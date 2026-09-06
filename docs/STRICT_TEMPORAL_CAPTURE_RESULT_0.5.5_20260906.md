# Strict temporal capture result — OpenNR 0.5.5

Date: 2026-09-06
Source root: E:\OpenNR_Captures_StrictTemporal_0.5.5_20260906

The Skyrim session ended cleanly after the capture root stopped growing. The final root contains 78 sequence directories and about 41.7 GB of raw artifacts. The capture-reset build was active for this session; each sequence records the requested history reset at its first frame.

## Integrity results

The metadata audit passed the contiguous Feature 18 crop contract:

- 78 sequences were read.
- 4,968 complete frames were read.
- All observed frame, sample, and host increments were one.
- Every sequence began with stereo history reset [true, true].
- No failed or partial frames, capture errors, backpressure events, or dropped frames were reported.
- The route is feature18_stereo; motion vectors identify exact_feature18_bound_resource.

The exhaustive byte audit found 39,744 artifacts with no missing files, duplicate IDs, duplicate hashes, all-zero color/depth/teacher images, or validator errors. It did report 158 all-zero raw motion-vector tensors. Those warnings are material because they are concentrated in one eye while the paired image tensors change and the other eye has populated motion vectors.

## Training disposition

The manifest at D:\.CODEX_Projects\OpenNR-VR\out\strict_training_manifest_0.5.5_20260906.json is the authority for the next cache build.

| Disposition | Sequences | Frames | Use |
| --- | ---: | ---: | --- |
| accept_temporal | 73 | 4,672 | Temporal training candidate set |
| exclude_temporal_mv_anomaly | 4 | 256 | Preserve raw; spatial-only candidate after separate review |
| exclude_incomplete | 1 | 40 | Preserve raw; do not train |

The four motion-vector-anomalous sequences are:

- seq-1788671404795-48 — right-eye motion vectors are all-zero in 43/64 frames.
- seq-1788671414977-49 — right-eye motion vectors are all-zero in 14/64 frames.
- seq-1788671421797-50 — right-eye motion vectors are all-zero in 55/64 frames.
- seq-1788671425120-51 — right-eye motion vectors are all-zero in 26/64 frames.

The suspected interrupted burst is seq-1788671650398-78. It has 40 complete frames and an empty frame_00000041 directory rather than the intended 64 frames. It is excluded without deleting it.

The four anomalous sequences still have valid-looking color, teacher, and depth tensors, so they remain useful as possible spatial data. They must not be used for a motion-vector-conditioned temporal loss until the eye-specific resource behavior is understood.

## Next step

The accepted 73-sequence cache was built at E:\OpenNR_RawCropCache_StrictTemporal_0.5.5_20260906 and used for a completed 16,000-step context_v4 continuation. The best validation checkpoint reached MAE 0.0228810 and feature distance 0.0757478 at step 15,000. On the held-out 15-sequence test split it reached MAE 0.0267324, PSNR 27.9083 dB, and 33.31 percent improvement over identity. The portable best-feature export is E:\OpenNR_Training\context_strict_temporal_v8_0.5.5_20260906\OpenNR_ContextStyle_v8_strict_temporal_best_feature.pt.

The current trainer uses sequence-clean crop rows as spatial/context samples; it is not itself proof of recurrent temporal behavior. The next model-specific step is a sequence-aware temporal objective evaluated on held-out complete clips. Do not merge the anomalous or incomplete sequences into that temporal cache.

These checks establish file and cadence integrity only. They do not prove temporal image quality, headset delivery, stereo comfort, or live VR frame time.
