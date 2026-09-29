# 0.5.5 crop-temporal capture preparation — 2026-09-06

The current full-frame sequence is being preserved as diagnostic/full-resolution evidence, but it is not a strict temporal clip because its first record lacks the required `[true, true]` history reset and the full-frame path is emitting required PNG masters at several seconds per frame.

Current diagnostic sequence:

```text
E:\OpenNR_Captures_Temporal_MasterRaw_0.5.5_20260905\seq-1788664426311-1
```

The standalone crop-temporal profile is prepared here:

```text
D:\.CODEX_Projects\OpenNR-VR\out\live_capture_temporal_crop_preparation_0.5.5_20260906\SettingsUser.OpenNR-CropTemporal.0.5.5.json
```

It has been validated with `tools/validate_capture_config.py`. The live `SettingsUser.json` and installed `CommunityShaders.dll` were not modified while Skyrim was running.

The crop profile keeps both eyes, pre-NR input, teacher output, native Feature 18 depth, and native Feature 18 motion vectors. It disables full-frame masters, keeps raw artifacts, uses one 512x512 crop, requests every eligible frame, and bounds each burst at 64 records. Its output root is:

```text
E:\OpenNR_Captures_Temporal_Crops_0.5.5_20260906
```

After Skyrim exits and the current full-frame writer has stopped, back up the live settings, merge the `OpenNR Capture` block from the standalone profile into the live settings, and relaunch through the same MGO profile. Do not copy or rebuild `CommunityShaders.dll`.

For each clip:

1. Stop any previous burst and wait until its `frames.jsonl` stops growing.
2. Close and reopen the Open Shaders overlay once without capture to force a clean Feature 18 history boundary.
3. Hold the camera still at the target scene.
4. Arm exactly one `\\` burst.
5. Close the overlay at the reset boundary and verify that the first record is `[true, true]`.
6. Keep the scene stable until 64 records commit and the queue drains.
7. Validate before moving to the next scene.

Use face/NPC, indoor low light, foliage/fine geometry, and a controlled camera turn. Run the strict temporal validator after the game exits. Full-frame masters remain useful for spatial/reference evidence, while crop clips are the practical source for contiguous temporal supervision.
