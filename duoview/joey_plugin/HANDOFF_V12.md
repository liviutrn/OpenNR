# DuoView owned-copy v12 engineering handoff

This revision is an active rendering integration candidate. Build49 intentionally disabled rendering; v12 instead observes a real native baseline copy and XR submission before arming cropped producers. STALKER 2 headset behavior, gaze alignment, FPS and PPD remain untested by the engineer.

Liviu's older modified backend delivered excellent foveal quality, approximately 50 PPD at normal FPS, and working gaze tracking, but hitched in all modes. Preserve those successes. Original Joey Mono is the smooth baseline.

## Binary correction

Original backend SHA-256: 19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966. It remains byte-identical.

The Build49 handoff misidentified RVA 0x1c4280 as D3D12 OpenXR copy. It is D3D11, with a different callback ABI. Both implementations reference the same diagnostic string. The actual D3D12 copy is 0x1e4770, unwind end 0x1e5ac2, called from on_frame 0x1f0f50, including callsite 0x1f83f5. Its mutex is this+0x170. The verifier checks optional callback flags, source-state stack operand, actual CommandContext::execute target and the DX12 caller. See RELEASED_JOEY_COPY_BOUNDARY_AUDIT.md.

JoeyCopyABI.hpp uses the full typed signature, including by-value optional std::function and shared_ptr, and the exact public embedded-commit CommandContext header at 5ac7edc207866569334175e4ed8a7517971547f6. The Windows separate-DLL fixture exercises engaged/empty callbacks, non-null aliasing shared_ptr, field-layout assertions, forwarding and destruction.

## Production path

1. Hash/loaded-entry checks and HLSL compilation precede hooks. Original Native Stereo producers remain intact during observation.
2. Actual selected scene source/state and acquired destination come from the copy boundary and callback. No guessed StereoHook source and no engine atlas overwrite.
3. Four Mono output slots prewarm before modified producers. A full native snapshot with its exact submitted eye metadata supplies initial fallback. A real copy/fence proof and successful scene xrEndFrame are required before arming a subsequent producer.
4. Reserve a retired non-held slot before changing any view. Busy slots leave the entire producer native. Freeze rectangle/projection/camera/gaze together. Match the UE family producer number to Joey's verified RHI consumer counter.
5. The actual on_frame call scope correlates copy and submission. Original copy receives null source and a callback that samples the selected scene, draws into an owned Mono output, then duplicates it into the acquired XR destination in Joey's actual CommandContext. No additional scene pass or separate plugin command allocator/CPU fence wait.
6. Copy proof requires recorded commands, valid destination/device/extents, original success, an advanced fence, waiting_for_fence and non-poisoned context. Resources/descriptors remain retained until the consuming fence retires. Accepted images remain held until replaced.
7. Submission uses the copied producer's actual optical pose; current presentation time remains Joey's xrEndFrame time. Locate time is never equated to submit time. A held image retains its original pose.
8. Missing/incomplete/mismatched modified producers use a coherent held image and stop subsequent modifications. A failed new copy gets one verified hold replay attempt. Actual XR/device failures cannot manufacture valid pixels; an unproved scene is not published. Reset retires old GPU objects and optical/hold generations.

## Other fixes

- Production no longer calls record_atlas_replacement or publishes before original_frame.
- Every production compositor is prewarmed; no shader/PSO setup during modified producer frames.
- Opposite-sign equivalent eye quaternions no longer appear 360 degrees apart.
- Removed invalid raw D3D12 BeginEvent marker discovered by debug-layer validation.
- Slots retain only owned Mono output, avoiding active double-wide staging allocations and their extra copy. Four 3000x3000 BGRA Mono slots total about 144 MB decimal, plus an initial 72 MB native snapshot. The snapshot is freed after its held slot retires. Driver allocations and retained source references are additional.
- Lua sandbox fs and combined-settings validation retained. Settings require restart. Mode1 diagnostic is retired; use Mode2 fixed or Mode3 gaze.

## Validation boundaries

Windows workflow runs eleven CTest checks: geometry, gaze, frame, config, state, submission, activation, optics, copy-flow, copy-abi and production-warp. WARP enables D3D12 debug layer, tests a non-RT source in SRVMask, owned compositing/copy, moved gaze, fence reuse, exact paired pixel readback, and fails on stored D3D12 error/corruption messages.

The ABI fixture is a compatible test implementation, not the released function in a live VR session. Copy-flow checks production decision/proof helpers, not every native hook. WARP does not execute Unreal. Eight portable checks were recompiled/run locally with g++. Windows additionally checks the pinned backend, restricted Lua simulation, isolated installer, DLL loading and exports.

Exact compiled source and Actions URL are generated into BUILD_SOURCE.txt. HASHES.txt records packaged file hashes. Do not describe compilation, an accepted xrEndFrame or a loaded UI alone as proof of working headset visuals.

## One initial headset acceptance

Install Mode2 defaults: 50% crop, density1, debug border on. Use OpenXR and Native Stereo ID0, Native Fix and compatibility modes off. Expect a centered detailed fovea with a thin orange feather border over softer full-field periphery, coherent Mono in both eyes. Pairing, composites and XR acceptance must advance together. Head movement must preserve the scene. Persistent observing/fallback with zero composites is an integration failure. Test gaze and measure performance only after fixed-fovea acceptance.

## Limits

Direct BGRA8 double-wide Native Stereo scene copying is supported. Native Fix callback paths, arrays/AFR, incompatible format/extent and conflicting hooks are refused or returned to original rendering. Exact-release internal view hooks remain version-specific.

Default density1 reduces nominal scene pixels without increasing central PPD. UE full-atlas/post-process costs and output sampling limits remain. Higher density/output resolution needs separate evaluation against original Joey Mono.

Logical misses have a coherent hold; irrecoverable XR/device faults may require a restart. No offline test guarantees valid output after hardware/runtime refusal.
