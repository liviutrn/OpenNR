# OpenNR storage relocation ledger — 2026-09-06

This document records storage-only relocations made to free fast-drive space.
The items listed here are existing OpenNR artifacts moved with their original
names and provenance. They are **not new captures, new training samples, or
additional model versions**. Any later inventory or dataset scan must treat the
G: copies as archived mirrors of the original paths.

## C: archive to G: cold storage

The superseded/reproducible archive was copied from:

```text
C:\OpenNR_Archive_OpenNR_Prune_20260906
```

to:

```text
G:\OpenNR_ColdStorage\OpenNR_Archive_OpenNR_Prune_20260906
```

The destination was verified against a pre-move source manifest using full
SHA-256 comparison:

- Files: 63 expected, 63 present
- Logical bytes: 148,078,563,977 expected and present
- Missing files: 0
- Extra files: 0
- Hash mismatches: 0
- Source manifest: `D:\.CODEX_Projects\OpenNR-VR\out\storage_move_open_nr_archive_source_20260906.json`
- Verification report: `D:\.CODEX_Projects\OpenNR-VR\out\storage_move_open_nr_archive_verification_20260906.json`

The G: copy contains these nine pre-existing artifact directories:

- `OpenNR_MergedSpatialCache_WithExcludedAux_0.5.5_20260906`
- `OpenNR_MergedSpatialCache_0.5.5_20260906`
- `OpenNR_MergedSpatialCache_20260905`
- `OpenNR_RawCropCache_0.5.3_20260905`
- `OpenNR_LegacySpatialAux_0.5.5_20260906`
- `OpenNR_RawCropCache_0.5.5_20260906`
- `OpenNR_DynamicGuides_Merged_0.5.5_20260906`
- `OpenNR_DynamicGuides_Merged_20260905`
- `OpenNR_AuxSpatialCache_ExcludedComplete_0.5.5_20260906`

The verification report reached `state: verified` before source cleanup. The
exact C: source was then removed by the completed Robocopy move; the final
check found `SourceExists: False`, while the G: destination still contained 63
files totaling 148,078,563,977 bytes. Robocopy reported zero failures and zero
mismatches. The G: copy is the recovery copy.

## E: derived-cache relocation

The following two derived caches were selected for verified cold storage
because their manifests identify them as historical derived products and
`test_used_for_tuning` is false:

```text
E:\OpenNR_RawCropCache_FreshTemporalClean_0.5.5_20260906
E:\OpenNR_RawCropCache_FreshNewDefault_0.5.5_20260906
```

Their verified destinations are:

```text
G:\OpenNR_ColdStorage\OpenNR_RawCropCache_FreshTemporalClean_0.5.5_20260906
G:\OpenNR_ColdStorage\OpenNR_RawCropCache_FreshNewDefault_0.5.5_20260906
```

These are not the active strict capture, current combined cache, final
all-source cache, or best checkpoint. Those fast-path artifacts remain on E:
for training. The E: copies were removed only after the verification report
below reached `state: verified`:

- Files: 16 expected, 16 present
- Logical bytes: 60,422,972,837 expected and present
- Missing files: 0
- Extra files: 0
- Hash mismatches: 0
- Source manifest: `D:\.CODEX_Projects\OpenNR-VR\out\storage_move_e_derived_source_20260906.json`
- Verification report: `D:\.CODEX_Projects\OpenNR-VR\out\storage_move_e_derived_verification_20260906.json`

The final check confirmed that both E: source paths no longer exist and both
G: destinations retain their complete file sets. The active combined-cache
`provenance.json` and `complete.json` now point at the archived G: root while
preserving the original complete/rows hashes.

## Active-path rule

Use E: for current training inputs, caches, and checkpoints. Use the G:
locations in this ledger only for cold restore, historical comparison, or
reconstruction. Do not count a G: archive directory as a new data source when
building manifests or calculating sample totals.

## C: NextGrid raw source to G: cold storage — 2026-09-07

The verified raw source was moved from:

```text
C:\OpenNR_Captures_NextGridPilot_0.5.5_20260906
```

to:

```text
G:\OpenNR_ColdStorage\OpenNR_RawCaptures_20260907\OpenNR_Captures_NextGridPilot_0.5.5_20260906
```

This was the first cleanup move from the 2026-09-07 storage triage. The source
was not touched until the destination had been copied and checked against the
source:

- Files: 215,250 expected and present
- Logical bytes: 225,587,369,167 expected and present
- Size: 210.095 GiB
- Pairwise SHA-256 comparisons: 215,250
- Hash mismatches: 0
- Missing files: 0
- Robocopy copy exit code: 1, success range
- Robocopy move exit code: 1, success range
- Final source path: absent
- Final destination path: present
- Compact verification summary: `D:\.CODEX_Projects\OpenNR-VR\out\storage_move_nextgrid_verification_20260907.json`

The full per-file hash list was compared during the move session but was not
persisted as a separate manifest; the compact summary above records the exact
counts, byte totals, and zero-mismatch result. The G: copy is an archived raw
source mirror, not new training data. The current high-effect cohort, active
combined caches, strict-temporal root, checkpoints, and current capture paths
were not moved or deleted.
