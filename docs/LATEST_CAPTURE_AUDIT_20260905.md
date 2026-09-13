# Latest crop capture audit — Open Shaders 0.5.3 OpenNR (2026-09-05)

## Dataset and intended grain

The audited root is:

```text
C:\OpenNR_Captures_Temporal_Crops_0.5.3_NoPreview_20260905
```

Each complete record is one Feature 18 stereo render sample with one centered 512×512 crop per eye and four stages: pre-NR input, post-NR teacher, native depth, and native motion vectors. The capture is raw-only for color (`write_color_previews=false`); the empty PNG paths are expected by the capture contract.

The root contains 120 sequence directories, 3,475 complete frame records, and 27,800 required raw artifacts. The raw tree occupies 29,166,021,032 bytes (27.16 GiB).

## Checks performed

- `python tools/validate_capture.py C:\OpenNR_Captures_Temporal_Crops_0.5.3_NoPreview_20260905 --json`
- `python tools/validate_temporal_capture.py C:\OpenNR_Captures_Temporal_Crops_0.5.3_NoPreview_20260905 --mode crop --allow-missing-initial-reset`
- Per-sequence metadata, frame ordering, artifact identity, dimensions, formats, raw file sizes, reset flags, guide scales, and capture settings profile.
- Runtime package recheck; the installed DLL remained version `0.5.3.0`, 20,779,008 bytes, SHA-256 `398E8B3F516659D5D8C7E59D4A3F6BF37F027D7A3A3CB05CD5496EE2B68ECD40`.

Machine-readable evidence is preserved in:

- `out/capture_audit_latest_0.5.3_NoPreview_20260905.json`
- `out/temporal_audit_latest_0.5.3_NoPreview_20260905.json`
- `out/latest_capture_quality_profile_20260905.json`
- `out/latest_capture_sample_metrics_20260905.json`
- `out/latest_capture_training_candidate_manifest_20260905.json`

## Findings

### Structural and byte integrity: pass

The normal validator reports 120 sequences, 3,475 complete frames, 0 partial frames, 0 failed frames, 27,800 artifacts, 0 missing files, 0 duplicate IDs, 0 duplicate hashes, 0 all-zero images, and 0 all-zero raw tensors. The independent profile found 0 missing raw files and 0 raw-size mismatches. Every raw artifact is exactly 1,048,576 bytes, matching the 512×512 crop and row pitch.

The observed contracts are stable:

- color input/teacher: `R8G8B8A8_UNORM`, 512×512;
- depth: `R32_FLOAT`, 512×512;
- motion vectors: `R16G16_FLOAT`, 512×512;
- color source rectangle: 2496×2688, crop `(992,1088,512,512)`;
- guide source rectangle: 1664×1792, crop `(576,640,512,512)`;
- both eyes are present for every complete frame;
- motion vectors are marked `exact_feature18_bound_resource`.

The guide spot-check over the first frame of every sequence found finite depth and motion values for every sampled value. This supports resource validity; it does not prove correct sign, scale, or visual quality beyond the recorded contract.

### Temporal integrity: mostly good inside sequences, reset gate still open

With the explicit relaxed policy that allows a missing initial reset, 111 of 120 sequences pass the crop temporal gate. The candidate manifest contains 3,435 complete frames, 6,870 eye pairs, and 27,480 raw artifacts.

The nine excluded sequences are:

- eight one-frame sequences: `seq-1788643661849-8`, `seq-1788643820885-23`, `seq-1788643876363-31`, `seq-1788643892627-37`, `seq-1788644017683-64`, `seq-1788644054635-75`, `seq-1788644116193-92`, and `seq-1788644260690-113`;
- `seq-1788643972441-59`, which contains a mid-clip reset and a host-frame jump of 93 at the same transition.

There were no backpressure events and no dropped-frame counters in the new root. This is a clear operational improvement over the previous 47-sequence crop root, whose temporal audit had 0 ready sequences and widespread queue backpressure/host gaps.

The remaining temporal limitation is reproducibility: all 120 sequence first frames record `history_reset=[false,false]`. Only one frame in the entire root records `[true,true]`, and it is the mid-clip reset in the excluded sequence. Therefore the strict temporal gate, which requires a reset-qualified first frame, is not passed by this capture. The relaxed candidate is suitable for spatial/feed-forward training and conditional for temporal training; the first sample of each sequence may depend on Feature 18 history from before capture.

### Teacher signal: present, but this is not a quality score

A diagnostic sample of the first frame from each sequence and both eyes found a median input-to-teacher RGB absolute difference of 10.95/255, p90 16.61/255, and no eye with a sampled difference below 1/255. This shows that the capture contains a non-trivial teacher target. It does not establish teacher visual quality, stereo correctness, or student equivalence.

## Training implications

The capture itself is healthy enough to preserve and use. The historical cache path expects color `png_path` values when it builds full-resolution rows, while this root intentionally has `png_required=false`, `png_written=false`, and empty PNG paths. A separate raw `R8G8B8A8_UNORM` crop loader/cache path is now implemented in `tools/build_raw_crop_cache.py`. It uses the already-verified raw tensors, avoids reintroducing PNG write pressure, and emits the same cache schema consumed by the current trainers. No runtime DLL change was required.

The built cache is `E:\OpenNR_RawCropCache_0.5.3_20260905`; its provenance and exact conversion contract are documented in `docs/RAW_CROP_CACHE_20260905.md`.

The first 12,000-step continuation over that cache completed successfully.
Validation and frozen-test results, checkpoint hashes, and the follow-up visual,
runtime, and reset-qualified temporal gates are recorded in
`docs/RAW_CROP_TRAINING_RESULT_20260905.md`.

`tools/train_long_student.py` now supports an explicit `--allow-new-cache` override for `--initialize` when rebinding a quality checkpoint to this new cache. Resume operations remain strict about cache identity.

Keep the capture immutable and use the built cache as the selection contract. For a first feed-forward continuation, use its 111 clean sequences with the frozen sequence-level train/validation/test split. Keep the eight one-frame records out of temporal windows; they remain available as optional spatial examples if a separate cache is built. Keep sequence 59 entirely out of the candidate because its reset/gap boundary cannot be repaired from metadata.

For a genuinely temporal model, collect at least one new burst after forcing a known Feature 18 history reset and verify `[true,true]` on the first record. That new reset-qualified burst should be used as the temporal acceptance anchor; it can be combined with the current corpus only after the raw loader and a split policy are in place.

## Scope limits

These checks establish capture-file integrity and a metadata/path training contract. They do not prove native guide sign/direction, stereo reprojection quality, temporal image quality, teacher/student visual resemblance, live SkyrimVR performance, or headset acceptance. The installed latest OpenNR package was not modified during this audit.
