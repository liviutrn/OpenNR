# Sparse full-eye anchor capture profile — 2026-09-09

## Status

This is the current press-`\\` collection profile. It supersedes the
full-eye-every-frame state-probe setup from earlier on 2026-09-09. That earlier
profile was operationally too heavy and its output is quarantined as diagnostic
material rather than accepted temporal-training data.

The live profile was changed only after Skyrim VR, SteamVR, and the relevant
capture processes were confirmed absent. The 18-sequence crop-temporal cache,
all existing raw capture roots, and every checkpoint remain untouched controls.

Live settings file:

`E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json`

Fresh output root:

`C:\OpenNR_Captures_TemporalCrops_SparseFullEye_20260909`

Backup and rollback record:

`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-sparse-full-eye-anchor-20260909-221903`

The pre-edit live settings and the backup are byte-identical with SHA-256
`ECE329C43261C16DD640C80FEB639408AE3BF3F727EA91535E55E9E0661DA444`.
The corrected live settings validate with `valid: true`, no errors, and no
warnings. The corrected live SHA-256 is
`FDBB44A7F3EE2B5C795697407CFFD812121CFF2CDC0B0C2067280D5C39768314`.

The planned 8-sequence tranche has now been collected. The crop-temporal audit
passes all 8 sequences: 512/512 complete frames, contiguous frame/sample/host
IDs, initial `[true,true]` resets, zero drops, and zero backpressure events. The
exhaustive byte audit reports 10,304 artifacts with no missing files, duplicate
IDs, duplicate hashes, or hard errors. It confirms 8 periodic full-eye anchor
frames with no missing anchor artifacts. The only warnings are 157 all-zero
auxiliary `gbuffer_specular` crop tensors, concentrated in sequences 7 and 8;
they remain retained and are not silently relabeled or deleted.

The authoritative reports are:

- `C:\OpenNR\Training\sparse_full_eye_anchor_temporal_audit_20260909.json`
- `C:\OpenNR\Training\sparse_full_eye_anchor_byte_audit_20260909.json`

## Effective settings

| Setting | Value | Purpose |
| --- | --- | --- |
| `enable_capture` | `true` | Capture is armed on launch |
| `burst_capture_key` | `220` (`\\`) | One bounded sequence per backslash press |
| `capture_rate_fps` | `80.0` | Eligibility cadence used for the temporal burst |
| `burst_frames` / `max_samples` | `64` / `64` | Exact bounded sequence length |
| `capture_left_eye` / `capture_right_eye` | `true` / `true` | Stereo data |
| `capture_full_frame` | `true` | Enables sparse full-eye validation anchors |
| `capture_full_frame_sequence` | `false` | Prevents full-eye output on every sample |
| `full_frame_every_samples` | `64` | One full-eye anchor at sample 64 |
| `capture_pre_nr` / `capture_post_nr` | `true` / `true` | Input and resolved comparison paths |
| `capture_raw_teacher` | `true` | Native Feature 18 teacher target |
| `capture_depth` | `true` | Native depth guide |
| `capture_motion_vectors` | `true` | Native Feature-18-bound motion guide |
| `capture_renderer_conditionings` | `true` | Renderer-owned conditioning crops |
| `crop_count` / `crop_size` | `1` / `512` | One center training crop per stage and eye |
| `crops[0]` | `(0.5, 0.5)` | Deterministic center crop |
| `queue_capacity` | `32` | Readback/writer headroom |
| `write_color_previews` | `false` | Avoids redundant preview I/O |
| `single_capture_key` / `toggle_capture_key` | `221` / `219` | Preserved; do not use for this tranche |

The live foveated-render settings remain unchanged: Full Eye preset, crop
width/height `1.0`, model resolution `100`, `neuralRenderingMultiPass=0`,
`neuralRenderingPreUpscale=0`, and no cropped-VR region override.

## Why this profile is usable

The renderer submits the normal 512² crop artifacts on every accepted sample.
On sample 64 it additionally submits the complete per-eye validation resources
for the standard input/source, depth, motion-vector, and teacher stages. The
renderer-conditioning stages remain crop-only by design.

Therefore a 64-frame burst contains:

- 64 contiguous temporal samples with native guides, raw teacher, pre-NR and
  post-NR color, and renderer-conditioning crops;
- both eyes on every sample;
- one full-eye validation anchor at the final sample, rather than 64 full-eye
  records;
- the exact sequence/reset/route/resolution/pass metadata needed for audit.

The prior every-frame full-eye run reached about 200–230 MB per frame and was
not a viable timing profile. This profile reduces the full-eye component from
64 anchors to one anchor per sequence. The canary tranche measured
approximately 1.38 GiB per 64-frame sequence, or 11.03 GiB for all 8
sequences. This is the observed rate for this scene mix, not a guarantee for
future scenes.

This is carried-state temporal evidence with reset metadata. It is not by
itself a formal teacher-state-distillation pair. A formal pair still requires a
separately replayed reset member and warm member with byte-identical current
RGB, native guides, renderer conditionings, route, pass and settings, plus a
measurable teacher response.

## Collection instructions

1. Start the normal MGO launcher: `Launch MGO - Do Not Unlock`.
2. Enter one selected scene and let the camera, teacher and overlay settle.
3. Press the keyboard backslash key `\\` once.
4. Keep the view and settings unchanged until the 64-frame burst is complete
   and the writer has drained.
5. Move to the next preselected scene or motion stratum.
6. Repeat for the planned sequence count, starting with one canary sequence.

During a burst, do not open the Open Shaders menu, change the teacher preset,
change resolution, toggle foveation, or move to a new view. If an accidental
menu open or setting change occurs, preserve the sequence and record it for
audit; do not silently count it as clean.

The exact temporal acceptance contract is: sequence length 64, contiguous
frame IDs, initial `history_reset=[true,true]`, no mid-sequence reset, usable
native guides, no dropped frames or partial records, and stable route/pass/
resolution/settings metadata. A slow or visibly stalled burst is rejected for
temporal/timing training even if its files are structurally complete.

## Storage guard

The output root is on `C:`. The old full-eye-every-frame mode reached 13.58 GiB
for one 64-frame sequence. The sparse profile produced 11.03 GiB for eight
64-frame sequences, approximately 1.38 GiB per sequence.

At the time of reconfiguration, `C:` had approximately 226.67 GiB free. Keep
at least 100 GiB free. Recheck free space before each subsequent sequence and
stop the tranche if the canary is unexpectedly large or introduces backpressure.
Do not delete or move the old cache, controls, checkpoints, or raw roots merely
to make room. Any future cleanup requires classification and verified-copy
checks first.

## Post-capture gates

Do not train directly from the raw root. The strict temporal audit must use
crop mode because the periodic profile intentionally does not contain full-eye
resources on every frame. Master mode is expected to reject these sequences;
that is a validator-contract mismatch, not a reason to discard the crop data.

```powershell
python D:\.CODEX_Projects\OpenNR-VR\tools\validate_temporal_capture.py `
  C:\OpenNR_Captures_TemporalCrops_SparseFullEye_20260909 `
  --mode crop `
  --expected-pass-count 1 `
  --output C:\OpenNR\Training\sparse_full_eye_anchor_temporal_audit_20260909.json
```

The exhaustive byte audit is
`C:\OpenNR\Training\sparse_full_eye_anchor_byte_audit_20260909.json`; its
`full_frame_frames=8` and `missing_master_full_frame_artifacts=0` fields are
the periodic-anchor check. Then run decoded content checks, native guide
checks, renderer-conditioning audit, and stereo alignment review. Keep
the new raw root, aligned cache, and split manifest separate from the immutable
18-sequence cache. Assign train/validation/test by sequence before training and
keep the test split unread during tuning.

## Non-changes

- No checkpoint was overwritten, merged, or promoted.
- The 18-sequence crop-temporal cache remains immutable.
- The rejected root `C:\OpenNR_Captures_FullEyeStateProbe_EveryFrame_20260909`
  was not deleted.
- No existing capture root was reused.
- No Runpod credit was spent.
- No Skyrim VR, SteamVR, native Feature 18 resource, or public build was
  changed.
