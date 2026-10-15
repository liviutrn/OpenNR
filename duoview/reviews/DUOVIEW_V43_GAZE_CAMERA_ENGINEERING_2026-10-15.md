# DuoView v43: gaze as ordinary camera motion

Status: implemented candidate, not headset-validated. The original game's consumed temporal matrices remain unobserved. Do not promise that the user's shaking is fixed from CI alone.

Branch: `experiments/duoview-gaze-camera-steering-v43`.
Base: v42 `48a9f673a09189becd56eb1360df37ebaac4dcb8` (public tree exactly matched the earlier local v42 repair). Protected Joey Build3 and all original SDK/backend/frontend pins remain unchanged.

## Why this implementation differs

v41 shifted finished RGB using a temporal crop-motion term. v42 removed that mathematically incorrect general correction. Neither changed how the real UE view moved.

v43 represents gaze movement by rotating the real narrow high-resolution camera about the same Mono optical origin. Its projection principal point stays fixed. The periphery keeps the original Mono camera and full projection. A current-frame projective homography maps foveal rays into the same full Mono image. This uses the ordinary camera-motion contract for Unreal's existing temporal handling, rather than adding projection-center translation each gaze frame or patching unknown historical matrices.

This removes dynamic off-axis principal-point movement as an input to the temporal renderer. It is an architectural response to the reported fixed-center-stable/moving-center-unstable behavior. It is NOT evidence that missing prior projection was the actual game-side cause, nor proof that all game temporal passes honor injected camera motion. Runtime image acceptance is still required before calling the gaze issue solved.

## Exact geometry

Given +Z-forward full projection P with focal scales px,py and center terms ox,oy, full output UV (u,v) gives a ray:

    d=((2u-1-ox)/px, (1-2v-oy)/py, 1).

The latched/clamped gaze ROI center gives unit forward f. Define r=normalize((f.z,0,-f.x)) and t=cross(f,r). These axes form a rigid camera basis, not a shear or a translated camera.

The foveal projection uses scales px/cropWidth and py/cropHeight, zero x/y principal-point terms, and the original depth/W projection terms. It is independent of gaze for a fixed full projection and crop size.

For any full-image ray d, the actual foveal coordinate is:

    localU=0.5+0.5*(px/cropWidth)*dot(r,d)/dot(f,d)
    localV=0.5-0.5*(py/cropHeight)*dot(t,d)/dot(f,d).

`make_steering` expands these expressions into a 3x3 homography stored as three padded float4 rows. The shader uses this SAME current-frame mapping for source sampling and coverage/feathering. No previous-frame displacement is added to current color. Rays behind the foveal camera are outside coverage.

A pure rotation homography is depth-independent because both views have the exact same optical origin. This is not DIBR and needs no depth readback.

## Real renderer integration

`DuoViewSteering.hpp` constructs and validates the basis/homography, applies the centered projection, and composes the foveal orientation with the canonical UE Mono pose. UE Euler conversion includes a vertical-look singularity path. Nonfinite or unsupported perspective inputs fail the existing frame gate.

`State::begin` creates the homography from the same immutable projection/ROI packet used by both source views and composition. On the first source camera callback, State stores the canonical Mono pose and computes both actual source poses ONCE. Returning stored poses avoids re-evaluation rounding disagreement in strict pair validation.

The generated source0 callback captures original Joey output AFTER its mod post-offset callbacks, then writes the selected stored source0 orientation to the actual output Rotator. Source1 reuses its stored actual source pose. If source0 is foveal it steers while source1 is canonical; if source1 is foveal source0 is canonical and source1 steers. Positions are identical in both cases.

`apply_frame_projection` returns the centered narrow projection only for tracked foveal view. The typed SceneView constructor reconciliation preserves the same projection. Original IDs 0/5 never activate DuoView code.

## Fixation noise

The existing persisted stabilization toggle now controls a one-OUTPUT-pixel spatial fixation guard. It holds only when both axis differences from the retained coordinate are <=1 output pixel. Any larger change updates immediately in that producer frame; there is no low-pass temporal smoothing, velocity cap, or integer quantization. Old broad guard and smoothing settings remain ignored. UI identifies the one-pixel guard explicitly.

## Preserved behavior and tradeoffs

- Eye Tracking OFF keeps the original fixed-center projection, camera and ROI sampling path. The steering helper returns the original pose without trig work in this path.
- Existing crop sizes, foveal texture dimensions/density controls, periphery dimensions, atlas allocation, source selector, bootstrap, safety quarantine, GPU timing opt-in and independent shading toggle remain available.
- Fovea pixel count does not increase and no extra rendering pass, GPU readback, temporal resource allocation, NGX interception or private UE memory write is introduced.
- Tracked crop sizes now define the narrow camera's angular/tangent frustum around gaze. Away from the center its outline on the full Mono plane is perspective-shaped. It is not exactly the old axis-aligned UV rectangle. At eccentric gaze, sampling density changes at the fixation point as well as at the edges. For horizontal eccentricity theta and otherwise identical settings, the new camera has cos(theta)^2 times the old off-axis crop's horizontal pixels per degree at the ROI center. With projection scale 0.78 and center u=0.75, theta is 32.7 degrees and the ratio is 0.709: about 29% fewer horizontal samples per degree. Do not claim identical center or edge PPD to the old off-axis renderer.
- Compositor root constants expand from 88 to 144 bytes (36 DWORDs), with explicit C++ size check and matching HLSL packing. Remains within the D3D12 root-signature budget.
- GPU execution time, actual game AA/Lumen behavior, injection success and headset stability have not been measured here.

## Fresh OpenNR/Cheeky/Toolkit comparison

OpenNR r10 `NativeOpenVRGaze.cpp` uses IVRSystem_026 GetEyeTrackedFoveationCenter, one-frame caching, a small fixation filter, origin guard and resets its controlled SR/NR histories on every crop origin change. Thus earlier claims that r10 exposed a directly portable Unreal previous-projection repair were unsupported. `CameraReprojection.h` computes current/previous transforms inside a reconstruction pipeline it owns.

Pinned Cheeky `4e47eefe51a512dcaf76bbdc672dcdab5251fc71` `src/crop_motion.hpp` adjusts private temporal motion-vector inputs with current-minus-previous crop origin. Its `gaze_policy.cpp` also has selective compatibility/reset policy. `openxr_layer.cpp` uses OpenXR gaze action/sample-time paths. None grants DuoView safe private UE previous-matrix access.

Toolkit `HmdDeviceHooks::UpdateGaze` publishes the SAME calibrated wearable combined ray that direct CAPI reads; it additionally attaches a device-to-host timestamp offset to SteamVR's eye-tracking component. Swapping to the undocumented foveated packet as a supposedly better filter is not justified. CAPI exports inspected do not expose that IMU clock offset. v43 does not claim to have established a calibrated CAPI-to-XrTime mapping.

## Validation

Local C++20 geometry/gaze/frame/config/state tests and independent temporal world-point oracle pass. The new quaternion/homography oracle covers 20,000 deterministic randomized cases, asymmetric projections, 0.1/0.3/0.5/0.8/1.0 extents, both source selectors, pitch/yaw/roll including vertical head poses, same-origin preservation and head-turn/world-fixation pointing. It independently uses quaternion rotation rather than the production Euler-basis formula. Camera motion and homogeneous ray coordinates must agree.

Pinned production contract now verifies tracked gaze changes the real camera basis while the foveal projection stays unchanged. The pre-existing v42 regression still forbids previous-frame RGB displacement.

Pinned WARP production raster tests now run stationary full-world color patterns through BOTH legacy and steered geometry at multiple crop sizes/densities/gaze origins. Source pixels are generated independently from actual foveal camera rays, not by calling the shader homography. A separate source channel verifies high-resolution foveal pixels are used, rather than allowing a low-resolution periphery substitute to pass. Both eye copies must remain identical.

Local generated C++ review defers Windows HLSL compilation explicitly and never produces fake shader bytecode. Full strict source verifier, Windows CAPI, compiled HLSL/WARP, original Joey compatibility suite/backend/frontend and final ZIP/PE audit are mandatory in CI before providing a build.

## Publication and acceptance

User explicitly authorized autonomous work and publication after reviewing the exact v42 patch/destination. Repository ownership, public visibility and connected-account push/admin permissions were verified. Shell Git has no push credentials; the connected GitHub Git-object API successfully published v42 and started Actions run 38647538179. No credentials or restricted SDK source were included. The former approval blocker is resolved.

v43 must not be advertised as a bug-free or visually confirmed fix. This is one substantive renderer candidate designed to remove gaze-dependent projection-center motion while preserving real high-resolution rendering. Record exact CI SHA, package hash and actual headset observations separately.

## Additional CAPI correctness finding before release

Toolkit CAPI stores `g_lastGazeStatusCounter` once per DLL, not per caller. Its zero-timeout `getGazeStatus` path returns false for an unchanged shared counter but STILL copies the latest packet; that packet can also change between its two lock acquisitions. Thus a false API notification does not establish that this particular DuoView reader has already observed the payload.

v43 now determines freshness from a reader-owned `(raw.timestamp, raw.frame_counter)` sequence, after validating the packet header. Separate readers can accept the same new physical packet independently. Repeated payloads do not refresh their age, even if the shared API counter advances. Malformed signaled packets still invalidate the cache; new physical blink packets continue to clear it. The existing original mapped UV is retained for a repeated packet, avoiding reprojection with a different optical transform.

Pinned CAPI tests cover duplicate packets, two consumers, timestamp-only and counter-only updates, malformed headers and sensor counter/time restart. This is an independently source-backed missed-sample bug fix; no claim is made that it alone explained all observed shaking.

The local steering oracle also passed AddressSanitizer and UndefinedBehaviorSanitizer. Default LeakSanitizer cannot inspect this container's ptraced /proc state; the successful rerun disabled only leak detection and retained address/UB instrumentation. Do not count leak checking as passed.

OpenNR r10 source pin checked in this review: `1a6057eef550296a7aa7efa6295fa7ad46308fc8`.
