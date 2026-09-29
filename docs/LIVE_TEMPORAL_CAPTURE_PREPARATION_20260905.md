# Live temporal capture preparation — 2026-09-05

The updated local installation is prepared for the next isolated native SkyrimVR
temporal capture pass.

Active MO2 root:

```text
E:\MGO-RC3-fresh
```

Active profile:

```text
MGO NSFW - 4.0 BETA
```

Enabled mod:

```text
Open Shaders DLSSNR VR 0.5.3 OpenNR
```

The deployed `CommunityShaders.dll` SHA-256 is:

```text
7FAC8BC641EC7BA04FCC308238DD892BA9ABA34D6AE5F454A5646C432CCAFF0A
```

The live `SettingsUser.json` was backed up before editing at:

```text
E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-temporal-capture-20260905-142238
```

That initial preparation requested a full-resolution master on every sample.
The first live stress run proved that mode is structurally complete but cannot
maintain contiguous host-frame cadence: it reached 87 backpressure events and
produced 24.8 GiB for 120 records. It is preserved as a diagnostic/master
source at `C:\OpenNR_Captures_Temporal_20260905\seq-1788638984693-1` and is
not a temporal-training clip.

The live profile was subsequently backed up and changed to a separate
crop-temporal preparation at:

```text
E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-temporal-crop-20260905-162353
```

Only the `OpenNR Capture` block was changed for the current crop-temporal
smoke. The current values are:

- capture feature enabled on launch so its hotkeys are active, while recording remains idle until a hotkey is pressed;
- both eyes and one 512x512 crop per frame;
- pre-NR, post-NR, raw teacher, depth, and motion-vector resources enabled;
- color PNG previews enabled in the currently deployed binary; the next capture
  build adds a raw-only crop option to remove this writer bottleneck while
  retaining the exact typed tensors;
- 90 FPS sampling request;
- 64-frame burst and 64 maximum samples;
- queue capacity 32;
- full-frame artifacts disabled for this temporal clip so the writer is not forced to read back approximately 195 MiB per sample;
- output directory `C:\OpenNR_Captures_Temporal_Crops_20260905`.

The current live preparation manifest is [out/live_capture_crop_preparation_20260905/manifest.json](../out/live_capture_crop_preparation_20260905/manifest.json). The superseded full-resolution preparation remains recorded in [out/live_capture_preparation_20260905/manifest.json](../out/live_capture_preparation_20260905/manifest.json).

The output directory is intentionally outside the MO2 root and was not created in
advance. The next live step is to launch only the isolated MGO profile, confirm a
healthy world and Feature 18 path, then start recording with the configured toggle
or burst hotkey. The feature is enabled but recording is idle at launch; it does
not write frames until a capture action is requested. The current hotkeys are:

```text
[  toggle capture
]  single capture
\  burst capture
```

For the temporal pass, use the toggle to start a clean sequence after the initial
history reset, hold a stable scene or controlled camera motion for 32–64 frames,
then stop capture before changing scenes. If the game crashes, keep the incomplete
tail quarantined and do not repair it by inference.

The crop-temporal gate is explicitly separate from the master gate:

```powershell
python tools\validate_temporal_capture.py `
  C:\OpenNR_Captures_Temporal_Crops_20260905 `
  --mode crop `
  --output out\temporal_audit_crop_20260905.json
```

It still requires consecutive `frame_id`, `sample_index`, and `host_frame`,
the initial `[true, true]` history reset, stable Feature 18 settings, no drops,
and complete input/teacher/depth/motion crop resources for both eyes. It does
not claim full-frame coverage; full-resolution masters remain a separate
validation role.

After the game exits, validate the output in this order:

```powershell
python tools\validate_capture.py C:\OpenNR_Captures_Temporal_20260905

python tools\validate_temporal_capture.py `
  C:\OpenNR_Captures_Temporal_20260905 `
  --output out\temporal_audit_20260905.json
```

No production MGO files were changed by this preparation. The prior capture
settings remain restorable from the backup directory.
