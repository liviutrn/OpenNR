# DuoView Joey fixed-center integration — engineering audit
Date: 2026-10-13
Branch: experiments/duoview-joey-fixed-center-v1
Reference control: Build 3, Windows run 38453012351, original Mono ID 5.
User headset evidence: 30 minutes STALKER 2 / Mono ID 5, no hitches, no problems, no setup changes.

## Immutable source pins
- Joey UEVR backend: 5ac7edc207866569334175e4ed8a7517971547f6
- Original authorized Joey UESDK: 3cffbc82429b6165ceec2714f0f0d9ae48f55596
- Matching Joey frontend: 60be4b0f9a646109fd9fdf448bacd41477234091
- OpenNR staging branch derives from exact baseline branch commit c97c889f66835c4b3b155ea52127fbcd72610ba4
- No private SDK contents checked into OpenNR; Actions uses existing authorized SDK credential

## Renderer implementation (experimental until headset verified)
Mode 0 Native Stereo and mode 5 Mono still use the original Joey rendering code.
Mode 6 uses the original Mono transition protocol and same XR doublewide submit.
For STALKER 2 DX12/OpenXR ONLY, mode 6 now requests 2 engine views:
- UE view 0 = full-frustum periphery, centered Mono camera, 0.25x linear resolution
- UE view 1 = cropped off-axis fixed-center fovea, same exact final Mono camera, 0.30 x 0.30 crop, 2.5x output density
- Render rectangles are disjoint within the existing doublewide scene atlas.
- Per-frame source snapshot freezes geometry/config and rejects different generations/frames and mismatching camera poses.
- DX12 raster compositor samples the scene atlas once, resamples to full-size Mono, then copies same composited image into both XR eye halves. Scene source/target states are transitioned/restored.
- Missing/invalid paired-view evidence or failed compositor GPU recording uses the existing current-frame original Mono copy and quarantines DuoView internally. ID 6 remains selected but subsequently executes the original single-view Mono renderer until the user explicitly switches away and back. This avoids an automatic mode-change quiescence/dropout during a bad GPU frame. It does not deliberately omit the XR projection layer.
- Gaze is NOT active. Crop is fixed center. No smoothing or temporal reuse.

## Safety / regression boundaries
The view-count, view-rect, projection, camera, and compositor branches are active only under mode 6 + STALKER 2 + DX12 + OpenXR.
The original mode 5 camera, projection, one-view render count, copy, and OpenXR submission are not deliberately modified.
Mode transitions reuse the already 30-minute-proven Joey deferred-retirement/generation protocol.
The DuoView fault quarantine happens AFTER the OpenXR copy callback; it does not take the rendering-method selection lock inside the XR copy lock. The next frame uses original Joey Mono while preserving a valid XR projection.
Unmatched packets cannot be composited; the last-resort original Mono copy attempts to preserve a projection frame.
All shader resources use a bounded per-OpenXR-command-slot map and clear when swapchains are reset or destroyed.

## Remaining honest limitations
1. A source/Windows-CI test cannot prove that both Unreal scene views execute their intended actual STALKER 2 GPU shading pass, nor prove temporal/Lumen compatibility.
2. The DX12 compositor creates PSOs and output textures lazily on first encounter of each command slot. It reuses them thereafter, but first activation/resize could have a one-time initialization spike. This needs prewarming before a polished release.
3. The CPU main-family and view-callback checks are not an independent GPU producer-completion proof. Correct same-queue ordering and Joey's existing copy fence remain assumptions that require an in-game GPU capture or headset evidence.
4. If geometry/pair evidence fails, one emergency original-Mono copy may briefly show an incomplete atlas; it is intentionally not treated as a valid DuoView composite. The code then quarantines the two-view renderer and executes original Joey Mono on the next frame without automatically switching rendering IDs. This is safer than repeatedly attempting uncertain GPU work but is not equivalent to a proven seamless fallback.
5. Independent production WARP tests verify the compositor algorithm and exact stereo output; original Joey compatibility tests verify legacy policies. Neither measures GPU frame time or real STALKER 2 performance.
6. A calculated 62.5% of original Mono view pixels is NOT a demonstrated GPU-time speedup: two Unreal scene families/passes, shadows/Lumen, composition and copies introduce overhead.
7. CI green cannot replace the user's 10–15 minute headset validation and scene-change test. Do not call this "stable" before that test.

## Windows CI release gate
- Exact source SDK verification (as successful Build 3).
- Guarded Stage 1 + Stage 2/3/4 source application.
- Separate pinned production geometry/packet-state tests against actual patched headers.
- Independent C++ geometry/state and DX12 WARP shader compositing tests.
- Original 41 compatibility tests.
- Matching frontend ID tests and full frontend publishing.
- Full original Joey backend and auxiliary DLL compilation.
- Final source diff whitelist and hashes, ZIP hash, artifact upload.
- Inspect every failure and artifact before downloading or claiming validation.

## Suggested first headset test ONLY after CI passes
1. Extract into its own folder; do not overwrite Build 3 or official Joey.
2. Launch STALKER 2 with same SteamVR/PSVR2 Toolkit/runtime and resolution as the clean 30-minute control.
3. Verify ID 5 loads normally, then select ID 6 fixed-center experimental. Do not expect gaze yet.
4. In a fixed scene compare fovea/peripheral actual detail, and record fpsVR GPU+CPU frametime. The central crop should be sharp; periphery deliberately coarse.
5. Move head, look around, try a level change. Check for missing frames, room takeovers, crashes, black views, and whether ID 6 internally quarantines to Mono and shows its fallback status.
6. If any issue, revert immediately to Build 3 folder and include UEVR logs. Do not interpret a compile success as stable runtime behavior.
