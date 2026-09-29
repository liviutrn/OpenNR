# OpenNR storage cleanup — 2026-09-06

The E: volume was approaching capacity during the OpenNR training/data
iteration. The cleanup preserved the authoritative training sources and moved
only superseded or reproducible derived artifacts to the explicit archive
directory:

```text
C:\OpenNR_Archive_OpenNR_Prune_20260906
```

The move was recoverable rather than destructive. Each directory was moved by
its exact absolute path, then verified by file count and summed byte length.
The archive contains 9 directories and approximately 137.91 GiB of logical
data:

The verified cold-storage destination for this existing archive is now:

```text
G:\OpenNR_ColdStorage\OpenNR_Archive_OpenNR_Prune_20260906
```

This is a storage relocation of the archive described below, not a new dataset.
The source/destination manifest and full SHA-256 verification are recorded in
`docs/STORAGE_RELOCATION_20260906.md` and the two JSON reports under `out\`.

| Archived directory | Files | Logical size |
|---|---:|---:|
| `OpenNR_LegacySpatialAux_0.5.5_20260906` | 5 | 10.88 GiB |
| `OpenNR_MergedSpatialCache_20260905` | 8 | 28.48 GiB |
| `OpenNR_MergedSpatialCache_0.5.5_20260906` | 8 | 34.56 GiB |
| `OpenNR_MergedSpatialCache_WithExcludedAux_0.5.5_20260906` | 8 | 35.60 GiB |
| `OpenNR_AuxSpatialCache_ExcludedComplete_0.5.5_20260906` | 8 | 1.04 GiB |
| `OpenNR_DynamicGuides_Merged_20260905` | 5 | 4.44 GiB |
| `OpenNR_DynamicGuides_Merged_0.5.5_20260906` | 5 | 4.75 GiB |
| `OpenNR_RawCropCache_0.5.3_20260905` | 8 | 12.08 GiB |
| `OpenNR_RawCropCache_0.5.5_20260906` | 8 | 6.08 GiB |

The first directory is the incomplete failed legacy-cache build superseded by
`E:\OpenNR_LegacySpatialAux_0.5.5_20260906_v2`. The merged caches and dynamic
guide caches are intermediate products superseded by
`E:\OpenNR_MergedSpatialCache_AllSpatialSources_0.5.5_20260906`, which is a
self-contained final cache. The two raw crop caches are derived caches; their
capture sources remain available in their recorded provenance and the final
all-source cache remains on E:.

The following authoritative artifacts were intentionally kept on E::

- `E:\OpenNR_Captures_StrictTemporal_0.5.5_20260906`
- `E:\OpenNR_RawCropCache_StrictTemporal_0.5.5_20260906`
- `E:\OpenNR_MergedSpatialCache_AllSpatialSources_0.5.5_20260906`
- `E:\OpenNR_LegacySpatialAux_0.5.5_20260906_v2`
- `E:\OpenNR_FullResMasterSpatialAux_0.5.5_20260906`
- `E:\OpenNR_Training`

No model checkpoint or training run was deleted. The raw strict capture and
older raw capture roots were also left in place. After the move, the strict,
all-source and legacy caches each passed `tools/test_raw_crop_cache.py`, and
the required array shapes and finite guide/context checks remained valid. That
earlier checkpoint reading is superseded by the final post-relocation
inventory below. Free-space readings vary with normal OS activity, so these are
the values observed immediately after the verified moves.

## Relocation status update

The archive copy from `C:\OpenNR_Archive_OpenNR_Prune_20260906` to
`G:\OpenNR_ColdStorage\OpenNR_Archive_OpenNR_Prune_20260906` completed with
63/63 files and 148,078,563,977/148,078,563,977 bytes. Full SHA-256
verification reported zero missing files, zero extras, and zero mismatches.
The C: source was removed only after that verified result. The final check
confirmed that the source path no longer exists and the G: destination still
contains all 63 files and all 148,078,563,977 bytes. This is an archive
relocation, not new training data; see `docs/STORAGE_RELOCATION_20260906.md`.

## E: derived-cache relocation status

Two historical derived caches were copied to G: cold storage and verified by
full SHA-256 comparison before their exact E: source directories were removed:

| Original E: path | Verified G: path | Files | Logical bytes |
|---|---|---:|---:|
| `E:\OpenNR_RawCropCache_FreshTemporalClean_0.5.5_20260906` | `G:\OpenNR_ColdStorage\OpenNR_RawCropCache_FreshTemporalClean_0.5.5_20260906` | 8 | 30,453,151,436 |
| `E:\OpenNR_RawCropCache_FreshNewDefault_0.5.5_20260906` | `G:\OpenNR_ColdStorage\OpenNR_RawCropCache_FreshNewDefault_0.5.5_20260906` | 8 | 29,969,821,401 |

The combined E: cache is self-contained and remains on E:. Its provenance
metadata was updated to the verified G: path for the historical fresh strict
source; the original complete and rows hashes were preserved. These G:
directories are existing-data cold storage and must not be counted as new
training data.

## Final observed volume state

Immediately after the relocations and active-cache validation:

| Volume | Free space |
|---|---:|
| C: | 298.27 GiB |
| E: | 110.13 GiB |
| G: | 380.26 GiB |

The C: archive relocation freed 148,078,563,977 bytes (about 137.91 GiB)
from C:. The two E: derived-cache relocations freed 60,422,972,837 bytes
(about 56.27 GiB) from E:. No active strict capture, current combined cache,
final spatial cache, training run, or checkpoint was moved or deleted.
