# Crop capture audit — OpenNR 0.5.5 — 2026-09-06

Root:

```text
E:\OpenNR_Captures_Temporal_Crops_0.5.5_20260906
```

The completed capture set contains **27 sequences and 1,728 complete records**. Every sequence contains 64 records. The structural validator reports:

- 1,728/1,728 complete frames;
- 0 partial frames and 0 failed frames;
- 13,824 required raw artifacts present;
- 0 missing files, duplicate IDs, duplicate hashes, or all-zero images/raw tensors;
- 0 backpressure events;
- 0 dropped frames;
- exact `+1` frame, sample, and host-frame transitions in every sequence.

Metadata is stable across the whole root:

- route: `feature18_stereo`;
- motion-vector contract: `exact_feature18_bound_resource`;
- color input: 2496×2688 per eye;
- native guide: 1664×1792 per eye;
- capture rate: 0 (every eligible frame);
- full-frame flags: false/false;
- teacher settings: intensity 2, local structure 2, local tone 2, skin structure -1, style 0, auto-mask enabled, UI correction disabled.

The strict temporal audit rejects all 27 sequences for one shared reason: every first record reports `history_reset: [false, false]`. No sequence has a mid-clip reset, gap, drop, or backpressure event. The relaxed audit with `--allow-missing-initial-reset` accepts all 27 sequences as contiguous crop temporal data, but the first-sample history state is not reset-qualified. These clips are safe for spatial/feed-forward training and conditional temporal experiments; a genuinely strict temporal model still needs one new burst whose first record is `[true,true]`.

Audit files:

```text
D:\.CODEX_Projects\OpenNR-VR\out\temporal_audit_crop_0.5.5_20260906.json
D:\.CODEX_Projects\OpenNR-VR\out\temporal_audit_crop_0.5.5_20260906_relaxed.json
```

Do not delete or rewrite these sequences. Keep the reset-qualified requirement separate from the otherwise excellent continuity and native-guide evidence.
