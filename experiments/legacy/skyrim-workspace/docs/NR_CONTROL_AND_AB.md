# DLSSNR controls and A/B captures

The Open Shaders fork already exposes the neural controls in its in-game
Upscaling panel. The default menu key is `End`. Under `DLSS Neural Rendering`
the fork provides Enable, Tuning Preset, Intensity, Local Tone, Local
Structure, Skin Structure, Style, Automatic Mask, and UI Correction. The
current source maps presets as follows:

| Code | Preset | Intensity | Local Tone | Local Structure | Skin Structure |
| ---: | --- | ---: | ---: | ---: | ---: |
| 0 | Custom | user value | user value | user value | user value |
| 1 | Balanced | 1.00 | 1.00 | 1.00 | 1.00 |
| 2 | Fabric Detail | 1.35 | 0.90 | 1.60 | 1.15 |
| 3 | Natural | 0.80 | 0.75 | 0.90 | 0.90 |
| 4 | Strong | 1.75 | 1.25 | 1.50 | 1.30 |

The controller also provides a project-defined `Cinematic` profile. It is
stored as Custom with intensity `1.25`, local tone `0.65`, local structure
`1.25`, skin structure `1.00`, and style `3`; it is not a native Open Shaders
preset. The native tuning range is clamped to `0.0–2.0`.

For deterministic changes outside the game, use
`scripts\Invoke-DLSSNRControl.ps1`. It edits only the active generated
`SettingsUser.json`, makes a timestamped backup first, validates the numeric
range (0–2), and forces the preset to `Custom` when an individual tuning value
is changed. Examples:

```powershell
powershell -File .\scripts\Invoke-DLSSNRControl.ps1 -Action Status
powershell -File .\scripts\Invoke-DLSSNRControl.ps1 -Action Apply -Preset Natural
powershell -File .\scripts\Invoke-DLSSNRControl.ps1 -Action Apply -Neural on -Intensity 1.10 -Style 3
powershell -File .\scripts\Invoke-DLSSNRControl.ps1 -Action Apply -Neural off
powershell -File .\scripts\Invoke-DLSSNRControl.ps1 -Action Apply -Preset Cinematic
powershell -File .\scripts\Invoke-DLSSNRControl.ps1 -Action Apply -Intensity 2.0
```

Close SkyrimVR before applying the JSON controller. While the game is running,
use the Open Shaders panel for live changes; `-AllowRunningGame` exists only
for an intentional experiment because the game may overwrite or ignore a live
file edit.

## Seeing ON/OFF and runtime status in-game

Press the physical `End` key while SkyrimVR is focused. In the Open Shaders
menu, open `Upscaling` / `Foveated DLSS` and look at `Enable DLSS Neural
Rendering`: checked is ON and unchecked is OFF. The checkbox is the configured
feature state; it is not by itself proof that a frame was successfully evaluated.

For the fork's diagnostic line, close SkyrimVR and enable Developer Mode before
the next launch:

```powershell
powershell -File .\scripts\Invoke-DLSSNRControl.ps1 -Action Apply -DeveloperMode on
```

After launching through the active MGO profile, press `End` again and return to
the same panel. Developer Mode exposes a line like `Status: initialized | NGX:
0x........ | Evaluations: N`. `initialized`/`ready` means the runtime is
available; an increasing `Evaluations` count is the useful proof that frames
are being processed. If the renderer failed for the session, the panel shows a
warning and points to `CommunityShaders.log`. Disable the extra line later with
`-DeveloperMode off` while the game is closed.

The current source does not render a permanent green `DLSS 5 active` badge.
The normal checkbox plus the Developer Mode diagnostic line are the available
in-game indicators in this build.

## Matched screenshot pair

The native Open Shaders screenshot feature uses the configured screenshot key
(currently `PrintScreen`, `Menu.ScreenshotKey = 44`) and saves lossless output
to its configured folder. The project helper labels the newest native image,
stores an SHA-256 hash, and snapshots the exact DLSSNR settings beside each
side. It does not toggle NR or move the camera, so the experiment remains
explicit and reversible.

1. In the same in-world location, keep headset refresh, render scale, crop,
   weather, and head pose fixed.
2. Start a session:

   ```powershell
   powershell -File .\scripts\Capture-DLSSNRComparison.ps1 -Action Begin -Name solitude
   ```

3. With side A active, press `PrintScreen` once, then run the printed Capture
   command with `-Side A`.
4. Toggle only Enable DLSS Neural Rendering in the Open Shaders panel (or
   restart after applying `-Neural off`), restore the same head pose, press the
   same screenshot key, and capture `-Side B`.
5. Compose a labeled side-by-side image:

   ```powershell
   powershell -File .\scripts\Compare-DLSSNRPair.ps1 -Session <session-folder> `
     -ALabel 'A - NR on' -BLabel 'B - NR off'
   ```

If the native screenshot folder is not the default game `Screenshots` folder,
pass `-ScreenshotRoot <folder>`. If an image was already captured, pass its
path with `-SourcePath`. The pair is written under
`captures\ab\<session>\A.*` and `B.*`, with `A-settings.json`, `B-settings.json`,
and side metadata.

The screenshot pair is visual evidence only. Neural acceptance still requires
fresh Community Shaders evidence of repeated successful evaluations and a
stable two-eye headset check.

## Intensity matrix

For a full comparison, use the matrix helper. It includes a true NR-off
baseline, enabled intensity values `0.0`, `0.5`, `1.0`, `1.5`, and `2.0`, plus
the project-defined Cinematic profile. Each capture is rejected if the active
settings do not match the label.

```powershell
powershell -File .\scripts\New-DLSSNRIntensityMatrix.ps1 -Action Begin -Name solitude

# For each row, apply the matching settings, press PrintScreen, then capture:
powershell -File .\scripts\Invoke-DLSSNRControl.ps1 -Action Apply -Neural off
powershell -File .\scripts\New-DLSSNRIntensityMatrix.ps1 -Action Capture -Profile Off -Session <session-folder>

powershell -File .\scripts\Invoke-DLSSNRControl.ps1 -Action Apply -Intensity 0.5
powershell -File .\scripts\New-DLSSNRIntensityMatrix.ps1 -Action Capture -Profile I0.5 -Session <session-folder>
```

Repeat the same two commands for `I0.0`, `I1.0`, `I1.5`, `I2.0`, and
`Cinematic` (using `-Preset Cinematic`). Compose the completed matrix with:

```powershell
powershell -File .\scripts\Compare-DLSSNRIntensityMatrix.ps1 -Session <session-folder>
```
