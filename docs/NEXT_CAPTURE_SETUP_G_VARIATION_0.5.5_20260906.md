# Next varied/high-effect OpenNR capture setup — 0.5.5 — 2026-09-06

> Active destination update: on 2026-09-07 the future capture root was moved
> from the empty G: staging root to the fast C: NVMe root shown below. The G:
> root remains empty historical setup state and is reserved for cold storage.

## Status

The active local OpenNR capture profile is prepared for the next deliberately
varied environment pass. SkyrimVR and MO2 were closed during the change. The
The initial 2026-09-06 setup temporarily pointed the capture writer at:

`G:\OpenNR_Captures_VariedHighEffect_0.5.5_20260906`

G: was measured at approximately 395.67 GiB free when this setup was made.
The output root was created but contains no capture sequences at setup time.

The live file is:

`E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json`

Before editing, it was copied and SHA-256 verified at:

`G:\OpenNR_Capture_Setup_Backups\pre-varied-high-effect-0.5.5-20260906-235556\SettingsUser.json`

Source and backup hash before the edit:

`FA2C0692E721CF6A730BD6EE858ED7CAECE8BBA726831BEA3955E9621FE5394B`

At the initial G: setup, only two live capture values changed from the backed-up
profile:

- `output_directory`: `C:\OpenNR_Captures_NextGridPilot_0.5.5_20260906` ->
  `G:\OpenNR_Captures_VariedHighEffect_0.5.5_20260906`
- `queue_capacity`: `32` -> `64`

The active Open Shaders DLL remains the known 0.5.5 OpenNR build. No teacher
settings, renderer resources, runtime route, or MO2 profile was changed.

## Active destination update — 2026-09-07

The active future destination is now:

`C:\OpenNR_Captures_VariedHighEffect_0.5.5_20260907`

C: had approximately 202.14 GiB free when the relocation was made. The new
root was created empty and is the only destination that should be used for the
next capture. Before this second edit, the live settings file was backed up and
hash-verified at:

`G:\OpenNR_Capture_Setup_Backups\pre-capture-relocate-to-c-0.5.5-20260907-000337\SettingsUser.json`

The backup SHA-256 is
`BE75B25CC9BC5ACF72438F51D8BBEC5257D3093001090375A4D624CAF972BFE7`.
The only value changed in this relocation was `output_directory`; the queue
remains `64`.

## Capture contract retained

The live block is equivalent to
[`opennr_capture_varied_high_effect_c.example.json`](../config/opennr_capture_varied_high_effect_c.example.json):

- both eyes;
- pre-NR input, post-NR teacher output, raw teacher readback, native depth,
  and native motion vectors;
- `route=feature18` and the capture build's exact native Feature 18 guide
  binding;
- four 512x512 crop positions: center, left, right, and lower-center;
- 64-frame finite bursts at the configured 90-FPS cadence;
- queue policy `defer_until_capacity`, with capacity 64;
- previews and periodic/full-frame artifacts disabled to keep the capture
  footprint manageable;
- the existing keys: `[` toggle, `]` single, `\` burst.

The capture implementation requests a Feature 18 history reset when each new
sequence starts. The first metadata record must therefore report
`history_reset: [true, true]`; later records must not reset mid-sequence.

## What the current capture can and cannot provide

The current capture is sufficient for the next data pass, but it does not yet
dump the additional renderer-derived channels proposed in the training report.
The source audit found that `OpenNRCaptureFeature` currently exposes only color,
teacher color, depth, native motion vectors, crop metadata, and scalar teacher
controls. The neural renderer currently supplies the runtime with the four
resources `DLSSNR.Color`, `DLSSNR.Depth`, `DLSSNR.MVec`, and `DLSSNR.Output`,
plus reset and tuning parameters.

| Desired information | Current status | Safe interpretation |
|---|---|---|
| Albedo/base color | Not captured or passed to Feature 18 | Feasible only after locating or adding a stable renderer pass; it must be recorded in the same eye/source coordinate space. |
| Normals | Not captured or passed to Feature 18 | Feasible if a native per-eye normal/G-buffer resource can be identified; a guessed screen-space normal is not equivalent. |
| Illumination | Not a single exposed resource | A defined linear-light or lighting intermediate could be added, but its exact stage must be specified before it becomes a target/conditioning. |
| Masks | Only `use_auto_mask` is recorded as a scalar teacher setting | This is not the teacher's internal mask texture. Engine-derived masks are useful only if their provenance and alignment are explicit. |
| Material/object semantics | No semantic buffer is exposed | Would require an opt-in engine/material-ID pass or stable object/material annotations; do not infer labels from RGB. |
| Exact carried teacher history | Not available through the current API | The reset flag is captured, but the internal history state of `nvngx_dlssnr.dll` is opaque. A recurrent proxy can be learned, but it must not be labeled as the exact teacher history. |

The highest-value implementation follow-up is an isolated auxiliary renderer
diagnostic path: first prove whether native albedo/normals/lighting resources
exist at the Feature 18 call boundary, then add opt-in copies and hashes without
changing the four-resource teacher route. Exact teacher history remains blocked
unless the runtime exposes it or an approved instrumentation boundary is found.

## What to collect

Use the active MO2 profile and launch through the configured `Launch MGO - Do
Not Unlock` bridge. After the scene is stable, press `\` once. Let the finite
burst finish and allow the writer to drain before changing scenes. Do not press
the toggle key around a burst, and do not collect through visible queue
saturation, severe stutter, or a damaged/partial sequence.

Aim for 12-20 independent sequences, with no more than two bursts from one
camera/environment combination. Record a short note for each sequence ID after
the burst so validation can be split by environment rather than by frame:

1. bright exterior with foliage, grass, rock, or fine geometry;
2. dark interior with torch/fire or strong local light;
3. snow, water, wet/specular, or reflective material;
4. NPC face, hair, cloth, skin, or weapon close-up;
5. shadow boundary or strong sun-to-shadow transition;
6. smoke, fog, particles, emissive signs, or other high-frequency effects;
7. slow lateral strafe;
8. fast lateral motion;
9. slow rotation/pan;
10. fast rotation or mixed translation plus rotation;
11. near geometry/parallax and disocclusion;
12. one deliberately high-effect scene where the teacher visibly changes tone,
    shadow, contrast, or material detail relative to the pre-NR input.

The purpose is not to make a large random grid. It is to make an environment-
level holdout possible and to put more of the teacher's high-effect behavior in
the training distribution. The later validator must quarantine all-zero or
invalid motion rows from recurrent loss while retaining their provenance.

## Acceptance gates after collection

Before any new cache or training run, validate each finished `frames.jsonl` and
report, per sequence:

- complete 64-frame length and contiguous frame/sample/host IDs;
- both eyes and all four crop indices for every required stage;
- `route=feature18` and
  `motion_vector_contract=exact_feature18_bound_resource`;
- first-frame `[true, true]` reset and no mid-sequence reset;
- zero failed/partial frames, dropped frames, and unexplained backpressure;
- native depth and motion validity, with anomalous sequences preserved and
  excluded from temporal loss rather than silently discarded;
- environment-level train/validation/test assignment after the notes are
  attached.

Do not start training from this root until that audit is complete. The current
known-good v65 model remains the offline baseline; this capture is data
collection only and does not change the live runtime model.
