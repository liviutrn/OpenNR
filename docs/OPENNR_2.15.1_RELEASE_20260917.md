# OpenNR 2.15.1 release and local update

Date: 2026-09-17. Includes the current working-tree renderer/adaptive changes plus
the native OpenVR gaze repair. The validation run itself created no release tag or
published artifact; branch publication and the upstream PR update are tracked
separately from this local release record.

## Deliverable

- AIO: `E:/OpenNR_Builds/2.15.1/dist/OpenNR 2.15.1.7z`
- Archive: 228,060,032 bytes; 490 files; 440,836,907 uncompressed file bytes.
- Archive SHA-256: `EACDEF4A496112EEE900FB00140D12CBE52E541B09D297A307D7C6324FEC60E1`
- DLL version: 2.15.1.0.
- DLL SHA-256: `88678653B66589A9B8737CA194BFEBA1C6AA80163B3C3E1800A9903B3AB7A10D`
- Changes: [packaged changelog](../runtime/open-shaders/package/OPENNR-2.15.1-CHANGELOG.md).

The AIO contains the native Feature 18 carrier, OpenNR Capture support, the full
declared feature payload, and current shaders/translations. Automatic deployment
was disabled during the build. The pinned external dependency snapshot remains
`C:/OpenNR/Dependencies/runtime-2.15.0`; its directory name is provenance rather
than the release version. Current build defaults now resolve to the 2.15.1 tree.
Historical 2.15.0 records remain historical; its old package changelog was moved
to `runtime/open-shaders/docs/releases/` so the new AIO has exactly one changelog.

## Eye-tracking implementation

The tester used Native OpenVR gaze provider. The repair makes movements larger
than two input pixels bypass the smoothing filter, including with saved 20 ms
smoothing. Smaller fixation noise can still be filtered; new settings default
to zero smoothing. A central guard is at most 2% of the eye extent, capped at 5%
of the crop extent per axis. It holds the crop through fixation jitter and
recenters immediately when escaped. Quantization is bounded by that guard.

Every actual crop-origin/extent change in the gaze path invalidates NR history
and sets the DLSS SR reset flag for that evaluation. Ordinary disabled-gaze
adaptive-crop changes do not acquire this new gaze-reset behavior. Native game
motion and depth are preserved. This release uses conservative history resets;
it does not claim overlap-preserving crop-motion reprojection. A reliable
exposed-region mask for the native Feature 18 route has not been established.

Tracking loss holds the previous crop for up to 50 ms, then returns to static in
one handoff. The 150 ms animated return was removed. Static/dynamic fallback
transitions with unchanged dimensions no longer change the gaze resource hash.
VRS, when enabled, consumes the same cached per-frame gaze result as DLSS/NR.

The UI now distinguishes time since a valid local query from sensor age. The
`Upscaling` devbench `eyeTrackingStatus` query exposes validity, query duration,
raw/filtered gaze, resolved crop coordinates, and crop/history-reset counters.
The API still has no sensor timestamp; no sensor-to-photon latency is claimed.

The earlier audit is [available here](../reports/EYE_TRACKING_LATENCY_AUDIT_20260917.md).
Its findings describe the pre-fix state; its proposed vector-compensation path
was not shipped in place of the conservative reset policy.

## Other recent changes included

- Stable adaptive crop backing allocations with explicit current valid extents.
- Corrected model-resolution sampling inside larger resource envelopes.
- Session memory-pressure NR ceiling, tier retention/prewarming restrictions,
  and reset/restart recovery of the learned ceiling.
- Current Streamline VRAM-warning and duplicate-constant handling, NR recovery
  policy, bounded tier residency, and queued reset/status actions.
- Current adaptive-budget UI and previous map/UI follow-up source changes.

The pre-existing working-tree diff and source/test backup are retained under
`C:/OpenNR/ReleaseBackups/2.15.1-20260917/`. No existing change was reset or reverted.

## Verification

- Clean external Release build: success; native DLL metadata 2.15.1.0.
- Runtime source-contract validator: passed.
- C++ tests: **185 test cases, 9,254 assertions passed**.
- Gaze tests cover saved smoothing, pursuit/saccade response, bounded fixation,
  continuous pursuit, quantization, and crop bounds.
- Production model-resolution shader executed on D3D11 WARP: **16/16 cases
  passed, maximum difference zero**, comparing tight textures against poisoned
  oversized resource envelopes.
- Path tests: 5 discovered, 4 passed, 1 skipped.
- AIO and exact lean-stage package validators: passed.
- 7-Zip integrity test: passed.
- Extracted archive: every file matches stage by path, size, and SHA-256.
- Local installation: every package file matches stage; only `meta.ini` is extra.
- `git diff --check`: passed (line-ending normalization notices only).

Evidence: `build.log`, `cpp-tests.log`, `shader-test.log`, `package.log`,
`archive-test.log`, `archive-manifest.json`, `installed-manifest.json`, and
`install-record.json` under `C:/OpenNR/ReleaseBackups/2.15.1-20260917/`.

## Local installation and rollback

Active profile: `E:/MGO-RC3-fresh/profiles/MGO NSFW - 4.0 BETA`.
New mod: `E:/MGO-RC3-fresh/mods/OpenNR 2.15.1`, enabled at the former OpenNR
position. Previous `OpenNR 2.15.0` remains on disk, disabled. MO2 was restarted
and its UI confirmed the new enabled entry and disabled rollback entry.

Full old-mod backup, settings and profile files:
`E:/MGO-Installer/Codex-Backups/OpenNR-2.15.1-20260917/`.

The overwrite `SettingsUser.json` is byte-identical to the backup, SHA-256
`5A9B3E8CF6D72D312F1C40632FDBCC1FAE6EE62CC7E41982D451530EAA8F571B`.
Gaze and VRS remain off in this user's saved local configuration; the update
does not silently enable them. Adaptive and other saved values remain intact.

To roll back with the game closed, disable 2.15.1 and enable 2.15.0 in MO2.
The separate backup also preserves the pre-update mod list and settings.

## Remaining acceptance

No game/headset run was performed. Existing local validation notes report no
installed devbench host. Source/build/package/install evidence does not establish
stereo correctness, eye-to-display response, native reset cost, visual stability,
or a sustained VR frame-time improvement. The FPS collapse's exact bottleneck
remains unmeasured; frequent crop relocations can still reset history frequently.

The next tester run should compare fixed crop against native gaze in one scene,
with fixed crop/model size, then check pursuit, saccades, blinks and head motion.
Record frame times and the new query/crop/reset diagnostics. Test VRS separately.
