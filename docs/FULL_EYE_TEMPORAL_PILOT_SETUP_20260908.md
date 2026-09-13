# Full-eye temporal pilot setup — 2026-09-08

The live OpenNR capture profile is now armed for a bounded, one-button pilot.
The change was made only after the Skyrim VR, SteamVR, MO2, OpenXR and
Community Shaders processes were absent. The Steam client and Oculus service
were left running because they do not load this profile. The selected MO2
profile is `MGO NSFW - 4.0 BETA`, and the live file is
`E:/MGO-RC3-fresh/overwrite/SKSE/Plugins/CommunityShaders/SettingsUser.json`.

## Capture contract

Press the configured burst key, `\` (`VK_OEM_5`, value `220`), once after the
scene is ready. The runtime will request a Feature 18 history reset, capture
240 accepted samples at an 80 Hz eligibility cadence, and stop the burst
automatically. At the nominal headset cadence this is about three seconds.
The accepted samples remain a contiguous sequence that can be split into the
existing 64-frame temporal windows. Sample 240 also carries one complete native
resolution artifact for both eyes because the periodic full-frame interval is
240 samples.

The live settings preserve the current training contract: both eyes, 512-pixel
center crop, pre-NR input, post-NR teacher, raw teacher readback, exact Feature
18 depth and motion vectors, and all six renderer conditioning resources. Color
PNG previews remain disabled; the required raw resources and JSONL metadata are
written. The new output root is
`C:/OpenNR_Captures_FullEyeTemporalPilot_20260908`, separate from the existing
renderer-state tranche.

The periodic master is deliberately one frame at the end of each short run.
Capturing eight full-resolution frames three seconds apart in one sequence
would require roughly 1,920 crop samples and about 36 GiB at the measured
renderer-state data rate. This pilot gets a synchronized temporal run and a
full-eye anchor while keeping each scene run reviewable and storage bounded;
additional scenes provide the sparse appearance variation.

## Exact settings

The disabled-by-default copy of the contract is
[`opennr_capture_full_eye_temporal_pilot_20260908.example.json`](../config/opennr_capture_full_eye_temporal_pilot_20260908.example.json).
The applied values are:

| Setting | Value |
|---|---:|
| `capture_rate_fps` | `80.0` |
| `burst_frames` / `max_samples` | `240` / `240` |
| `capture_full_frame` | `true` |
| `capture_full_frame_sequence` | `false` |
| `full_frame_every_samples` | `240` |
| `crop_size` / `crop_count` | `512` / `1` |
| `queue_capacity` | `16` |
| eyes | left and right |
| renderer conditionings | enabled |
| output | `C:/OpenNR_Captures_FullEyeTemporalPilot_20260908` |

The configuration validator reports `valid: true` with no warnings. A semantic
comparison against the pre-edit profile found only six intended changes:
capture rate `90.0` to `80.0`, burst and sample limits `64` to `240`, enabling
periodic full-frame artifacts, setting the interval to `240`, and changing the
output root.

## Backup and audit handoff

The pre-edit profile is preserved at
`E:/MGO-RC3-fresh/_OpenNR_Pilot_Backups/pre-full-eye-temporal-pilot-20260908/SettingsUser.before.json`.
Its SHA-256 is
`3b3b1517f296cfca486ce51251e91829366575a8ca1f5f3dc7e6bdc4db0f54a8`.
The applied profile SHA-256 is
`260c185ade91e832c408852e2ed87cb7047d46ddb7d3c74b2d78a21815cd19a9`.
`Rollback.ps1` in the same backup directory restores the exact pre-edit file
after the game and VR runtimes are closed.

After each run, preserve the sequence and audit it before training. Require
240 frame records, an initial `history_reset=[true,true]`, no later reset,
contiguous `host_frame`, complete left/right Feature 18 depth and motion
resources, renderer-conditionings availability, and a full-frame record at
sample 240. A queue stall or incomplete master is an exclusion to report, not
silently repair. Do not mix this root into the promoted cohorts until the
validator, stereo alignment check, and broad visual sheet pass.

## Superseding every-frame re-arm — 2026-09-09

The anchor-only profile described above has been replaced in the live profile
by a bounded every-frame contract. The live file is
`E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json`.
Only these capture fields changed from the anchor profile:

| Setting | Before | Live after re-arm |
| --- | ---: | ---: |
| `burst_frames` | 240 | 64 |
| `capture_full_frame_sequence` | false | true |
| `full_frame_every_samples` | 240 | 0 |
| `max_samples` | 240 | 64 |
| `output_directory` | `C:\OpenNR_Captures_FullEyeTemporalPilot_20260908` | `C:\OpenNR_Captures_FullEyeTemporalEveryFrame_20260909` |

All other OpenNR capture settings remain as previously validated: 80 Hz,
both eyes, one 512-pixel center crop, raw pre/post input and teacher, native
depth/motion and all six renderer conditionings. The edited live profile
validates with `valid: true`, no errors and no warnings. Its SHA-256 is
`ccde5515081396076715fba06ff66430456adf50a4995ef273ba77de76762dd0`.

Before editing, the exact prior profile was copied to
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-full-eye-every-frame-20260909\SettingsUser.before.json`
and matched SHA-256
`260c185ade91e832c408852e2ed87cb7047d46ddb7d3c74b2d78a21815cd19a9`.
`Rollback.ps1` in that directory restores and verifies the prior profile.
The new output root did not exist at re-arm time, so no capture bytes have
been written yet. The user must launch Skyrim/VR and trigger the burst once
the scene is ready; this task did not launch or control the game.

## Superseding capture audit and crop-temporal re-arm — 2026-09-09

The user-launched every-frame full-eye run completed two sequences under the
contract above:

| Sequence | Complete frames | Size | Strict temporal result |
| --- | ---: | ---: | --- |
| `seq-1788993098503-1` | 64/64 | 13.59 GiB | rejected: host gaps up to 188; backpressure 47; drops 0 |
| `seq-1788993615492-2` | 64/64 | 13.41 GiB | rejected: host gaps up to 179; backpressure 94; drops 0 |

Both sequences have the initial `[true, true]` reset, contiguous `frame_id`
and `sample_index`, complete full-frame input/teacher/depth/motion for both
eyes, and all six renderer-conditioning crop stages. The strict gate reports
`temporal_ready=false` solely because full-frame readback cannot maintain
contiguous `host_frame` cadence under sustained backpressure. After the
validator was corrected to keep crop-only G-buffers out of the full-frame
requirement, the exhaustive byte validator passes both sequences with zero
errors, missing files, duplicate IDs or duplicate hashes. It reports three
all-zero motion-vector crop tensors in sequence 1 and 67 in sequence 2 as
warnings; they are retained for decoded/static-scene review.

After Skyrim and SteamVR were closed, the live profile was re-armed for the
separate lower-I/O crop-temporal contract. Only the capture settings below
changed from the full-eye profile:

| Setting | Full-eye run | Current live value |
| --- | ---: | ---: |
| `capture_full_frame` | true | false |
| `capture_full_frame_sequence` | true | false |
| `queue_capacity` | 16 | 32 |
| `output_directory` | `C:\OpenNR_Captures_FullEyeTemporalEveryFrame_20260909` | `C:\OpenNR_Captures_TemporalCrops_EveryFrame_20260909` |

The live profile still requests both eyes, one 512-pixel center crop, 80 Hz,
raw pre/post input and teacher, native depth and motion, and all six renderer
conditioning crops, with `burst_frames=max_samples=64`. It validates with
`valid: true`, no errors and no warnings. Its SHA-256 is
`6e770b9b9a193bd959b7bc404e4583ddd1472ede7c9dd00c1034ce3f97193c6d`.
The byte-identical pre-edit backup is
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-crop-temporal-20260909\SettingsUser.before.json`,
with SHA-256
`ccde5515081396076715fba06ff66430456adf50a4995ef273ba77de76762dd0`;
`Rollback.ps1` in that directory restores and verifies the prior full-eye
profile. The disabled example is
`config/opennr_capture_temporal_crops_every_frame_20260909.example.json`.

Use the crop mode of `validate_temporal_capture.py` for the next burst. Keep
the Open Shaders menu closed while recording, do not trigger a second burst
until the first crop sequence has been audited, and keep the two completed
full-eye masters in a separate spatial/color cohort.

## Crop-temporal acceptance result — 2026-09-09

The armed crop contract subsequently produced two 64-frame sequences:
seq-1788995597432-1 and seq-1788995726335-2, each approximately 1.19 GiB.
Both passed validate_temporal_capture.py --mode crop --expected-pass-count 1.
Each has 64/64 complete records, initial [true, true], reset index [0], no
mid-reset, contiguous frame/sample/host IDs with host gaps exactly 1, zero
backpressure, and zero dropped frames. The exhaustive validator passed 2,560
artifacts with no missing files, duplicate IDs, duplicate hashes, or zero-image
warnings. The crop pair is structurally eligible for temporal cache creation;
visual temporal quality and teacher-match acceptance remain separate gates.
