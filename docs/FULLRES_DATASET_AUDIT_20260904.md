# OpenNR-VR full-resolution dataset audit — 2026-09-04

## Overall assessment

The new C: capture is structurally trustworthy for a first spatial distillation
run, with explicit exclusions. It is not yet a temporal training set and it is
not evidence that a student can replace Feature 18 in live stereo VR.

The source recording is `C:\OpenNR_Captures_FullRes_Pilot_20260904`. The
preserved copy made by the capture move is separate:
`C:\OpenNR\_Captures\_FullRes\_Pilot\_20260904\OpenNR_Captures_FullRes_Pilot_20260904`.
The move verification manifest is
`C:\OpenNR\capture-move-verified.csv`; the source recordings were not rewritten
by this audit.

## Audit evidence

The exhaustive audit in `out/fullres_audit_20260904` read every referenced PNG
and raw tensor in the new source tree. It checked metadata/schema identity,
frame ordering, complete stage/eye/crop coverage, safe relative paths, raw byte
sizes, PNG decode and dimensions, raw-to-PNG equality for color, finite tensor
values, source/crop bounds, full-frame completeness, duplicate IDs, duplicate
hashes, and exact crop-versus-full-frame consistency. It also recorded SHA-256
hashes and an HTML/contact-sheet visual review.

One representative 20-frame sequence was independently checked with the
existing `tools/validate_capture.py`; it passed with 20 complete master frames,
800 artifacts, no missing files, duplicate IDs, duplicate hashes, or zero data.
The fixture tests in `tools/test_master_audit.py` prove that truncated PNG/raw
files, an orphan file, and a torn JSONL tail are reported without discarding an
earlier readable record.

The aligned guide geometry and loader are tested by
`tools/test_master_dataset.py`. It exercises mismatched-resolution pixel-center
sampling, invalid-guide masks, finite tensors, all three prepared splits, and
one CUDA optimizer step. The saved result is
`out/fullres_audit_20260904/loader_validation.json`.

## New C: full-resolution pilot

| Item | Result |
| --- | ---: |
| Sequence directories | 58 |
| Frame records | 507 |
| Complete records | 504 |
| Failed records | 3 |
| Committed stereo frame pairs retained for spatial training | 491 |
| Retained eye pairs | 982 |
| Fixed aligned 512×512 patches (4 locations per eye) | 3,928 |
| Duplicate full tensors | 0 |
| Orphan files | 19 |
| Referenced bytes | 126.06 GB / 117.40 GiB |
| Color per eye | 2496×2688, R8G8B8A8_UNORM |
| Native guides per eye | 1664×1792 |
| Teacher route | Feature 18 stereo, 100% model resolution, one pass |
| Teacher settings | identical across all 507 records |

The three failed records are frames 2–4 of
`seq-1788567981150-27`. Their manifest status is `failed` with
`failure_reason=gpu_query_timeout_or_failure`; they are excluded. The last
capture sequence, `seq-1788574213393-26`, has 14 committed complete records.
Its `frame_00000015` directory contains 19 files left by the crash, but no
committed frame record; the orphan tail is excluded. This is the expected
crash-tail handling: the preceding committed records remain usable and the
uncommitted tail is never inferred into the dataset.

The output writer reported no dropped frames. Queue pressure did occur, with a
maximum `backpressure_events_before=31`, so sustained full-resolution capture
was close enough to the queue limit that the next run should use fewer crops or
a shorter burst while confirming that pressure does not affect the game.

The saved `CommunityShaders.log` contains a short Streamline/FOVEATED failure
cluster at 22:01:24–22:01:25, before the later sequences resumed. The affected
log entries report fallback to the standard DLSS path; subsequent committed
records still carry the expected Feature 18 route metadata. No Skyrim crash dump
or Windows Application Error event was found for the final 22:10 capture tail,
so the cause of the reported game crash remains unverified. The orphan-tail
policy is therefore based on commit integrity, not a claim about the crash
mechanism.

The full-frame input and teacher images are visibly distinct and the two eyes
are never byte-identical in valid records. The full-frame teacher-input MAE in
the audit is 0.03218 on average in normalized RGB, ranging from 0.00726 to
0.06259; this only proves there is a measurable teacher signal, not that the
teacher is perceptually correct or that the student will match it.

## Guide and temporal findings

Depth is finite in all inspected full-frame records and remains in the captured
range `[0,1]`. Native motion data contains no non-finite values. The audit
counts 2,617,642 raw motion components beyond the exploratory ±0.25 input
threshold out of 6,011,486,208 components (0.04354%). They are left untouched
on disk and masked/bounded only in the student representation. The raw motion
range reaches about `[-1.201, 2.293]`, so a student must not consume it without
the bounded preprocessing and validity mask.

No valid record has `history_reset=true`. The host-frame gap has percentiles
`min=1`, `p50=22`, `p95=181.8`, and `max=241`; only five adjacent stored record
pairs are one rendered frame apart. These are sampled spatial records, not
continuous clips. They cannot support a temporal recurrent loss or motion-based
reprojection claim.

The existing crop artifacts must not be paired directly by file name with the
native guide crops. A 512×512 color crop and a 512×512 guide crop cover
different fields of view because the source rectangles are 2496×2688 and
1664×1792. `tools/master_dataset.py` instead maps color pixel centers into the
native guide grid, selects the correct per-eye X/Y motion scales, and returns
validity masks.

## Prepared split

The prepared JSONL is
`out/fullres_audit_20260904/training_manifest.jsonl`. It is a reference manifest
pointing to the immutable full-frame masters, not a second 126 GB copy.

The split keeps both eyes and all patches of a frame together. The first capture
process contributes 26 train sequences, two guard sequences, and four validation
sequences. The second process contributes 26 held-out test sequences. The guard
band is the two sequences immediately before validation. This prevents the
nearest temporal neighborhood from sitting on the training side of the
validation boundary. It does not prove scene, location, character, or weather
disjointness; that remains an open benchmark limitation.

The 16 exclusions in `out/fullres_audit_20260904/exclusions.json` are the three
failed records plus the 13 guard-band records. `duplicates.json` is empty.

## Supplemental preserved captures

The older moved full-resolution pilot is audited in
`out/fullres_pilot_audit_20260904`. It contains 42 sequence directories and
280 complete records. One directory, `seq-1788555794130-1`, has 49 orphan
payload files and no `frames.jsonl`; it is excluded from any model index. Of
the 280 committed records, 278 use 2496×2688 color and 1664×1792 guides; two
use 1497×1612 color and 998×1075 guides. All committed records use the expected
Feature 18 stereo/100%/one-pass route. The supplemental set has no failed
frame records, but it has only three consecutive stored frame pairs and one
guide-outlier frame, so it is not a temporal set either.

The older crop-only dataset at
`C:\OpenNR\_Captures\_FullRes\_Pilot\_20260904\OpenNR_Captures` passed the
existing validator: 33 sequences, 919 complete frames, 29,432 artifacts,
no missing files, duplicate IDs, duplicate hashes, or zero-valued data. It is
valuable provenance and spatial pretraining material, but its crop/guide
geometry follows the old reader and should not be merged into the new aligned
guide experiment without re-indexing from full-frame masters.

The existing validator also reports 75 all-zero raw motion artifacts in that
older full-resolution pilot, mostly repeated static crop locations. They are
not used to reject the newer source because the newer audit tests its own
full-frame guides separately; they are another reason to keep the older run
supplemental until guide-validity masks are applied.

## Validation report

### Overall assessment: Share with caveats

The new source is suitable for a first full-resolution aligned spatial training
run after applying the saved exclusions. It is not ready to support claims about
temporal stability, reset handling, stereo comfort, live Feature 18 equivalence,
or real-time VR performance.

### Methodology review

The unit of analysis is a committed stereo render record, with per-eye full
color, teacher, depth, and motion artifacts. The target is Feature 18 teacher
RGB. Train/validation/test membership is sequence/process based. Guide inputs
are sampled at their native resolution using the color frame's pixel-center
geometry. Motion is bounded only for the exploratory student input; raw capture
bytes remain preserved.

### Issues found

1. **High — temporal coverage is insufficient.** Most records are 20–25 host
   frames apart, no resets are present, and only five adjacent stored pairs are
   consecutive. A temporal model would learn from false adjacency or missing
   history. Collect a separate contiguous clip set.
2. **High — guide scale and geometry can be misused.** The native guides are
   lower resolution and motion has finite outliers. Directly pairing old crop
   files or applying raw scales can create invalid features. Use the new aligned
   loader, per-eye X/Y scales, masks, and bounded representation.
3. **Medium — crash/timeout records exist.** Three frames have explicit GPU
   query failures and the final sequence has an uncommitted file tail. They are
   excluded and preserved for forensic reference.
4. **Medium — scene-disjoint generalization is unverified.** Contact sheets show
   useful indoor/outdoor, NPC, face, clothing, and low-light variation, but
   repeated locations and characters appear across sequences. The split is a
   process holdout, not a location holdout.
5. **Medium — queue pressure was measurable.** Backpressure reached 31 events,
   with zero dropped frames. This supports capture integrity but warrants a
   lighter capture configuration for the next temporal pass.

### Calculation spot-checks

- `504 complete = 507 records - 3 failed`: verified from every `frames.jsonl`.
- `491 retained spatial frames = 504 complete - 13 guard frames`: verified by
  `prepared_summary.json`.
- `982 eye pairs = 491 frames × 2 eyes`: verified by the manifest.
- `3,928 patches = 982 eye pairs × 4 fixed locations`: verified by the manifest.
- All valid frames use the expected route, model resolution, pass count, and
  color/guide dimensions: verified from per-frame metadata.
- Representative existing-validator check: 20 master frames, 800 artifacts,
  zero structural errors: verified for sequence 1.
- Loader geometry, masks, finite tensors, and CUDA gradient: verified by the
  saved smoke-test result.

### Visualization review

The generated contact sheets in `out/fullres_audit_20260904/previews` show
paired left/right input and teacher images across interiors, daylight streets,
NPC close-ups, faces, clothing, darker scenes, and dusk. They show visible
teacher changes and correct stereo differences. They do not establish headset
delivery or perceptual quality in motion.

## Next steps

1. Run a single-pass spatial baseline from the new manifest: RGB identity,
   RGB-only student, RGB+depth, and RGB+depth+motion with the same split and
   masks. Select checkpoints on validation only; evaluate test once.
2. Use 128×128 or 256×256 internal compute with a full-resolution RGB skip as a
   speed experiment, but measure warm stereo inference including upload,
   reconstruction, and compositing. The earlier full-frame POC was about 244 ms
   sequential stereo, far above the roughly 11.1 ms 90-Hz frame budget.
3. Collect a separate temporal set with contiguous 8/100-frame bursts, explicit
   reset and scene-transition markers, calibrated motion direction/scale under
   head rotation and strafing, and queue/backpressure logs. Keep menus/loading
   transitions in separate sequences.
4. Add scene/location/weather labels or deliberately held-out locations before
   making a generalization claim. Preserve this process holdout as the first
   frozen benchmark.
5. Keep the raw failed and orphan material quarantined by manifest. Do not delete
   it until crash forensics are complete, and do not use it as a training target.
