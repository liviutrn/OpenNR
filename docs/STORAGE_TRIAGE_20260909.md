# OpenNR storage triage — 2026-09-09

This pass separates the unreliable USB disk from a newly attached Linux archive
disk. No capture source, checkpoint, or training cache is deleted based on an
unverified copy.

## Device decisions

| Device | Identity | Current state | Decision |
| --- | --- | --- | --- |
| `H:` | Seagate One Touch, USB, NTFS | Read/write and readback probes failed with I/O-device errors; an earlier verified tree became unreadable | **Retired from OpenNR storage. Do not write, delete, or trust it until independently recovered.** |
| `/dev/sde1` | WDC WD200EDGZ-11B9PA, USB, ext4, label `usb_hdd_20tb`, UUID `066661e4-c349-4cce-86b6-59b92f47cd4f` | 18.2 TiB partition, about 9.0 TiB free; read-only mount is accessible; non-destructive `e2fsck -fn` found free-block and free-inode count mismatches | **Promising cold-storage target, but write-disabled pending an authorized filesystem repair and a clean recheck.** |

The Linux disk is mounted at `/mnt/wsl/wd_elements_20tb` with
`ro,relatime,norecovery`. Existing `DMS_*`, `PRIVATE_VAULT`, `_incoming`,
`lost+found`, and test files are user-owned archive content and remain
untouched. The proposed OpenNR root is
`/mnt/wsl/wd_elements_20tb/OpenNR-ColdStorage/`, but it has not been created.

## Non-destructive Linux-drive check

The partition was unmounted cleanly before inspection. `e2fsck -fn /dev/sde1`
completed without a reported device I/O error, but it reported:

- free blocks mismatch: `2651839602` in metadata vs `2651839598` counted;
- free inodes mismatch: `305097610` in metadata vs `305097606` counted;
- many extent trees that could be shortened or narrowed (repair would optimize
  them, but this is not a clean read-only result);
- `87158/305184768` files and `2231107982/4882947584` blocks in use at scan
  time.

Because the partition contains existing user data, no automatic `fsck -y`,
`e2fsck -p`, or write mount was attempted. The disk is remounted read-only
until the owner authorizes a maintenance repair window and the partition can be
checked again. The complete machine-readable evidence is in
`out/storage_triage_20260909/linux_drive_manifest.json`.

## OpenNR data inventory and hot/cold policy

Sizes below are the measured source trees before any new Linux-disk transfer.

| Tree | Size | Decision |
| --- | ---: | --- |
| `C:\OpenNR_Captures_FullRes_Pilot_20260904` | 117.41 GiB | Previously copied to H: and source removed only after verification; the H: destination is now unavailable. Do not alter the C: junction until H: is recovered. |
| `C:\OpenNR_Captures_FullEyeTemporalPilot_20260908` | 88.38 GiB | Source remains intact. Copy to the Linux target only after it is repaired, mounted `rw`, and passes a probe. |
| `C:\OpenNR\_Captures\_FullRes` | 100.70 GiB | Historical raw capture; cold-copy later, one tree at a time, with manifest and hash verification. |
| `C:\OpenNR_Captures_Temporal_Crops_20260905` | 29.25 GiB | Historical raw capture; cold-copy later. |
| `C:\OpenNR_Captures_Temporal_Crops_0.5.3_NoPreview_20260905` | 27.16 GiB | Historical raw capture; cold-copy later. |
| `C:\OpenNR_Captures_Temporal_20260905` | 24.75 GiB | Historical raw capture; cold-copy later. |
| `C:\OpenNR_Captures_RendererStatePairs_0.5.7_20260908` | 22.58 GiB | Preserve the already-built NVMe cache; cold-copy the raw source later. |
| `C:\OpenNR\TrainingCache` | 20.68 GiB | Keep hot; derived caches are used by evaluation/training. |
| `C:\OpenNR\Training` | 20.80 GiB | Keep hot; current and comparison checkpoints remain immediately usable. |
| `D:\.CODEX_Projects\OpenNR-VR\out` | 4.34 GiB | Keep warm until the current audit and TensorRT checks are closed. |

The raw capture sources total roughly 410 GiB. The new Linux disk has ample
space, but capacity alone is not a reason to write while its filesystem check
is non-clean.

## Relocation contract after repair

After a clean, user-approved filesystem repair and a successful write/read
probe, create only this new root:

```text
/mnt/wsl/wd_elements_20tb/OpenNR-ColdStorage/
  RawCaptures/
  DerivedArchives/
  Manifests/
  Logs/
  Checksums/
```

Copy one explicitly named capture tree at a time with resumable `rsync` from
`/mnt/c/...`. Before removing any NVMe source, require matching file count and
byte sum plus representative SHA-256 checks. Preserve the source until those
checks and a no-op comparison pass. Keep current caches, checkpoints, runtime
files, and audit outputs on NVMe. Never move or modify the unrelated existing
archive directories on the Linux disk.

The next OpenNR-specific warm operation remains materializing the strict
11-sequence, 64-frame crop cache on C:, followed by cache-integrity and
baseline-quality checks. The eight backpressure-gapped sequences stay
preserved and excluded from recurrent training; they are not silently dropped.

## Post-materialization update — 2026-09-09

The strict crop cache was already complete before this pass. A separate
renderer-conditioning overlay was then materialized from the same 11 selected
sequences and 1,408 eye rows:

| New derived tree | Measured size | State |
| --- | ---: | --- |
| `C:\OpenNR\TrainingCache\full_eye_renderer_conditioning_strict_20260909_retry2` | 0.73 GiB (`conditioning.npy` plus manifests) | Complete; hash-verified; renderer conditioning only; source cache and raw capture unchanged |
| `C:\OpenNR\Training\semantic_renderer_conditioned_pair_20260909` | 1.10 GiB | Complete matched control/arm; both endpoints retained; no promoted checkpoint |

The successful overlay payload is SHA-256
`0303f738267aeab1683de7f34f981ed5ed2821c7e0016cba6040f7de7e038df0` and its
source strict-cache row identity is
`efbd159ad069fbd128fb28a890ff53a07fa968ae67f1182ad259fc6ef47e13a1`. The
first builder preflight left an incomplete scratch directory at
`C:\OpenNR\TrainingCache\full_eye_renderer_conditioning_strict_20260909`;
it was not used or deleted because storage is not constrained and the exact
cleanup was not necessary.

The final read-only capacity check showed approximately 300.3 GiB free on C:,
37.9 GiB on D:, 31.1 GiB on E:, and 18.9 GiB on G:. No raw capture, accepted
cache, checkpoint, or provenance directory was removed. The H: device remains
retired from OpenNR use, and the WDC ext4 archive remains read-only pending
owner-authorized repair and a clean recheck. Runpod was not rented; the local
GPU fit the work and the remaining credit is preserved.

## Prepared every-frame full-eye capture budget — 2026-09-09

The next evidence tranche has a separate disabled-by-default configuration at
`config/opennr_capture_full_eye_temporal_every_frame_20260909.example.json`.
It requests 64 full-frame stereo records at 80 Hz with one center crop and all
six renderer conditionings. The example validates with `valid: true`, no
warnings, and `enable_capture=false`. The same five capture fields were then
applied to the live profile after a byte-identical backup; the live profile
validates with `valid: true` and has consumed no capture storage yet. The
earlier full-resolution audit measured
approximately 0.25 GiB per full-frame stereo record, so a first 64-frame run
could approach 16 GiB before derived caches. The first run should therefore
be audited before any additional scenes are recorded, and the four-scene
initial budget should be treated as an upper bound rather than a guaranteed
allocation.

## Post-capture and crop-temporal re-arm — 2026-09-09

The bounded full-eye run produced two complete 64-frame sequences before the
profile was changed:

| Sequence | Measured size | State |
| --- | ---: | --- |
| `C:\OpenNR_Captures_FullEyeTemporalEveryFrame_20260909\seq-1788993098503-1` | 13.59 GiB | 64/64 complete; preserved; strict temporal gate rejected host gaps/backpressure |
| `C:\OpenNR_Captures_FullEyeTemporalEveryFrame_20260909\seq-1788993615492-2` | 13.41 GiB | 64/64 complete; preserved; strict temporal gate rejected host gaps/backpressure |

The two sequences occupy approximately 27.00 GiB in total. After the
validator's crop-only renderer-conditioning rule was corrected, exhaustive
validation found no errors, missing files, duplicate IDs or duplicate hashes.
All-zero motion-vector tensors remain explicit warnings (3 in sequence 1 and
67 in sequence 2); the source trees remain unchanged.

After the game and SteamVR were closed, the live profile was changed to the
lower-I/O crop-temporal contract. The new root is
`C:\OpenNR_Captures_TemporalCrops_EveryFrame_20260909`; it does not exist yet,
so no crop capture bytes have been added. The live profile is
`E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json`
with SHA-256
`6e770b9b9a193bd959b7bc404e4583ddd1472ede7c9dd00c1034ce3f97193c6d`.
Its pre-edit backup is
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-crop-temporal-20260909\SettingsUser.before.json`
with SHA-256
`ccde5515081396076715fba06ff66430456adf50a4995ef273ba77de76762dd0`.
The crop profile retains `write_color_previews=false`, so the next burst is
expected to be materially smaller and faster than the full-eye masters.

The latest capacity check after capture showed approximately C: 272.78 GiB,
D: 37.85 GiB, E: 31.05 GiB and G: 18.88 GiB free. No older data was removed;
the two new masters, their provenance and the earlier caches/checkpoints remain
available for the separate spatial/color and temporal experiments.

## Crop-temporal capture accepted — 2026-09-09

The rearmed lower-I/O contract created two complete sequences at
C:\OpenNR_Captures_TemporalCrops_EveryFrame_20260909. Each contains 64/64
records and is approximately 1.19 GiB; the pair adds approximately 2.38 GiB.
The monitor found 128 complete records, contiguous frame/sample/host IDs,
initial [true, true] resets, zero backpressure, and zero dropped frames.
The strict crop validator accepted both sequences
(temporal_ready_sequences=2) and the exhaustive validator found 2,560
artifacts with zero missing files, duplicate IDs, duplicate hashes, errors,
warnings, or all-zero image/raw payloads. These are retained as eligible
temporal-training source data.

Current read-only capacity after this capture was approximately 270.19 GiB
free on C:, 37.85 GiB on D:, and 31.00 GiB on E:. No deletion or migration was
performed. The large full-eye masters remain retained for spatial/teacher/color
work, while the crop pair is the first structurally accepted temporal tranche.

## Superseding 18-sequence capture, cache, and training storage state — 2026-09-09

The two-sequence section immediately above is historical. The user completed
the capture session, and the final authoritative crop-temporal root is:

C:\OpenNR_Captures_TemporalCrops_EveryFrame_20260909

It contains 18 complete 64-frame sequences, 1,152 committed frames, 2,304
eye rows, and 23,040 exhaustively validated artifacts. The raw root measures
22,968,598,213 bytes, approximately 21.39 GiB. The all-18 cache is materialized
at:

C:\OpenNR\TrainingCache\crop_temporal_every_frame_20260909_all18

The cache is schema 2, complete, finite, hash-bound, and split by sequence into
11 train / 3 validation / 4 test sequences. Its raw arrays are RGB
[2304, 2, 3, 512, 512], guides [2304, 5, 128, 128], and context
[2304, 8, 96, 96]. The cache builder and integrity test passed. Both paired
training runs and the independent test replay completed without needing
additional local scratch space beyond the retained outputs.

The final read-only capacity check after replay/validation showed approximately:

| Drive | Free space |
| --- | ---: |
| C: | 240.77 GiB |
| D: | 37.64 GiB |
| E: | 31.02 GiB |

No raw capture, accepted cache, checkpoint, or provenance directory was
deleted or migrated. The eight low-information all-zero auxiliary raw warnings
and the localized eight-record gbuffer_specular outlier are documented in the
capture report; no source data was silently discarded. The older full-eye
masters remain retained for spatial/teacher/color work, and the 18-sequence
crop cache remains retained as the current temporal control.

The local RTX 5070 Ti completed the paired arms and replay with peak usage
around 10.1 GiB, so Runpod was not rented and the remaining $3 credit is
preserved. Additional VRAM would not address the observed protected-cohort
regression. The full quality decision is in
[CROP_TEMPORAL_CONTINUATION_20260909.md](CROP_TEMPORAL_CONTINUATION_20260909.md).

