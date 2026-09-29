# Superseded full-eye-every-frame state-probe setup — 2026-09-09

## Status

This document records the rejected full-eye-every-frame profile. It is retained
for provenance and diagnosis only; it is not a usable timing or temporal-
training collection profile. The error was enabling full-eye output on every
sample, which made the capture writer and disk path dominate the run.

The current press-`\\` profile is documented in
[`SPARSE_FULL_EYE_ANCHOR_CAPTURE_20260909.md`](SPARSE_FULL_EYE_ANCHOR_CAPTURE_20260909.md).
That corrected profile keeps per-frame 512² crops and native guides, and adds
only one full-eye anchor at sample 64.

The rejected output root is retained and must not be mixed into an accepted
temporal cache:

`C:\OpenNR_Captures_FullEyeStateProbe_EveryFrame_20260909`

The 18-sequence crop-temporal cache, all other raw capture roots, and every
checkpoint remain untouched controls.

## Historical setup state

Active settings file:

`E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json`

Fresh empty output root:

`C:\OpenNR_Captures_FullEyeStateProbe_EveryFrame_20260909`

Pre-edit backup and rollback:

`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-full-eye-state-probe-20260909-215939`

The backup `SettingsUser.before.json` SHA-256 is
`6E770B9B9A193BD959B7BC404E4583DDD1472EDE7C9DD00C1034CE3F97193C6D`.
The supplied `Rollback.ps1` refuses to run while Skyrim VR or SteamVR is
running and verifies the backup hash before restoring it.

## Effective capture settings

| Setting | Value | Purpose |
| --- | --- | --- |
| `enable_capture` | `true` | Capture is armed on launch |
| `burst_capture_key` | `220` (`\\`) | One bounded sequence per backslash press |
| `burst_frames` / `max_samples` | `64` / `64` | Preserves the validated 64-frame temporal contract |
| `capture_rate_fps` | `80.0` | Keeps the proven lower-I/O full-eye rate |
| `capture_left_eye` / `capture_right_eye` | `true` / `true` | Stereo data on every frame |
| `capture_full_frame` | `true` | Writes native full-eye resources |
| `capture_full_frame_sequence` | `true` | Writes full-eye resources for every sample |
| `full_frame_every_samples` | `0` | Runtime policy: every sample in sequence mode |
| `capture_pre_nr` / `capture_post_nr` | `true` / `true` | Input and resolved comparison paths |
| `capture_raw_teacher` | `true` | Native Feature 18 teacher target |
| `capture_depth` | `true` | Native depth guide |
| `capture_motion_vectors` | `true` | Native Feature-18-bound motion guide |
| `capture_renderer_conditionings` | `true` | Six renderer-owned stages / 17 normalized channels |
| `crop_count` / `crop_size` | `1` / `512` | Center training crop retained with the master |
| `crops[0]` | `(0.5, 0.5)` | Deterministic center crop |
| `queue_capacity` | `32` | Readback headroom; drops remain a hard rejection |
| `write_color_previews` | `false` | Avoids redundant preview I/O |
| `single_capture_key` / `toggle_capture_key` | `221` / `219` | Preserved; do not use for this tranche |

The live foveated-render settings are already compatible with full-eye
capture: Full Eye preset selected, crop width/height `1.0`, model resolution
`100`, `neuralRenderingMultiPass=0`, `neuralRenderingPreUpscale=0`, and no
cropped-VR region override. The capture config validator reports `valid: true`
with no errors or warnings.

## What one backslash press produces

Each press of `\\` requests one new sequence in the fresh root. The runtime
should write:

- 64 contiguous frame records;
- both eyes for every frame;
- full native input, teacher, depth and motion resources;
- the retained center crop;
- pre-NR and post-NR color;
- all available renderer conditionings;
- exact route, resolution, pass, guide-size, teacher-setting, runtime and
  reset metadata.

The required temporal metadata is an initial `history_reset` pair of
`[true,true]`, followed by `[false,false]` on every later frame. A mid-clip
reset, host-frame gap, dropped frame, partial record, changed teacher setting,
or changed route makes that sequence non-promotable. It must be preserved with
the rejection reason rather than repaired or deleted.

The native teacher's carried history is opaque at this capture boundary. This
profile therefore captures a valid carried-state trajectory and its reset
metadata, but it does not export a hidden teacher tensor. A formal state-pair
experiment still requires a separately validated warm member with
`[false,false]` and byte-identical current RGB, native guides, renderer
conditioning, route, pass and settings. Do not describe an ordinary second
burst as such a pair.

## Collection target

The first bounded target is **8 accepted sequences across at least 6 distinct
scene/motion strata**. Use scenes and camera paths that are not represented by
the 18-sequence crop-temporal cache wherever possible. A 12-sequence stretch
target is allowed only if the storage guard remains satisfied.

Suggested strata:

1. interior face/skin and timber;
2. exterior stone/terrain with strong daylight;
3. foliage or grass with motion;
4. deep shadow, hair or fur;
5. strong highlights/specular material;
6. deliberate camera/object motion with occlusion or disocclusion.

Use one backslash burst per selected scene/camera state. Let the writer drain
fully before moving to another scene or beginning the next sequence. Do not
open the Open Shaders menu, change the teacher preset, change resolution,
toggle foveation, or move to a new view during a burst. If an accidental menu
open or setting change occurs, leave the sequence on disk and record it for
audit; do not silently count it as clean.

## Storage guard

The last comparable full-eye capture used approximately 13.5 GiB per 64-frame
sequence. The new root is intentionally separate and empty. Approximate raw
growth is therefore:

| Accepted sequences | Estimated raw growth | Expected interpretation |
| ---: | ---: | --- |
| 8 | ~108 GiB | Safe first tranche |
| 12 | ~162 GiB | Stretch target; recheck free space first |
| 16 | ~216 GiB | Do not attempt on the current C: headroom |

Current free space at setup was approximately 240.77 GiB on C:, 37.64 GiB on
D:, and 31.02 GiB on E:. Stop the tranche before starting a new sequence if C:
falls below approximately 100 GiB free. Do not delete older data to make room
without a fresh classification and verified alternate copy; the current
headroom is sufficient for the bounded 8-sequence target.

## User capture procedure

1. Start the normal MGO launcher: `Launch MGO - Do Not Unlock`.
2. Enter a selected scene and let the view, teacher and overlay settle.
3. Press the keyboard backslash key `\\` once.
4. Keep the view stable until the 64-frame burst and disk writer finish.
5. Move to the next preselected scene or motion stratum.
6. Repeat until the 8-sequence target is reached.
7. Do not start training or move/delete any capture data after collection; the
   raw root must be audited first.

## Post-capture gates

Run the strict full-frame audit before decoding or training:

```powershell
python D:\.CODEX_Projects\OpenNR-VR\tools\validate_temporal_capture.py `
  C:\OpenNR_Captures_FullEyeStateProbe_EveryFrame_20260909 `
  --mode master `
  --expected-pass-count 1 `
  --output C:\OpenNR\Training\full_eye_state_probe_temporal_audit_20260909.json
```

Then run the exhaustive artifact validator and renderer-content/conditioning
audits. Only accepted sequences may enter a new aligned cache. Keep the new
cache, raw root and split manifest separate from the immutable 18-sequence
cache. Register sequence-level train/validation/test assignment before any
training and leave the test split unread for tuning.

For the teacher-state question, build a separate pair manifest only after an
exact reset/warm replay produces at least eight clean pairs. The formal pair
audit must report byte-identical current RGB, native guides and renderer
conditioning, matching metadata, reset `[true,true]` versus warm `[false,false]`,
and a measurable teacher response. Until then, use this tranche as carried-
state full-eye evidence, not as state-distillation supervision.

## Non-changes

- No training process was started.
- No checkpoint was overwritten, merged or promoted.
- The 18-sequence crop-temporal cache remains immutable and remains the control.
- Existing full-eye, renderer-state and crop roots were not reused or deleted.
- No Runpod credit was spent.
- No Skyrim VR, SteamVR, native Feature 18 resource or public build was changed.
