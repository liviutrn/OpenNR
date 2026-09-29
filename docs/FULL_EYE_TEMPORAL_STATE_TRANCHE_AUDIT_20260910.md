# Full-Eye Temporal State Tranche Audit — 2026-09-10

## Scope

Read-only audit of `C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910` after the first collection run. No capture data was moved, deleted, or modified.

## Result

The tranche currently contains **9 sequences / 144 frames**. All 9 sequences pass the strict metadata/path gate in `master` mode:

- 16/16 complete frames per sequence;
- full-frame master resources present for every frame;
- initial reset flags `[true, true]`;
- no mid-sequence reset;
- contiguous host, frame, and sample IDs;
- zero backpressure events;
- zero dropped frames;
- zero strict temporal errors or warnings.

The exhaustive artifact validator reported:

- 9 sequences;
- 144 complete frames;
- 4,032 artifacts;
- 0 partial or failed frames;
- 0 missing files;
- 0 duplicate IDs;
- 0 duplicate hashes;
- 0 all-zero images;
- 0 hard errors.

## Content warnings

The exhaustive validator reported **34 all-zero raw motion-vector tensors**. These are warnings, not missing-file errors:

- sequence `seq-1789063628889-1`: both eyes in frames 2–8 and 10–16;
- sequence `seq-1789063809364-3`: eye 1 in frames 1–3 and 8–10.

The affected sequences remain structurally usable, but the affected frames should not be treated as strong motion-supervision examples until scene motion/content is reviewed. This may be valid for static or near-static content; it is not evidence that the full-frame capture path dropped data.

## User-confirmed interpretation

The user confirmed that the all-zero raw motion frames occurred while the headset was intentionally placed on the table. These frames are valid static/state-anchor supervision, not missing or corrupted capture data. They remain in the tranche and should be included in static-anchor analysis, while not being counted as dynamic-motion coverage.

## Decision

The capture profile is currently demonstrating the required I/O behavior. Continue collecting with the same settings, one 16-frame burst at a time, while adding controlled motion and scene diversity. Do not press the burst key during a running burst, and wait for the output to finish flushing before starting the next one.

Stop and investigate if any later sequence shows backpressure, dropped frames, host/frame/sample gaps, incomplete full-frame resources, or fewer than 16 complete frames.

## Follow-up batch validated 2026-09-10

Five additional sequences were added after the initial nine:

- `seq-1789071178359-1`;
- `seq-1789071316621-2`;
- `seq-1789071448597-3`;
- `seq-1789071604237-4`;
- `seq-1789071762719-5`.

The strict temporal validator now reports 14/14 temporal-ready sequences and
224/224 complete frames. Every sequence has 16 contiguous frames, an initial
`[true, true]` reset, complete synchronized full-frame resources, zero
backpressure events, and zero dropped frames.

The exhaustive format-aware capture validator reports 224 complete frames and
6,272 complete artifacts, with zero missing files, partial frames, failed
frames, duplicate IDs, duplicate hashes, all-zero RGB images, or hard errors.
The only 34 all-zero raw motion warnings remain in the previously audited old
sequences 1 and 3; none occur in the five new sequences.

The follow-up batch occupies approximately 16.9 GiB of raw capture data, and
the full tranche currently occupies approximately 48.3 GiB.

The auxiliary `audit_master_capture.py` tool reports its five new sequences as
having invalid frames because its decoder does not support the renderer
conditioning formats `24`, `26`, and `56`. The per-frame errors are the literal
unsupported format IDs, not missing or malformed files. Those renderer
conditionings are crop-only by design; the format-aware `validate_capture.py`
validator recognizes their byte sizes and found no errors. The auxiliary tool
also found zero orphan files and no sequence-level errors. Its unsupported
format limitation must be fixed or explicitly accounted for before using it as
the renderer-conditioning acceptance gate.

## Additional folder rechecked 2026-09-12

The separate folder `C:\OpenNR_Captures_LearnedResidualStudent_20260911`
contains five more 16-frame sequences. The byte/PNG/raw validator reports 80
complete frames and 1,280 complete artifacts, with zero missing files, partial
or failed frames, duplicate IDs, duplicate hashes, all-zero RGB images, or hard
errors. The nine all-zero raw-motion warnings are confined to the fifth
sequence and are content warnings, not missing files.

Four of the five sequences are strict temporal-ready clips:

- `seq-1789177812541-1`;
- `seq-1789178401151-2`;
- `seq-1789178469272-3`;
- `seq-1789178646427-4`.

Sequence `seq-1789178720325-5` is retained but excluded from strict temporal
training because it has a second `[true, true]` history reset at frame 14. Its
first segment has only 13 frames and its post-reset segment has only 3 frames,
so neither segment satisfies the current 16-frame temporal candidate contract.

These five sequences were captured while
`capture_renderer_conditionings=false`. They are therefore usable as a
separate full-eye RGB/teacher/depth/motion tranche, but they are not valid
renderer-state-conditioning evidence and must not be silently mixed into the
renderer-state tranche. Their rechecked audit is
`out/learned_residual_capture_audit_20260911_rechecked_20260912.json`; the
strict candidate manifest contains the four eligible sequences at
`out/learned_residual_temporal_candidate_20260912.json`.

The installed profile was corrected on 2026-09-12 after this recheck: renderer
conditionings are enabled, the next output is isolated at
`C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260912`, and the speed-safe
16-frame/80-FPS/queue-32/no-preview settings remain unchanged. The profile
backup and rollback are under
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-fast-full-eye-state-20260912`.

## Validators

```powershell
python tools\\validate_temporal_capture.py `
  C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910 `
  --mode master `
  --expected-pass-count 1

python tools\\validate_capture.py `
  C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910
```
