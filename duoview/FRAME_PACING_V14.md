# DuoView v14 — validated same-frame evidence repair

## Baseline
The user confirmed in STALKER 2 that the source-integrated public UEVR
DuoView renderer **does** display a high-quality fovea and lower-resolution
periphery. v13's DX12 graphics-memory housekeeping fix did not stop the
periodic 1–2 second VR interruptions: SteamVR background/controllers appear
while the game image disappears, then the game resumes.

This release is based on v13 and the originally user-tested Injector-5.
It is **not** the nonworking Joey plugin builds 69/73. Keep your official Joey
injector separate; remove DuoViewJoey.dll from the game UEVR plugins folder
for this test.

## Static source diagnosis
Original Mono integration in `D3D12Component::on_frame()` explicitly calls
`OpenXR::end_mono_transition_frame()` and returns without a scene when the
per-frame Mono validity check fails. That function creates an empty OpenXR
frame. Such frames can explain why SteamVR's background is briefly visible
instead of the game; this must be correlated with the live log.

Specific source defects found:
1. `OpenXR::update_poses()` clears `mono_frames[frame%QUEUE_SIZE]`
   unconditionally. A second pose update with identical frame count can
   erase the already-observed projection and view-family evidence.
2. `note_mono_main_family()` previously required a projection callback to
   be observed **before** the main view-family callback. Yet the final
   `has_mono_frame()` already requires and verifies both, so the early order
   constraint can needlessly reject otherwise complete same-frame evidence.

The v14 patch retains same-frame evidence when the pose callback repeats and
makes family/projection proof order-independent at the final gate, while still
requiring exact generation, pose frame, projection frame, valid pose, main
family and optical geometry. There is **no fabricated/stale frame allowance**.
The gate now rate-limits a warning with its exact individual proof values:
`[DuoView] Mono frame rejected: frame=...`.

v13 DX12 post-present memory housekeeping fix is preserved. The foveation
layout, view indices, camera, gaze, shader, GPU compositor and OpenXR frame
timings are otherwise unchanged.

## How to test
1. Close STALKER 2. Move the older DuoViewJoey.dll away from the UEVR plugins
   folder. Do not overwrite the normal official Joey installation.
2. Extract this entire **v14 Windows injector** in its own directory.
3. Select OpenXR and start in Native Stereo (ID 0), as required by this
   experimental public UEVR backend. Inject using this build's injector.
4. Once native image appears, select DuoView Mono (ID 6).
5. Use the same scene and crop settings that displayed the working fovea
   in v13. Watch for SteamVR background/controller interruptions; check
   whether they stop or become less frequent.
6. If any 1–2-second dropout remains, stop. Upload the new `UEVR.log` or
   `log.txt`. Search for `[DuoView] Mono frame rejected`,
   `[Mono] Empty transition frame`, `xrEndFrame`, `xrWaitFrame`,
   `xrBeginFrame`, and DX12 device reset events. The next fix should
   follow those correlated failures, not a new foveation architecture.

CI regression verifies exact original-backend source patch, repeated same-
frame callback ordering, Windows DLL and injector compilation and production
WARP D3D12 compositor. Passing CI does not prove hitch-free headset runtime.
