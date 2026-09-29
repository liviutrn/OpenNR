# Next capture preparation — installed Open Shaders 0.5.3

The next capture is pinned to the installed MO2 package, not to the older
source-tree Dev-Fast build.

Runtime authority:

- package: `Open Shaders DLSSNR VR 0.5.3 OpenNR`;
- installed DLL version: `0.5.3.0`;
- installed DLL SHA-256:
  `398E8B3F516659D5D8C7E59D4A3F6BF37F027D7A3A3CB05CD5496EE2B68ECD40`;
- rebuilt OpenNR archive SHA-256:
  `D073AE6421C415F6917FA761D91CF30686BD68224BBC9A18CEE6033B189A6642`.

The installed DLL contains the `write_color_previews` capture setting. No
`CommunityShaders.dll` was copied or rebuilt during this preparation. The live
settings file was backed up at:

```text
E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-next-capture-latest-0.5.3-20260905-172118\SettingsUser.json
```

Only four keys in the `OpenNR Capture` block changed from the prior live
profile: `burst_frames` and `max_samples` changed to 32,
`output_directory` moved to a fresh root, and `write_color_previews` was set to
`false`. The structural comparison confirmed every non-capture setting stayed
unchanged.

The prepared probe writes to:

```text
C:\OpenNR_Captures_Temporal_Crops_0.5.3_NoPreview_20260905
```

It captures both eyes, one centered 512×512 crop, pre-NR input, post-NR
teacher, native depth, and native motion vectors. Full-frame artifacts remain
disabled. PNG previews are disabled for sampled crops, but the typed raw
tensors remain enabled. This is intended to remove color PNG conversion and
write pressure while keeping the training payload.

The output root was empty when prepared. After launching the isolated MGO
profile and confirming the world is stable, press `\` once for the configured
32-frame burst. Keep the camera/scene stable and do not start another burst
until the first directory is finished. Then validate it with:

```powershell
python tools\validate_temporal_capture.py `
  C:\OpenNR_Captures_Temporal_Crops_0.5.3_NoPreview_20260905 `
  --mode crop `
  --allow-missing-initial-reset `
  --output out\temporal_audit_latest_0.5.3_20260905.json
```

The preparation evidence and exact hashes are in
[out/live_capture_latest_0.5.3_preparation_20260905/manifest.json](../out/live_capture_latest_0.5.3_preparation_20260905/manifest.json).
