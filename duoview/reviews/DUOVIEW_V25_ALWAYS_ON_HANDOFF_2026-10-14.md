# DuoView v25 — always-on startup and gaze camera candidate

Status: implementation/local CPU checks complete; Windows CI and headset acceptance pending.
Branch: `experiments/duoview-v25-gaze-camera-always-on`.
Parent: `c38e929da2979a52b43726bcdd17e8f53f078cc8` (Build33 source plus rejected-crop handoff).

Build33 was rejected. User now confirms DuoView/fixed-center crop works, but eye-tracked crop and contents jitter. Do not claim this new candidate is headset-verified.

## Changes

- Dedicated RenderingMethodSetting activates ID6/generation1 in its constructor, ignores other mode requests and normalizes profiles to ID6. Frontend exposes/defaults/displays only ID6. The original pure Selection transaction remains for Joey compatibility tests; the shipping setting never enters ID0.
- Confirmed startup dependency removed: `attempt_hook_fsceneview_constructor()` previously installed only for Native Fix/Ghost Fix/compatibility modes, all normally inactive in Mono. DuoView installs that essential hook itself. Original stereo-device view-count/pass and RT hooks initialize directly, without rendering mode ID0.
- Compact scene source is separate from final XR output. Default 5000x5000 uses 3504x2504 scene atlas instead of 10000x5000. Rectangles align to eight pixels. XR output stays full resolution. Total VRAM capacity still limits resolution.
- Eye-tracked fovea is a gaze-directed narrow camera at the same mono position as periphery, with symmetric frustum covering desired crop corners. Shader reconstructs full-view world rays and maps them through that exact camera. Gaze movement appears in native view rotation instead of solely as changing lens shift.
- The two views share camera position, **not identical rotation**. This is intentional and the compositor accounts for it. Eye tracking OFF preserves the prior fixed-center off-axis path.
- Valid gaze is immediate: no delay/guard/quantization/speed cap. Missing tracking holds the last coordinate until fresh gaze; no old scene image is reused. Reset retires snapshots, increments independent epoch and returns gaze to center, with ID6 still selected.
- Failed/incomplete frames are withheld and retried. No full-resolution original Mono or native-stereo fallback. Tracked frame acceptance requires distinct SceneStates and constructor application of the foveal rotation.
- Saved conflicting compatibility flags normalize OFF. Optional in-game independent shading remains and starts OFF.

## Validation and limits

Local g++ passes: geometry, gaze, frame, config, state, new camera suite (8100 ray round-trips, instant gaze/reacquisition, loss hold, compact 5000 layout, restart), pinned production contracts including direct ID6 startup. Exact-anchor patches apply to pinned backend/frontend. No private SDK edits/publication.

Windows CI additionally compiles HLSL offline, runs pinned/independent GPU WARP tests with compact source and full-sized output, verifies stationary world-ray patterns across abrupt gaze moves, runs original Joey compatibility suite, tests/builds matching frontend and packages DLLs. CI status will be appended after completion.

No STALKER 2 GPU capture or PSVR2 execution is available here. Native camera motion is intended to use Unreal's ordinary temporal matrices/velocities; actual TSR/DLSS/Lumen stability is not established by synthetic tests. No guessed private history offsets are patched. Actual high-detail foveal scene pixels remain hardware acceptance evidence.

## Pins and protected baseline

- Backend: `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`.
- SDK: `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`, unchanged; existing authorized CI secret.
- Frontend: `joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091`.
- User-confirmed Joey Mono Build3: `64432d0442066715fa442660a0848cf4963640b0`, run38453012351, untouched. Extract candidate separately.

## Entry points and acceptance

`apply_stage25.py` runs after existing Stage1/234 anchors. New camera math: `DuoViewFovealCamera.hpp`; source latching: `DuoViewState.hpp`; GPU mapping: composite shaders and `DuoViewD3D12.hpp`. Tests: `gaze_camera_tests.cpp`, `ProductionContractTests.cpp`, `production_warp_test.cpp`.

Target STALKER 2 DX12 / SteamVR OpenXR / PSVR2 Toolkit CAPI. Debug source 0=blend, 1=periphery, 2=fovea. Validate direct high-resolution startup and restart, fixed center versus gaze, rapid gaze/head movement, blinks, and fine scene detail with fovea-only diagnostic. Do not call jitter fixed until the user accepts the headset result.
