# DuoView Mono UEVR v23 Build32 — gaze stability continuation handoff

Prepared 2026-10-14. **Binary compiled source SHA:** `8d13ad8f6cc49bc0ebdb4ea3373c37f1298bac32`. Isolated branch `experiments/duoview-temporal-shading-v22` remains named v22 for compatibility with its exact pinned Actions workflow. Docs-only commits after this SHA do not change the tested binary.

## Results and artifact

**Full Windows CI SUCCESS:** https://github.com/liviutrn/OpenNR/actions/runs/38565044386

**Working complete injector artifact:** https://github.com/liviutrn/OpenNR/actions/runs/38565044386/artifacts/11896096623 (artifact `Joey-DuoView-Temporal-v23-32`; ID `11896096623`). The outer artifact contains `Joey-DuoView-Temporal-v23-32.zip` and its SHA256 sidecar. Extract inner ZIP for all injector files.

- Outer artifact SHA256: `ab8cbf4f1a3fd6129507942cd9161a2368bb7595047db5705b68de76142bb030`, independently matches GitHub artifact metadata.
- Inner injector ZIP SHA256: `84be5e24004252f17d73e389129c10c681e163956432e32bf88efc8cb41096c8`, independently matches bundled SHA sidecar.
- `UEVRBackend.dll`: `5537bff3fb5b52cd4925e0d3391a6adc3c2de89ee3c19035cbf3e99e593ae773` (16,300,032 bytes).
- `LuaVR.dll`: `72f9ca52c3e408f2a653d632ac0b8ff1f293f22d093a58e2f29e7828e906d67e`.
- `UEVRPluginNullifier.dll`: `9408b4a3d3b46110dd0ad9802297838f60e497bee704a6b6f22e64684cdef52d`.

**All 50 Windows tests passed:** 3 pinned contracts (including DX12 WARP) + 6 independent geometry/gaze/state/WARP tests + 41 original Joey compatibility tests. Exact-source baseline verification, Stage1/Stage234 source-hash verification, full backend/auxiliary DLL build, original frontend tests/publish and source identity recheck all passed. Downloaded artifact independently CRC-tested (outer/inner), checked SHA sidecar, all 14 files and AMD64 PE headers, and packaged pinned original source metadata.

## User headset feedback motivating this build

Build29 v22 (`bd8024c9e83debaaee6890d36c756f186e8421e1`, run38557341481) still shakes and trembles during eye tracking: both crop edge and image inside crop; worse when gaze is held relatively still and head moves. **Fixed-center mode is stable.** Its crop guard was a spatial hold/quantize/recenter mechanism, *not* true temporal smoothing. User explicitly authorized stronger smoothing and larger guard.

## v23 implementation (exact source commit above)

- `duoview/DuoViewCropStability.hpp`: replaces abrupt guard threshold jump with a continuous deadzone and gradual, time-based exponential following plus 1.4 full-screen UV/s per-frame speed cap. Frame `dt` limited to 33ms following stalls. Crop translation aligned to a single foveal source pixel, not the old four-source-pixel steps. Short missing-gaze gaps hold for 100ms; longer gaps move smoothly to center with deadzone bypass. No update to previously accepted frame snapshots.
- `duoview/DuoViewConfig.hpp` and `duoview/joey_stage1/apply_stage234.py`: persisted guard control 0–25% of crop (default 8%), smoothing 0–250ms (default 85ms), enabled via existing stable-crop toggle. Frozen source-frame packet contains the chosen settings, crop origin, projection and atlas geometry; both UE source views and DX12 compositor consume it. Wide guards trade foveal centering for reduced fixation jitter.
- `duoview/DuoViewPSVR2Gaze.hpp`: sampled calibrated Toolkit CAPI ray is now transformed and projected into UV **only on fresh acquisition** using same-frame left optical pose and producer projection. For no-new-frame polls, previously mapped UV is reused up to 50ms, avoiding a stale raw ray being recomputed against newer eye optical transforms during head motion. Blink/invalid input clears cached UV immediately.
- `duoview/stage10_state_tests.cpp`, `duoview/joey_stage1/ProductionContractTests.cpp`: assert stable fixation, continuous bounded gaze pursuit, gradual return after expiry, single-source-pixel alignment and bounded option validation. `verify_stage234.py` checks new UI/control wiring.

Iterations before successful Build32: run30 `38564530643` failed due Python verifier syntax; corrected commit `7e21427c`. Run31 `38564735847` caught an authentic bug where wide guard trapped expired gaze; corrected in `8d13ad8f`. Final run32 passed all gates.

## Protected original baseline and scope

Exact original Joey backend `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`, original restricted `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`, frontend `joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091`. Original Joey Mono ID5 Build3 (run38453012351, 30-min headset stable) is **protected**; so is Native Stereo ID0. New behavior is isolated to experimental DuoView ID6 in STALKER 2 DX12 through SteamVR OpenXR. No restricted SDK source is bundled.

**Do not claim game motion vectors or TSR histories are fixed by CPU CI:** this implementation does not patch UE ViewState memory, velocity buffers, camera cuts or native XR submission; those could cause regressions or double compensation without game evidence. Build32 is rigorously source/Windows validated but **not yet headset validated**. The user needs to check fixation, head movement, deliberate saccades, tracker loss, fovea-only diagnostic mode2, eye-tracking OFF control, shading toggle OFF initially, and long-session frame pacing.

## Headset checklist

Use a separate directory from stable Joey Build3 and Build29. Extract the complete inner injector ZIP and run `UEVRInjector.exe`. In STALKER2 DX12 choose ID6, tracking ON, `Smooth tracked crop` ON, guard .08, smoothing 85ms, source diagnostic 0, independent primary shading OFF. Look at a stationary near/far high-detail feature, move only head with gaze steady, then make deliberate eye shifts; compare to eye-tracking OFF fixed center. If boundary still trembles, try 150ms + 15% guard before raising to extremes. If boundary is steady but foveal content still trembles, inspect fovea-only diagnostic 2: it likely needs targeted engine temporal history/motion analysis, not indiscriminate gaze filtering. No runtime timing claim is made.
