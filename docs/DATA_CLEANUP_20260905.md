# OpenNR capture cleanup — 2026-09-05

SkyrimVR was closed before cleanup. The pre-delete manifest with per-file
SHA-256 hashes is [out/data_cleanup_20260905/manifest_pre_delete.json](../out/data_cleanup_20260905/manifest_pre_delete.json), and the verified result is [out/data_cleanup_20260905/manifest_post_delete.json](../out/data_cleanup_20260905/manifest_post_delete.json).

Removed data:

- nine one-sample crop probes from `C:\OpenNR_Captures_Temporal_Crops_20260905`;
- the old supplemental sequence with no committed `frames.jsonl`;
- the explicitly quarantined one-frame capture tree;
- the uncommitted crash-tail directory `frame_00000015` from the 2024-09-04 full-resolution pilot.

The cleanup removed 256 files totaling 605,983,840 bytes (0.564 GiB). Every
target was checked against an allowed capture root before deletion, and every
target was verified absent afterward.

Retained data is complete or useful source evidence:

- `C:\OpenNR_Captures_FullRes_Pilot_20260904` — the audited full-resolution
  spatial masters; the three failed metadata records remain excluded by the
  audit manifest;
- `C:\OpenNR_Captures_Temporal_20260905` — a complete full-frame stress master
  preserved for spatial/diagnostic use even though its host cadence is not
  temporal-ready;
- `C:\OpenNR_Captures_Temporal_Crops_20260905` — complete crop pairs retained
  for possible spatial/crop experiments; they are not accepted as strict
  temporal clips because of host-frame gaps and missing initial resets;
- the verified older supplemental copy under
  `C:\OpenNR\_Captures\_FullRes\_Pilot\_20260904`.

No retained capture was deleted solely because it failed the temporal gate;
those files still contain valid input/teacher/guide pairs for non-temporal
experiments.
