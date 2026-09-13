# Full-resolution temporal capture preparation — 2026-09-05

The next capture is prepared as a small, reset-qualified full-frame master
sequence. The live settings were backed up before the change, and only the
`OpenNR Capture` block in the selected MO2 overwrite was edited.

Runtime authority for this preparation is the enabled profile entry
`Open Shaders DLSSNR VR 0.5.5 OpenNR`:

```text
DLL: E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.5 OpenNR\SKSE\Plugins\CommunityShaders.dll
Version: 0.5.5.0
Bytes: 43,744,768
SHA-256: ECC2B784F19037CD3AD97D265883440D21C92BACD8674D6F13E258ADD9149CAE
```

The DLL was not copied, rebuilt, or modified. The exact settings backup is:

```text
E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-fullres-temporal-0.5.5-20260905-230251\SettingsUser.json
```

The preparation manifest and the standalone capture block are in
`out/live_capture_fullres_temporal_preparation_20260905/`.

The new output root is:

```text
E:\OpenNR_Captures_Temporal_MasterRaw_0.5.5_20260905
```

The capture contract is:

- 64 samples per burst, with a maximum of 64 records in a sequence;
- full-frame pre-NR input and post-NR teacher for both eyes;
- full-frame native Feature 18 depth and native Feature 18 motion vectors for both eyes;
- raw color only (`write_color_previews=false`), so PNG conversion is removed from the writer path;
- `capture_rate_fps=0`, which requests every eligible render frame and avoids intentional wall-clock sampling gaps;
- queue capacity 64 as a bounded reservoir, not as a substitute for writer throughput;
- a 16×16 auxiliary crop, solely because the runtime requires at least one crop preset; the required payload is the full-frame set;
- the existing Feature 18 route, model resolution, teacher style, motion-vector scales, refresh, and reprojection settings are left untouched.

The raw-only crop pass demonstrated that the no-preview path can produce 3,475
complete frames with zero backpressure and zero drops. Its strict temporal gate
remained closed because every sequence started after history was warm. The
full-frame pass is a separate, more expensive test: one 2496×2688 RGBA tensor is
about 25.7 MiB per eye, and the depth/motion masters add roughly 23 MiB per eye.
Four 64-frame clips can therefore occupy tens of gigabytes. `E:` has the free
space for this run; the old `C:` captures remain untouched.

## Starting one reset-qualified clip

1. Launch only the selected `MGO NSFW - 4.0 BETA` profile through the normal MGO
   bridge. Wait for a stable world and verify that Feature 18 is active on its
   intended route.
2. Leave the camera still. Open the Open Shaders menu with `END` while the
   scene is stable.
3. While the overlay is open, request the finite burst. The preferred action is
   the feature's **Burst** button or pressing `\` once. If the overlay accepts
   the key, this starts recording and arms 64 samples while the scene is still
   paused. If you must use the feature's **Start** button first, keep the
   overlay open and press `\` (or **Burst**) before closing it; otherwise a
   zero-rate capture would begin an unbounded sequence as soon as the overlay
   closes.
4. Close the overlay once. The Open Shaders temporal integration resets Feature
   18 when the overlay closes. The first committed record after that transition
   must show `history_reset: [true, true]`.
5. Keep the camera and scene fixed until the 64-frame burst finishes.
   The game may become very slow; do not interpret the low live FPS as a model
   or runtime result.
6. Wait until the sequence has 64 committed lines and the queue has drained
   before changing the scene. The burst stops by itself. Do not begin the next
   clip while the previous sequence is still growing.

For the requested coverage, use four clips in this order: NPC/face close-up,
indoor low light, outdoor foliage or fine geometry, and a controlled camera turn.
For every new clip, force the same overlay-close reset before the first sample.
For the camera turn, start from a still view and rotate at a steady, deliberate
speed after the reset-qualified first frame.

Monitor the root from the project checkout while the game is running:

```powershell
python tools\monitor_temporal_capture.py E:\OpenNR_Captures_Temporal_MasterRaw_0.5.5_20260905 --watch --expected-frames 64
```

Stop the current clip and preserve it for inspection if any of these appears:

- `backpressure_events_before` becomes nonzero;
- `dropped_frames_before` becomes nonzero;
- a frame, sample, or host counter is not exactly one greater than its predecessor;
- a frame is partial or failed;
- memory pressure, a crash, or an unstable Feature 18 route occurs.

Do not repair a crash tail by renaming or inferring records. Keep that sequence
separate and validate only complete committed records.

## Validation after the game exits

Run both gates, in this order:

```powershell
python tools\validate_capture.py E:\OpenNR_Captures_Temporal_MasterRaw_0.5.5_20260905
python tools\validate_temporal_capture.py E:\OpenNR_Captures_Temporal_MasterRaw_0.5.5_20260905 `
  --output out\temporal_audit_fullres_temporal_0.5.5_20260905.json
```

The second command is intentionally strict. It requires the full-frame stage/eye
set, the initial `[true, true]` reset, no mid-clip reset, exact frame/sample/host
increments, no drop, and stable Feature 18 metadata. A structurally complete
full-frame clip that fails any one of those checks remains diagnostic data, not a
temporal-training clip.
