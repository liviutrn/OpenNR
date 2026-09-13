# Next capture step: four-crop temporal grid pilot

Date: 2026-09-06  
Purpose: expand spatial coverage while preserving the native Feature 18 temporal contract.

Execution record: this pilot was collected successfully at
`C:\OpenNR_Captures_NextGridPilot_0.5.5_20260906`. The resulting 105-sequence
audit, 92-sequence clean temporal cache, four-crop spatial cache, and training
outcome are recorded in
[NEXT_GRID_TRAINING_RESULT_0.5.5_20260906.md](D:/.CODEX_Projects/OpenNR-VR/docs/NEXT_GRID_TRAINING_RESULT_0.5.5_20260906.md).
The profile below is therefore historical preparation, not an instruction to
recollect the same pilot without a new coverage goal.

## Prepared profiles

Primary pilot:

```text
D:\.CODEX_Projects\OpenNR-VR\config\opennr_capture_next_temporal_grid_pilot.example.json
```

Output root:

```text
C:\OpenNR_Captures_NextGridPilot_0.5.5_20260906
```

Optional later full-resolution master pilot:

```text
D:\.CODEX_Projects\OpenNR-VR\config\opennr_capture_next_fullres_master_pilot.example.json
```

Output root:

```text
C:\OpenNR_Captures_NextFullResMasterPilot_0.5.5_20260906
```

Both files are examples with `enable_capture: false`. Neither file changes the live profile by itself.

## What to do now

Only run the temporal grid pilot first. Do not start the full-resolution master pilot yet. Begin with one burst as a writer/storage smoke test; collect the remaining five only if that first burst is healthy.

1. Confirm Skyrim VR and the MGO launcher are closed.
2. Back up the live `SettingsUser.json` before changing it.
3. In the same MGO profile used for the validated Feature 18 capture, merge only the `OpenNR Capture` object from the primary pilot file. Do not replace the complete settings file and do not rebuild or replace `CommunityShaders.dll`.
4. Set `enable_capture` to `true` in the isolated capture profile, or enable the capture checkbox in the Open Shaders overlay before recording.
5. Launch through the same MGO route used for the previous strict captures.
6. For each burst, move to a different scene or deliberately different camera condition, let the view settle, then press the configured burst key `\` exactly once. Do not press `[` or change the overlay while a burst is running.
7. Wait until the 64-frame burst finishes and its `frames.jsonl` stops growing before starting another burst.
8. Collect one initial burst using the dark-interior/torch-lit condition below. If it finishes cleanly with no queue saturation or game instability, collect five more bursts using the remaining conditions:

   - exterior foliage, grass, or fine geometry;
   - NPC face, hair, cloth, or weapon material;
   - fire, smoke, fog, particles, or emissive lighting;
   - snow, water, specular detail, or a bright/dark shadow boundary;
   - a controlled slow pan or strafe across fine detail and an occluding object.

   The initial smoke-test condition is a dark interior or torch-lit stone/wood scene. The six-burst list is therefore one smoke-test burst plus five additional bursts.

9. If the game stutters badly, the capture overlay reports queue saturation, or the game becomes unstable, stop after the current burst. Do not keep collecting through a damaged run.
10. After the pilot set is complete, restore the backed-up live settings and relaunch normally if you want to play.

## Expected pilot size

Each sequence should contain:

- 64 contiguous frames;
- both eyes;
- input, teacher, depth, and native motion-vector stages;
- four crop indices, 0 through 3;
- an initial `[true, true]` history reset;
- no mid-sequence reset;
- no dropped frames.

The four-crop burst is expected to be roughly four times the raw size of the existing one-crop burst, approximately 0.8–1.0 GiB per sequence depending on row pitch and metadata. Six bursts should therefore remain within a manageable pilot budget. Do not delete older data to make room for this pilot.

## Acceptance conditions

The pilot is useful only if the sequence-level validator confirms:

- `route == feature18_stereo`;
- `model_resolution_percent == 100`;
- `pass_count == 1`;
- `motion_vector_contract == exact_feature18_bound_resource`;
- `history_reset` is `[true, true]` on frame one and false afterward;
- frame ID, sample index, and host frame are contiguous;
- all four crop positions are present for every required stage and eye;
- raw artifacts are complete and dimensionally correct;
- no dropped frames or missing stage/eye pairs.

Backpressure is recorded as a warning by the current validator, but the preferred result for the pilot is zero backpressure events. If the pilot has backpressure or host-frame gaps, preserve the root and report it; do not silently promote it to temporal training data.

## What to send back

After collecting the first burst, send only the capture-root path, for example:

```text
C:\OpenNR_Captures_NextGridPilot_0.5.5_20260906
```

Do not build a cache, move files, or delete anything first. I will validate the manifests, raw artifacts, crop alignment, native MV metadata, effect distribution, storage cost, and representative A/B samples. If the first burst is healthy, I will tell you to continue with the remaining five conditions; otherwise I will adjust the profile before you spend more storage.

## Full-resolution pilot gate

The optional full-resolution profile is intentionally limited to eight frames and one frame per second. It is a spatial/reference pilot and should not be treated as a strict temporal clip unless it separately passes contiguous host-frame validation. We will run it only after the four-crop pilot demonstrates that the writer and storage budget are healthy.
