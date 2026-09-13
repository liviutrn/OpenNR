# Full-eye temporal/state tranche setup — 2026-09-10

Status: prepared and validated, but not yet live-accepted. The first burst is a
mandatory timing pilot; only sequences that pass the structural and temporal
gates may be followed by the larger collection.

## Active profile

- MO2 instance: `E:\MGO-RC3-fresh`
- active MO2 profile: `MGO NSFW - 4.0 BETA`
- Skyrim VR: `E:\Games\Steam\steamapps\common\SkyrimVR`
- live settings: `E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json`
- output root: `C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910`
- burst key: `\\` / `VK_OEM_5` / `220`

The fresh output root did not exist when the profile was prepared. The game and
SteamVR were not running during the edit.

## Applied capture contract

| Setting | Live value | Why |
|---|---:|---|
| `capture_full_frame` | `true` | Write native per-eye full-frame resources. |
| `capture_full_frame_sequence` | `true` | Write full-eye input/teacher/depth/motion on every accepted sample. |
| `full_frame_every_samples` | `0` | Avoids mixing periodic-anchor semantics into the master sequence. |
| `capture_rate_fps` | `80.0` | Keeps the cadence used by the accepted crop-temporal contract. |
| `burst_frames` / `max_samples` | `16` / `16` | Bounded continuous clip; prevents the 64-frame full-eye backlog that caused host gaps and backpressure. |
| `queue_capacity` | `32` | Enough headroom for the bounded clip without allowing a large native-resource backlog. |
| eyes | left and right | Stereo state and teacher correspondence. |
| `capture_pre_nr` / `capture_post_nr` | `true` / `true` | Input and resolved comparison paths. |
| `capture_raw_teacher` | `true` | Native Feature 18 teacher target. |
| `capture_depth` | `true` | Exact Feature-18-bound depth guide. |
| `capture_motion_vectors` | `true` | Exact Feature-18-bound motion guide; no optical flow substitution. |
| `capture_renderer_conditionings` | `true` | Retain the available renderer-owned conditioning stages on every sample. |
| `crop_size` / `crop_count` | `512` / `1` | Keep the aligned center training crop alongside the full-eye resources. |
| `write_color_previews` | `false` | Avoid redundant preview I/O; raw resources and metadata remain enabled. |

The profile validator reports `valid: true` with no warnings. The live profile
changed only these fields from the sparse-anchor profile: burst length,
full-frame sequence mode, periodic interval, sample limit, and output root.

## Why this is different from the rejected run

The rejected full-eye run used full native artifacts on every sample for 64
samples. It produced complete-looking files but failed the strict temporal gate
because sustained native readback/writer pressure caused host gaps and
backpressure. Increasing the queue alone would only defer the failure while
increasing memory pressure.

This profile keeps the information contract intact and reduces the maximum
continuous native payload instead: each press produces a short 16-frame,
reset-qualified full-eye clip. At the measured rejected-run size of roughly
13.4–13.6 GiB per 64-frame sequence, a 16-frame sequence is expected to be
approximately 3.3–3.5 GiB, but the actual size must be measured from the first
pilot. The 16-frame value is a deliberately conservative starting point, not a
claim that the writer has been proven under this new setting.

The renderer conditionings remain the implementation's available crop-sized
renderer stages. The capture does not claim to export a hidden teacher-history
tensor or full-resolution G-buffers. The teacher state is represented by the
native Feature 18 carried trajectory, exact reset metadata, full-eye input/
teacher/depth/motion resources, and per-frame renderer conditioning metadata.

## Collection procedure

1. Start Skyrim VR yourself through the normal MO2 route. Do not edit the Open
   Shaders menu after launch and do not open it while a burst is active.
2. Load the intended scene and let the view settle. Keep route, resolution,
   teacher settings, renderer pass, and feature configuration fixed for the
   tranche.
3. Press `\\` once. Do not press it again while the burst is writing. The
   runtime requests the Feature 18 history reset at sequence start; do not
   manually reset mid-clip.
4. Wait for the 16-frame sequence to finish writing before touching the scene.
   The first burst is the timing pilot. Keep it isolated until it passes both
   validators.
5. Audit the sequence. A sequence with a host gap, backpressure, dropped frame,
   missing artifact, mid-clip reset, changed settings, incomplete stereo pair,
   or missing native guide is rejected and preserved with its reason.
6. Only after the pilot passes, repeat one backslash burst per scene/motion
   stratum. Do not start the next burst until the prior sequence has been
   audited and the writer has settled.

Do not use the toggle key or single-capture key for this tranche. Do not open
Open Shaders, change the camera, change weather, pause, load a menu, or change
the renderer while a burst is active. Such activity can be recorded as a
separate exploratory sequence but must not be mixed into the accepted tranche.

## Large-tranche design

The initial target is 32–48 accepted 16-frame clips across at least eight
sequence-disjoint strata, with four to six clips per stratum:

1. interior face/skin and timber;
2. exterior stone/terrain in daylight;
3. foliage/grass with visible motion;
4. deep shadow, hair, or fur;
5. strong highlights/specular materials;
6. occlusion/disocclusion and deliberate camera motion;
7. weather or volumetric-light variation;
8. a held scene with subtle teacher-history evolution.

Use new camera paths and scene states rather than replaying the 18-sequence
crop cache. Keep a sequence manifest with scene stratum, route, reset result,
validator result, and any visual-quality notes. The first accepted tranche
should be sequence-disjoint between train, validation, and frozen test splits.

At the observed size, 32–48 clips are expected to occupy roughly 105–170 GiB.
Stop collection if the output root exceeds 250 GiB before triage, if free C:
space falls below 500 GiB, or if two consecutive pilot clips show backpressure.
The goal is clean information, not a large rejected archive.

## Acceptance commands

From `D:\.CODEX_Projects\OpenNR-VR`:

```powershell
python tools/validate_capture.py C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910
python tools/validate_temporal_capture.py C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910 `
  --mode master --expected-pass-count 1 `
  --output out\full_eye_temporal_state_tranche_audit_20260910.json
```

The temporal gate must report, for every accepted sequence:

- exactly 16 complete frame records;
- initial `history_reset=[true,true]` and no later reset;
- contiguous `frame_id`, `sample_index`, and `host_frame`;
- zero backpressure and zero dropped-frame records;
- both eyes on every frame;
- complete full-frame input, teacher, depth, and motion resources for both
  eyes;
- stable route, resolution, guide dimensions, Feature 18 settings, teacher
  controls, and renderer-conditioning availability;
- no missing, duplicate, zero-image, or duplicate-hash artifacts.

Passing this gate makes the clip structurally eligible. It does not by itself
prove teacher resemblance, color match, temporal image quality, or student
promotion; those remain separate visual and model-evaluation gates.

## Backup and rollback

The pre-edit profile is preserved at:

`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-full-eye-state-tranche-20260910\SettingsUser.before.json`

- pre-edit SHA-256: `FDBB44A7F3EE2B5C795697407CFFD812121CFF2CDC0B0C2067280D5C39768314`
- applied SHA-256: `3CBA0117B4F2A136010E8519460B349E0ECCB586243DBE99CBD03FE98A567EFE`

To roll back, close Skyrim VR and SteamVR first, then copy the backup over the
live settings file and verify the pre-edit hash. Do not roll back while the
game or VR runtime is running.

