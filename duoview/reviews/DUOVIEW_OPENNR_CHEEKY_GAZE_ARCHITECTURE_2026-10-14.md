# DuoView eye-gaze stability — OpenNR r10 + Cheeky architectural re-evaluation
Prepared: 2026-10-14. Scope: source-backed comparison and next engineering contract, NOT a completed gaze fix or hardware-validated build.

## User-observed control
- DuoView fixed-center UE fovea perfectly stable.
- Tracked-gaze DuoView crop edge AND independently rendered scene within shake/jelly, especially during head yaw/pitch with steady world fixation.
- Cheeky SR follows gaze without flicker in user's tests, but Cheeky NR has shown flicker; do not misstate both as perfect.
- Preserve exact Joey Build3 (~30 minutes stable in STALKER2 Mono ID5), Build33 manual Native0->DuoView ID6 working fixed-center; Build37 automatic bootstrap not yet headset-accepted.

## Verified source facts (exact read)
1. OpenNR r10 (`build/2.20.1-v06-r10-stable`): `runtime/open-shaders/src/Features/Upscaling/NativeOpenVRGaze.cpp` reads native OpenVR IVRSystem_026::GetEyeTrackedFoveationCenter (OpenVR already outputs NDC eye-foveation centers), caches one `ResolveForFrame` result for the engine frame, uses `GazeCropPolicy::Filter` and `ResolveOrigin`. The filter bypasses for >2 rendered pixels. ResolveOrigin has bounded guard and quantization; gaze reacquisition resets history and missing samples hold 50 ms. This works in a post/render-pipeline crop domain rather than creating new Unreal scene views. `ResolveForFrame` also marks a crop change as a renderer history-reset event in its particular pipeline; that behavior must not be transplanted into Unreal or NVIDIA.
2. Cheeky fork r13 pinned upstream `ClarkCheekyKent/CheekyFoveatedDLSS@4e47eefe51a512dcaf76bbdc672dcdab5251fc71`; `CheekyPort/overrides/src/OpenNR_R10_GazeCropPolicy.h` contains verbatim OpenNR r10 Filter+ResolveOrigin. The upstream `src/crop_motion.hpp::crop_motion_offset` computes additive previous-local current-to-previous displacement from current-origin minus previous-origin with source MV unit scale, and `src/d3d12_backend.cpp` submits corrected PRIVATE vectors when crop moves and history is preserved, or resets when correction is not valid. `src/gaze_foveation.cpp::calculate_coordinated_crop` caches a per-view coordinated crop; the OpenXR layer projects tracked gaze with located view pose + submitted FOV; r12 separately changed NR reset policy for tiny scale-rounding differences. Cheeky SR stability is evidence for correction and synchronization, not proof that NR never flickers.
3. DuoView Build33/37: `duoview/DuoViewGeometry.hpp::apply_foveal_crop` alters source UE view projection every time gaze moves. `duoview/DuoViewState.hpp` latches layout and gaze for an engine frame, and `duoview/DuoViewComposite.hlsl` maps an independently UE-rendered high-density source to CropUv ROI. However `apply_stage234.py` rewrites only CURRENT `FSceneViewInitOptions` projection and says explicitly that UE previous view state, TSR/Lumen/velocity inputs are NOT corrected. `temporal_audit()` compares state identity/expected crop delta; it does not validate prior matrices consumed by actual temporal reconstruction. This is the principal unclosed architectural contract.

## Nontransferable difference
OpenNR and Cheeky move a crop within render/postprocessing and can compensate crop-local motion in their controlled reconstruction passes. DuoView changes the 3D view frustum BEFORE UE renders. A compositor-only shift of motion vectors or copying a guard policy cannot repair history already consumed inside Unreal. A static or translated crop taken from low-resolution periphery is unacceptable: user requires genuine separately rendered high-res fovea.

## Exact temporal invariants to prove
Let full-screen top-left UV be U, per-frame crop ROI origin o=(u0,v0), fraction s=(cw,ch), high-res source viewport size R=(fw,fh). A world point has current full UV U_n and prior full UV U_{n-1}, including its corresponding camera projection. Its current local fovea UV is (U_n-o_n)/s. Its previous local UV is (U_{n-1}-o_{n-1})/s. The current->previous local motion in pixels is:
 m_local = R * [(U_{n-1}-U_n) + (o_n-o_{n-1})] / s.
The second term R*(o_n-o_{n-1})/s is the crop-origin correction Cheeky already implements in its own pipeline. Validate sign relative to UE velocity convention; this equation is a current-to-previous convention and requires adjustment if actual UE buffer convention differs. If Unreal's previous projection is head-only/uncropped, it loses that correction and (worse) can mix source viewport transforms. Merely making current `FSceneViewInitOptions::projection_matrix` equal the foveal projection is insufficient.

When the world point is at rest with no head motion, post-composite U output must remain CONSTANT for any gaze/crop movement. When head moves, it must follow the exact full-camera transform, not add extra crop-origin motion or image jelly. View rect, screen percentage, temporal jitter, exposure, view-state and previous projection must be coherent. Include asymmetric FOV tests, saccades and blink reacquisition.

## Revised implementation order
A. Keep Build37 launch restoration and all untested launch state separate from gaze. Build37 run 38623649137 was still in_progress at the latest source check, no published artifact. Do not call it known-good.
B. Start from Build33's user-seen working fixed-center/manual mode path while isolating gaze mechanics, or Build37 only AFTER launch accepted.
C. Design foveal UE-native previous-frame transform/history correction BEFORE TSR/DLSS/velocity consume it. First inspect actual pinned Joey sceneview constructor and available verified UESDK types/engine interfaces. Do not invent private offsets or intercept nvngx. Capture a one-shot gated diagnostic of UE previous/current matrices and frame identities. If no safe writer/reader exists, do not ship an approximate fix.
D. As control, use a non-temporal fovea-only resolve to isolate history from geometry (not a production quality solution); if jelly disappears while crop remains, it confirms history branch. Check independent high-res detail; do not turn off temporal globally.
E. Port EXACT r10 tiny fixation guard/quantization after coherence is correct, converted to FULL OUTPUT/source pixel coordinates and shared by UE frustum + compositor. Deliberate saccades bypass; no laggy smoothing. Use Cheeky's per-view frame policy and asynchronous native gaze hold as comparative references.
F. Unit/oracle tests for static world fixation during head yaw/pitch, noncentral gaze, crop origins stepped by 1/3/large pixels, both fovea view index orders, and rect-to-atlas mapping; Windows pinned source build/test, actual shader WARP, full Joey compatibility suite, package hash, then ONE headset verification.
G. Fix camera/gaze optical basis if verified mismatched; optional OpenVR GetEyeTrackedFoveationCenter may serve as a side-by-side diagnostic, but NDC per-eye output cannot simply be equated to DuoView's asymmetric Mono optical projection.
H. Move no NGX interception; do not restore compact atlas or force ID6 at injection. Never overwrite Joey Build3.

## v38 warning
Experimental branch `experiments/duoview-gaze-pose-latched-v38` currently contains two source edits that defer gaze until after first UE Mono camera offset. It was made before this architectural comparison and is NOT CI wired, NOT compiler-tested, NOT validated, and NOT sufficient to correct UE temporal reprojection. Do not label it stable or deploy. Re-evaluate or discard those edits after prior-frame temporal contract is understood.

## References
- https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r10-stable/runtime/open-shaders/src/Features/Upscaling/NativeOpenVRGaze.cpp
- https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r10-stable/runtime/open-shaders/src/Features/Upscaling/GazeCropPolicy.h
- https://github.com/liviutrn/OpenNR/blob/experiments/cheeky-psvr2-r13-duoview-eye-select/CheekyPort/overrides/src/OpenNR_R10_GazeCropPolicy.h
- https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/crop_motion.hpp
- https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/d3d12_backend.cpp
- https://github.com/liviutrn/OpenNR/blob/experiments/duoview-build33-lowres-native-bootstrap-v37/duoview/joey_stage1/apply_stage234.py
