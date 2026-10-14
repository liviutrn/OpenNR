# DuoView v40 — Sensor/Temporal Coherence Source Audit (14 October 2026)

## Status and scope
**NOT A GAZE STABILIZATION FIX. NOT RELEASED.** Based on isolated `experiments/duoview-gaze-sensor-coherence-v40` from v39 checkpoint `ce9bd292e75a48f70ba74aafe611919537291753`. Does not alter UE historical matrices, projection/camera timing, or raw gaze crop. Stable Joey Build3, Build33 and Build37 are untouched.

## Why fixed-center remains stable and moving gaze does not
- With fixed-center, the off-axis foveal projection remains constant. Normal Unreal camera movement and native temporal history cooperate.
- With tracked gaze, UE foveal projection is altered each producer frame. For static world and head but moved ROI, correct **crop-local** current->previous pixel motion is `(currentOrigin - previousOrigin)*foveaSourcePixels / cropExtent`. Previous-projection mismatch or incorrectly scaled motion results in jelly/reprojection artifacts.
- `apply_stage234.py` patches only **current** FSceneViewInitOptions projection, not actual UE previous ViewState/TSR/DLSS state; independent CPU/WARP tests do not prove game consumer correctness. The exact user-observed error is **still uncorrected**.

## New source-backed finding: CAPI false/no-new behavior
Pinned public PSVR2 Toolkit source:
- `projects/psvr2_toolkit_capi/psvr2tk_capi.cpp` calls `CustomShareManager::getGazeStatus(..., &g_lastGazeStatusCounter, timeoutMs)`.
- `projects/libcustomshare/custom_share_manager.cpp::getGazeStatus()` increments/checks a **shared status update counter**. When `timeoutMs==0` and counter unchanged it **copies the same status into the caller buffer and returns false**. Thus false means **no new data**, not sensor invalid. Existing DuoView code correctly holds last UV briefly rather than treating false as a blink.
- The raw Toolkit struct contains `raw.timestamp` and `raw.frame_counter`. Their clock relationship to XR predicted display time is not established by these CAPI sources; do not invent conversion, speed prediction or XR synchronization.
- Current `VR::get_eye_transform(0)` reads `get_runtime()->eyes[0]` under `eyes_mtx`. Pinned Joey OpenXR `update_matrices` populates `eyes[0]` from `xrLocateViews` and Mono projection from the common optical union. This is more temporally disciplined than arbitrary per-pass sampling, **but raw gaze CAPI has no proven matching pose timestamp**.
- Stage B/E0 source discovery supports metadata observability and a future safe frame/pose synchronization contract, not a claim that unsynchronized CAPI is definitively the jitter root.

## Source changes on v40 (read-only, no runtime gaze algorithm change)
- `DuoViewPSVR2Gaze.hpp`: `GazeObservation` preserves host receipt millisecond count, raw sensor frame counter/timestamp and validity from the SAME new CAPI read. `Reader::observation()` returns a mutex-protected snapshot; the renderer continues to resolve UV exactly as before. No CAPI ABI or new global hooks.
- `apply_stage234.py`: an opt-in ImGui display under existing temporal audit shows raw source IDs/clock **only when the in-game diagnostic is enabled**. No frame-time log loop, no GPU stalls, no interpolation.
- `ProductionPSVR2GazeTests.cpp`: checks exact metadata copying from controlled fake sensor packets and independently invalid packet recording.
- `verify_stage234.py`: asserts generated production source really records/accesses sample evidence; fail closed on missing helper or UI.
- Dedicated v40 branch Windows workflow against unchanged exact pinned backend/sdk/frontend and full original regression suite.

## Critical unresolved Stage B/D blocker
Exact UE version advertised for STALKER 2 Update 2.0 is UE 5.5.4 (see GSC Zone Kit Phase 2 official announcement), but actual runtime upscaler settings and consumer previous projection/velocity/Jitter are NOT observed. Public Epic UE5.5 `FSceneView::ClipToPrevClipOverride` is a potentially relevant engine-native previous-clip interface, however pinned Joey UESDK does **not** expose its validated address/offset/method. Writing an invented offset, wrapping NGX globally, resetting history each eye movement or simply smoothing crop is specifically rejected.

## Status and next source work
1. Audit v40 dedicated Windows compile/WARP/CPU and original Joey results; do not infer pass from queued/in-progress work.
2. The next research target is a safe precise UE 5.5.4 **renderer-owned** previous projection/viewport/velocity API or a bounded pre-temporal hook. Without proof, STOP and do not build a headset candidate. Native Zone Kit modding tools alone do not prove C++ render-stage injection in the shipping game.
3. Once a validated temporal interface is available, use the independent world-point oracle plus metadata to prove exactly one crop-delta correction. Preserve last successful engine history rather than `State::consume()` CPU eligibility.
4. After D/E pass, introduce OpenNR r10 *small* 1-2 output-pixel fixation guard with immediate saccade bypass. Never hide uncorrected jelly with a 45-pixel dead zone.
5. Shader WARP world-grid, two-source actual high-density, GPU lifetime, complete Windows CI+manifest/hashes and separate independent review before one headset candidate.

**STOP RULE:** No source-verified previous clip consumer = no claim to have fixed the shaking, irrespective of green CI.
