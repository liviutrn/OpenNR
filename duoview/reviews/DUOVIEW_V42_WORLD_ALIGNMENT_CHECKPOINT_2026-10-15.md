# DuoView v42: world-alignment regression repair, engine fix blocked

Date: 2026-10-15 Europe/Bucharest.
Branch: `experiments/duoview-gaze-correctness-v42`.
Base: v41 documentation HEAD `9608de226c8b9c6b19bdb086890e7d69e8f4c0f4`.
v41 CI code: `0da733a67d05571dd17600aeef2a0a6411b9354a`.

## Status

This is a correctness repair and engineering checkpoint. It does NOT fix the original pre-v41 eye-tracked shaking. No headset test candidate is recommended. No private UE previous-matrix writes or temporal hooks have been added. Runtime acceptance remains pending.

The user authorized autonomous implementation, validation and durable reporting. Preserve original Joey Build3, no smoothing workaround, no global NGX interception. No subagents were used.

## Independently verified findings

The attached v41 ZIP contains three Markdown files, not source/binaries. Actual sources were checked out separately. v41 Actions run 38636899230 has completed SUCCESS, including original compatibility tests, backend, frontend, final package and independent ZIP/PE checks. This supersedes the handoff's pending status; it is not headset acceptance.

Actual pinned Cheeky `src/crop_motion.hpp` at `4e47eefe51a512dcaf76bbdc672dcdab5251fc71` defines current-to-previous crop-local motion for temporal reconstruction. v41 instead added this displacement to sampling current, already reconstructed RGB in the final raster compositor.

For static world point full coordinate U, current origin O, extent E and legacy offset D=(O-Oprev)/E, the correct current source position is (U-O)/E. A compositor that samples local+D displays that point at U-E*D = U-(O-Oprev). Therefore it creates motion opposite the crop displacement even if the engine color is perfect. With 3000 output pixels and origin change +0.02, the added displacement is -60 output pixels (150 source pixels at 2.5 density and 0.30 extent). This is a counterexample to general stabilization correctness, not proof that the game output currently is perfect.

The prior WARP test expected the current image to shift by two texels; that test verified the wrong operation faithfully. It did not establish world alignment or validate Unreal temporal reconstruction.

## Changes

- Production State no longer computes final-color offsets from accepted XR history.
- CPU root constants force the legacy offset ABI to zero, even for externally constructed nonzero packets.
- Both raster and reference compute shaders ignore legacy displacement and sample current color at the current ROI's local coordinates. This is defense in depth against stale settings/packet producers.
- Remove the experimental final-image shift toggle and gain from production UI and persisted settings registration; generated configuration forces disabled values. Retain legacy struct fields and buffer shape to minimize unrelated ABI churn. They are not user-facing controls.
- Keep existing accepted-copy bookkeeping and pure legacy helper for regression evidence; do not treat XR acceptance as engine previous-history ownership.
- Pinned production contracts reject shifting current color even when legacy settings request it.
- Pinned production WARP verifies a nonzero legacy offset cannot move the final raster. Added independently encoded full-world red/green patterns for moving origins, 0.30/0.50 extents and 1.0/1.5/2.5 densities where geometry fits the atlas; verifies fixed output colors and identical eye copies.
- CPU world-point oracle now exercises the actual legacy helper and explicitly checks its 60-pixel output displacement counterexample.
- Generated-source verifier forbids reintroducing the final-RGB displacement wiring/UI. Existing source/SDK boundaries remain enforced.
- Workflow and package identify v42 as an engineering checkpoint, not a solved gaze build.

## Local verification

Linux has g++ but no cmake, Windows SDK or D3D12/WARP. The six CPU targets were compiled directly with g++ C++20, -O2, -UNDEBUG and pthread. Geometry, gaze, frame, config, state and temporal oracle all passed; the oracle exercised 17,280 deterministic randomized frame pairs. Python source compilation and git diff whitespace checks passed. This does not replace Windows CI.

## Actual source integration review

Pinned Joey backend remains `5ac7edc207866569334175e4ed8a7517971547f6`, matching frontend `60be4b0f9a646109fd9fdf448bacd41477234091`, SDK `3cffbc82429b6165ceec2714f0f0d9ae48f55596`.

Original `calculate_stereo_view_offset` source at lines 30377 onward places the DuoView capture anchor after all mod post-offset callbacks and output pose writes. The later controller update changes controller state, not those output pose references. Therefore a claim that the existing capture is necessarily before final pose writes is not established by this source. View1 reuses captured output rather than running a second pose update. Callback placement is not itself a validated Toolkit/XR clock match.

Original BeginRenderViewFamily publishes `runtime->internal_frame_count = frame_count` and then marks the main family; Draw uses internal_frame_count+1 for the next pose. DuoView predicts the same next engine frame for producer keys. D3D12 Mono consumes `vr->m_frame_count`, with source code explicitly distinguishing it from preceding Present's `m_render_frame_count`. These source conventions are consistent in the normal path, but there is no runtime trace proving the actual game render-target content and ROI packet have identical source frame identity under all auxiliary callbacks/repeats. No speculative frame-key change was made.

## Hard blocker for the original gaze fix

The pinned SDK's `FSceneView` exposes constructor address and Family discovery only. It does not expose previous view/projection matrices, temporal uniform buffer update or ClipToPrevClipOverride layout/accessors. The inspected current InitOptions projection update cannot by itself prove what TSR/DLSS and Lumen consume as previous state.

Official Epic current API documents ClipToPrevClipOverride, but this does NOT prove ABI or behavior for the user's exact STALKER 2 executable. Connected fetch of EpicGames/UnrealEngine at ref 5.5 for Renderer/Private/SceneRendering.cpp returned 404. Shell checkout of the restricted SDK lacks credentials; its exact source was readable through the connected GitHub tool, and existing Windows CI has the configured SDK source credential. Never expose/reuse CI secrets locally or substitute SDKs.

A safe production engine fix cannot be implemented from guessed offsets or this handoff alone. Missing evidence is the exact current/previous transforms, velocity convention, jitter and active temporal consumer in the actual game pipeline. Need either source/ABI-backed engine access plus game build validation, or one bounded runtime capture of that consumer. A purely color-stage correction cannot recover arbitrary temporal corruption, dynamic-object motion, depth disocclusion or spatially varying error.

## Next engineering steps

1. Inspect full v42 Windows CI and generated source/ZIP evidence; record exact source SHA and result below.
2. Keep v42 as the corrected engineering base, without recommending a headset test that merely repeats pre-v41 behavior.
3. Establish exact game/upscaler version and safe access to actual UE temporal consumer. Capture current/previous fovea projection, camera, viewport/jitter/history owner and source frame identity; distinguish actual data from expected math.
4. Repair only an evidenced mismatch at the real temporal consumer, once. If UE already includes the crop displacement, adding Cheeky's term again is incorrect.
5. Pair gaze and camera within a proven producer frame; only then add a tiny immediate fixation guard if needed. Preserve instant saccades.
6. Full pinned and original Windows tests, source verification and artifact audit before one meaningful headset candidate.

## Protected branch snapshot

Before v42 publication, `experiments/duoview-joey-current-clean-v1` is `c97c889f66835c4b3b155ea52127fbcd72610ba4`; v41 branch is `9608de226c8b9c6b19bdb086890e7d69e8f4c0f4`. v42 must not update either ref.

## Windows CI

NOT STARTED. Source repair commit: `abd18a5` (local).

Automatic approval review rejected `git push -u origin experiments/duoview-gaze-correctness-v42`, saying that autonomous implementation did not explicitly authorize publishing modified source to that GitHub destination. No alternate publishing tool or retry was attempted. Explicit approval to publish this isolated branch to `liviutrn/OpenNR` is required before Windows Actions can run.

Additional local validation after the source commit:

- Applied Stage1, Stage234 and native bootstrap patches to actual pinned Joey/ matching frontend local checkouts. Windows `embed_shader.py` invocation was explicitly deferred in a source-review-only wrapper; NO fake shader header or Windows binary was generated. This local tree is NOT a full CI-verified backend.
- Ran `audit_generated.py` against those generated public C++ sources. Source anchors passed; it explicitly reports actual previous projection UNOBSERVED.
- Compiled and passed `ProductionContractTests.cpp` against the generated production headers and patched Joey Mono policy using g++ C++20.
- Compiled that SAME updated production regression against the actual prior v41 State/Config/HistoryCorrection headers: it failed at "Accepted adjacent crop must not displace current color", as expected. Thus the new test detects the real v41 implementation flaw.
- Total local positive CPU executables: seven. Windows CAPI, WARP, full original compatibility, backend/frontend and final ZIP checks have NOT run for v42.

No v42 headset test is requested. The original UE temporal correction remains unimplemented until the actual consumer interface is validated. Publishing approval unblocks CI only; it does not by itself resolve that engineering blocker.
