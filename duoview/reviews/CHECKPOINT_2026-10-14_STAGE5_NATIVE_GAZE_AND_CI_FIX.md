# DuoView Mono / Joey — Stage 5 Gaze and CI hardening checkpoint
Date: 2026-10-14 Europe/Bucharest

**Stable control:** Build3 source SHA `64432d0442066715fa442660a0848cf4963640b0`, Actions `38453012351`, tested Mono ID5 30 minutes smooth.

**Experimental code:** `95b038bfe4288e0f6ac9b88503b5274aec083f3b` (subsequent docs-only branch head may differ). 
**Status:** Stage5 native eye-gaze implemented in source but NOT yet CI-verified as a whole and NOT headset-verified.


## 12. Stage 5 continuation — 2026-10-14; NEW SOURCE, Windows CI pending

**READ THIS BEFORE RESUMING.** The only confirmed headset-stable build remains **Joey Build 3**, run 38453012351, exact SHA `64432d0442066715fa442660a0848cf4963640b0`. Do not touch or overwrite it.

### New development status (verified GitHub writes)
- CI #12 run https://github.com/liviutrn/OpenNR/actions/runs/38474205084, source SHA `690fc4f1eb8c90fa73b2012a27157627cf53db53`, completed **FAILURE at package gate ONLY**. Pinned production tests **2/2**, independent **6/6**, original Joey **41/41**, backend `UEVRBackend.dll` and aux DLL builds, matching frontend test/publish all succeeded.
- Root cause: overstrict new package gate checked for `uevr.dll`, but the actual compiled backend DLL name (confirmed log) is `UEVRBackend.dll`. Exact fix commit `95b038bfe4288e0f6ac9b88503b5274aec083f3b`. No renderer edit needed for this CI error.
- First Stage5 CAPI reader and pure tests: `7e164419fa7fbfe995a917fc0f00977e3669dbb5`; integration commit `5148c1e2e422d9b11a91763a8b668fb4335d21b2`; PSO prewarm commit `5eb951f7db318653e9ec2bfef23fd48d5ed2bc5b`; gaze projection convention bugfix `3f5b0056a20bc37d4b1b97346c15516790fcdd01`; packaging fix `95b038bfe4288e0f6ac9b88503b5274aec083f3b`.
- **IMPORTANT SOURCE REVIEW BUG FIX**: Joey OpenXR runtime `src/mods/vr/runtimes/OpenXR.cpp::update_matrices` uses `Matrix4x4f { ..., [2][3] = +1, [3][2] = nearz }` in Mono mode, i.e. +Z-forward Unreal clip space. Initial Stage 5 UV projection used generic OpenXR -Z and would reject valid gaze. Source `duoview/DuoViewPSVR2Gaze.hpp` and its `ProductionPSVR2GazeTests.cpp` now project +Z forward; the new test uses `p[11] = +1` and rejects `p[11] = -1`. DO NOT UNDO.
- **Toolkit source confirmed**: `BnuuySolutions/PSVR2Toolkit/projects/common/hmd2_gaze.h` matches 0x148-byte status packet. CAPI exports `psvr2_toolkit_init` and `psvr2_toolkit_gaze_status`; fallback search uses already-loaded DLL, PSVR2TK_CAPI_PATH, native temp path file, Steam registry driver location, system lookup. Does not redistribute or modify Toolkit.
- **Gaze safety**: read once for each new production snapshot, reject packet size/magic, missing combined direction, blink, backward or non-finite vector; hold last valid ray max 50ms on no-new-frame status; invalid samples revoke old ray immediately. Project via Joey's **frozen shared LEFT Mono matrix**, put ROI into immutable State frame config, and use exactly that to modify UE fovea projection and DX12 composite. When CAPI is missing, fallback stays centered.
- **Frame key**: patch adds `duoview_producer_key()`, predicting UE next frame `internal_frame_count+1` during `UGameViewportClient::Draw`, while `BeginRenderViewFamily` later records its exact actual engine `frame_count`. This is source-informed by upstream `FFakeStereoRenderingHook.cpp` `update_hmd_state(true, internal_frame_count+1)`, but **still requires real STALKER2 headset validation**. If frame mismatches, the safe compositor gate will reject the pair and quarantine rather than submit stale GPU atlas contents.
- **D3D12 prewarm**: `DuoViewD3D12.hpp::Compositor::prewarm` is called for each DOUBLE_WIDE XR command context during `OpenXR::create_swapchains()` if ID6 DuoView is already active, using Joey's actual scene format SRGB flag. This avoids building descriptor/PSO/output in XR-copy callback *in that activation path*; first-use reconstruction may still occur if ID6 was activated without swapchain recreation, or source format differs. The production WARP test now executes prewarm before composition.
- **Interface**: rendering method ID6 now labeled `DuoView Mono (Eye Tracked - Experimental)` in both backend & frontend; ImGui reports `PSVR2 Toolkit active`, `CENTER fallback`, or `original Joey Mono fallback / inactive`. No extra settings and no eye tracking polling in modes ID0/ID5.

### Exact latest code head and work remaining
- Exact **code head** `95b038bfe4288e0f6ac9b88503b5274aec083f3b`. This handoff documentation commit may advance branch HEAD, but latest requested Windows source remains `95b038...` until a new code push.
- Windows CI Stage5 previous runs were queued or canceled as new commits arrived; check the actual run on `95b038...` via GitHub Actions. Do not substitute #12 artifact: #12 failed packaging, is not a release.
- Required complete Windows checks: pinned contracts + pinned CAPI test + pinned WARP; independent 6/6; original Joey 41/41; backend/aux DLL compile; frontend ID6 label consistency/publish; source whitelist/hash check; package manifests; actual artifact digest, completeness. Fix the *first* failure precisely and rerun.
- Runtime NOT VERIFIED: actual gaze-to-headset alignment, two UE views on same GPU source frame, Lumen/TAA seam quality, potential first-use PSO spikes, possible corrupt emergency fault atlas. Therefore never call the source 'stable' or ready to play based solely on CI. A green CI would allow a **controlled first headset test only**, keeping Build3 untouched.
- Avoid new architectures, full quadviews, mixing old Joey UEVR/SDK, or advancing to cosmetic settings now. Focus on one usable experimental binary and one strict rollback procedure.

## One-line restart prompt
Continue `liviutrn/OpenNR` DuoView from this file and `duoview/ACTIVE_HANDOFF_JOEY_FIXED_CENTER.md`. Verify the newest dedicated `duoview-joey-stage234.yml` workflow run for source SHA `95b038bfe4288e0f6ac9b88503b5274aec083f3b`, inspect ALL compiler and test logs, fix root causes, preserve Joey Build3 and do not call pending CI or untested gaze a success.
