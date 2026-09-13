# OpenNR storage triage and cleanup — 2026-09-10

Status: completed successfully on 2026-09-10. No removal failures were reported.

## Decision boundary

The single retained student model is:

`C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`

- SHA-256: `40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`
- protected ordinary reference: approximately `0.013283985`
- reason for retention: this is the broad/temporal-safe control. The `0.011729875` finetune-v2 checkpoint was a narrow experimental frontier and failed the broad/temporal promotion gates, so it is documented but not retained as the operational model.

The cleanup is intentionally aggressive because the immediate objective is room for a large new capture. Historical metrics, hashes, rejection reasons, and lineage are kept in the repository reports; raw rejected captures and non-promoted checkpoints are not kept as training assets.

## Files and inputs retained

- The protected checkpoint above, plus its small `run.json`, `history.json`, `status.json`, and `step_zero_replay.json` metadata.
- Current aligned training inputs used by the protected run:
  - `E:\OpenNR_TrainingInputs\AlignedGuides_AllCohorts_20260907`
  - `E:\OpenNR_TrainingInputs\AlignedGuides_HighEffect_20260907`
  - `E:\OpenNR_TrainingInputs\AlignedGuides_RendererPilot_20260907`
  - `E:\OpenNR_TrainingInputs\RendererConditioningFreshSession_20260907_2114`
  - `D:\OpenNR_TrainingInputs\RendererStateDistillationStrict_20260908`
  - `C:\OpenNR\TrainingCache\RendererPairsStrict_20260908`
- Compact accepted derived caches that remain useful as retention material for the next training run:
  - `C:\OpenNR\TrainingCache\crop_temporal_every_frame_20260909_all18`
  - `C:\OpenNR\TrainingCache\full_eye_periodic_spatial_20260909`
  - `C:\OpenNR\TrainingCache\sparse_full_eye_anchor_crop_20260909`
  - `C:\OpenNR\TrainingCache\full_eye_renderer_conditioning_strict_20260909_retry2`
- DINO cache/weights under `C:\Users\oleks\.cache\torch\hub`, needed by the existing training/evaluation tooling.
- OpenNR source, scripts, docs, the capture setup backup, and the small FaceAudit output. Unrelated game/mod projects are out of scope.

## Removal groups

The following groups were classified as disposable or superseded:

1. All non-protected children of `C:\OpenNR\Training`, including scratch, calibration, capacity, renderer, temporal, Runpod-upload, and replay outputs. The protected model directory is reduced to the one checkpoint and four metadata files.
2. Old caches under `C:\OpenNR\TrainingCache`, including `student_v1`, the rejected full-eye pilot cache, the rejected clean7 cache, and the superseded renderer-conditioning duplicate.
3. Experimental inference outputs, research clones, Flux/GEN model weights, generated GEN targets, and obsolete local ML dependency environments under `C:\OpenNR`.
4. Rejected, superseded, or raw copies of captures and derived caches on C:, including the old pilot, full-eye state probe, invalid full-eye temporal runs, old renderer pilots, old temporal crops, and raw copies whose validated derived cache is retained.
5. Superseded E: raw captures, spatial caches, training-input copies, and all non-promoted E: checkpoint experiments.
6. `G:\OpenNR_ColdStorage`, which is an old OpenNR archive of raw captures and derived caches and is not referenced by the retained model or its current inputs.
7. Disposable pip download/wheel cache and selected large generated comparison galleries under the repository `out` directory.

## Safety checks

- No active student training or capture writer was present during the audit; the only Python process was the Codex runtime.
- The protected checkpoint hash is recorded above and is rechecked after cleanup.
- The cleanup uses explicit paths. Unrelated folders on D: and G: are not touched.
- `Remove-Item` is permanent rather than Recycle-Bin based. The report is the retained provenance record; removed raw data/checkpoints are not expected to be recoverable from the local disks.

## Pre-cleanup measured pressure

At the start of the final audit, free space was approximately:

| Drive | Free |
|---|---:|
| C: | 123.09 GiB |
| D: | 14.10 GiB |
| E: | 31.02 GiB |
| G: | 18.88 GiB |

The largest named disposable groups were `G:\OpenNR_ColdStorage` (551.71 GiB), `E:\OpenNR_Captures_StrictTemporal_0.5.5_20260906` (178.92 GiB), `C:\OpenNR\_Captures` (100.70 GiB), and the old C:/E training caches and checkpoints listed above.

## Post-cleanup verification

The retained checkpoint was rehashed after cleanup:

- SHA-256: `40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`
- result: unchanged from the pre-cleanup manifest
- retained model files present: checkpoint plus `run.json`, `history.json`, `status.json`, and `step_zero_replay.json`
- all 15 protected model/input/cache paths verified present
- all sampled removal roots verified absent, including `G:\OpenNR_ColdStorage`, `E:\OpenNR_Training`, `C:\OpenNR\Models`, `C:\OpenNR\_Captures`, the rejected full-eye pilot, the raw 18-sequence capture, and GEN static outputs

Measured free space after cleanup:

| Drive | Before | After | Reclaimed |
|---|---:|---:|---:|
| C: | 123.09 GiB | 1,020.25 GiB | 897.16 GiB |
| D: | 14.10 GiB | 20.42 GiB | 6.32 GiB |
| E: | 31.02 GiB | 421.72 GiB | 390.70 GiB |
| G: | 18.88 GiB | 570.64 GiB | 551.76 GiB |
| Total | 187.09 GiB | 2,033.03 GiB | 1,845.94 GiB |

The cleanup script is retained at `tools/storage_cleanup_20260910.ps1` as an explicit audit trail. The large raw captures and old checkpoints were permanently removed; they were not moved to the Recycle Bin. The next large capture has ample room on C: and E:, while the current model/input graph remains intact.

## Intentional leftovers

- `C:\OpenNR\TrainingCache` is now only the five retained compact caches listed above.
- `E:\OpenNR_TrainingInputs` is now only the four current E: input cohorts listed above; the strict renderer-state input remains on D:.
- `E:\OpenNR-VR-Poc-Venv` was left in place because it is an environment rather than training data and its use by the live capture setup was not disproven. It can be removed later after a successful new capture confirms it is not part of the capture/runtime path.
- `G:\OpenNR_Capture_Setup_Backups` was left in place because it is the rollback path for the live capture configuration.
- A few zero-byte/very small legacy manifest files and empty directory shells remain; they are immaterial to the storage target and were not worth risking a runtime/config reference for.
- The only matching live process after cleanup was Codex's local report HTTP server, not Skyrim, capture, or training.
