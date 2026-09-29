# Full-resolution capture result — OpenNR 0.5.5 — 2026-09-06

The 0.5.5 full-frame capture test finished after Skyrim exited. The installed runtime DLL was preserved unchanged:

```text
E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.5 OpenNR\SKSE\Plugins\CommunityShaders.dll
SHA-256: ECC2B784F19037CD3AD97D265883440D21C92BACD8674D6F13E258ADD9149CAE
```

Capture root:

```text
E:\OpenNR_Captures_Temporal_MasterRaw_0.5.5_20260905
```

The root contains 71 complete records across three sequences:

| sequence | records | full-frame complete | initial reset | backpressure | host gaps | strict temporal result |
|---|---:|---:|---|---:|---|---|
| `seq-1788664426311-1` | 64 | 64 | `[false,false]` | 0 | none | rejected: missing initial reset |
| `seq-1788664453250-2` | 6 | 6 | `[false,false]` | 2 | 138, 177 | rejected: backpressure and gaps |
| `seq-1788664480697-3` | 1 | 1 | `[false,false]` | 3 | n/a | rejected: backpressure, one frame |

The main sequence is valuable full-resolution spatial/reference evidence: every committed frame is complete, both eyes and all native stages are present, and frame/sample/host counters are contiguous. It is not reset-qualified temporal supervision. The two short tails remain preserved as failure diagnostics and are excluded from training.

Validation outputs:

```text
D:\.CODEX_Projects\OpenNR-VR\out\temporal_audit_fullres_temporal_0.5.5_20260906.json
```

The full-frame path still emits required PNG masters, so raw-only settings do not make a full-resolution temporal writer fast enough for repeated clips. The active settings have therefore been switched to a separate crop-temporal profile after backing up the previous settings:

```text
Backup: E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-crop-temporal-0.5.5-20260905-232505\SettingsUser.json
Active: E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json
Profile: D:\.CODEX_Projects\OpenNR-VR\out\live_capture_temporal_crop_preparation_0.5.5_20260906\SettingsUser.OpenNR-CropTemporal.0.5.5.json
Output: E:\OpenNR_Captures_Temporal_Crops_0.5.5_20260906
```

The non-capture settings were unchanged, the active capture configuration validates, and the DLL hash remains unchanged. Launch the normal MGO profile, force a clean Feature 18 reset before each finite burst, and verify `[true,true]` on the first crop record before collecting the four requested scene conditions.
