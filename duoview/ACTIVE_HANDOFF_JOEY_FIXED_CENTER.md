# DuoView Mono / Joey UEVR — ACTIVE ENGINEERING HANDOFF AND RECOVERY LOG

**Checkpoint:** 2026-10-14, about 00:45 Europe/Bucharest (UTC+03).
**Project:** https://github.com/liviutrn/OpenNR
**Status:** Exact Joey baseline IN-HEADSET VERIFIED; Phase 1 CI PASSED; first fixed-center Stage 2–4 prototype CI PASSED; hardened Stage 2–4 candidate BUILD IN PROGRESS, NOT YET RELEASED.
**This is a recoverable engineering record, not a claim that DuoView is verified in-game.**

## 0. Instructions to the next ChatGPT / ChatGPT Work session

Do not restart from old mixed-version UEVR forks. Do not use reconstructed SDKs. Do not assume a successful Actions run proves DuoView works in STALKER 2. Continue from this document, the pinned branches and exact runs below; check the latest Actions run status and logs BEFORE modifying source.

**Immediate work order:**
1. Query https://github.com/liviutrn/OpenNR/actions/runs/38471717326, exact CI source SHA \`e27a61e076926b730af20f2914df9a978b404567\`.
2. Check job \`115552745015\` and all logs and artifact manifests. At checkpoint the job was **in_progress**; live job logs endpoint returned BlobNotFound, which is NOT evidence of failure.
3. If failed, identify FIRST failing step, obtain compilation/test output and fix source only after root-cause analysis. Every code change requires another isolated run and checkpoint.
4. If successful, distinguish passing original 41 tests, independent 6 tests and NEW pinned production contract + production WARP tests. Verify hashes, DLL/package presence and artifact provenance. CI success is not headset validation.
5. Inspect known caveats in section 7 before deciding if safe to ask Liviu to test. Do not label Stage 2–4 "stable" simply because all tests pass.
6. Keep branch \`experiments/duoview-joey-current-clean-v1\` and its Build 3 untouched. Do not overwrite its folder or replace it with the experiment.
7. Update THIS HANDOFF and, ideally, create a new dated immutable checkpoint in \`duoview/reviews/\` after important milestones. Include exact SHA, run/job IDs, failing log excerpt and resolution.

## 1. User goal and stability requirement

User plays STALKER 2 with SteamVR / PSVR2 on PC, using Joey's UEVR DIBR+Mono. The goal is **real DuoView Mono**, NOT native stereoscopy and NOT a postprocessing-only sharpness mask:

- One Unreal scene view covers the entire common Mono field at lower raster resolution (periphery).
- A second Unreal scene view renders a smaller off-axis subfrustum with much higher pixel density (fovea).
- Both use the EXACT same monoscopic camera pose, *not* the ordinary left/right physical eye separation.
- A DX12 compositor maps both into one CURRENT-FRAME, full-FOV monoscopic image, submitted to both eyes via Joey's established OpenXR projection/crop lifecycle.
- PSVR2 Toolkit eye tracking will move the fovea in **Stage 5**, **not** this milestone. Stage 2–4 deliberately fixes it at center.
- Primary priority: no freezes, 1–2 second SteamVR-room takeovers, missing XR frames, black screens, crashes, or regressions in Joey Native Stereo ID 0 / Mono ID 5.
- User does not want endless headset testing of speculative builds. Perform source review, Windows compilation, WARP execution and regression suite first. Communicate detailed progress and persist notes frequently because previous work chats have frozen.

## 2. Hard baseline — user verified, not inference

**Build 3:**
- Exact clean branch: \`experiments/duoview-joey-current-clean-v1\`
- GitHub Actions: https://github.com/liviutrn/OpenNR/actions/runs/38453012351
- Run source SHA: \`64432d0442066715fa442660a0848cf4963640b0\`
- Run completed **success**.
- Liviu explicitly tested the Build 3 **original Mono ID 5 for 30 minutes**, reporting **no hitches, no problems**. He reported no changes to STALKER 2, the runtime or Joey setup. This is our only confirmed 30-minute smooth current-source headset control.
- A later commit \`c97c889f66835c4b3b155ea52127fbcd72610ba4\` was the clean branch HEAD at feature-fork time; do NOT conflate this with the exact Build 3 build SHA.

**Source pins used throughout clean integration:**
- Joey backend: \`joeyhodge/UEVR\` @ \`5ac7edc207866569334175e4ed8a7517971547f6\`
- Original Epic-authorized Joey SDK: \`joeyhodge/UESDK\` @ \`3cffbc82429b6165ceec2714f0f0d9ae48f55596\`
- Matching frontend: \`joeyhodge/uevr-frontend\` @ \`60be4b0f9a646109fd9fdf448bacd41477234091\`
- The SDK is obtained in Windows Actions via an authorized secret; private SDK source is never copied into OpenNR.
- Source identity and SDK exact tree/completeness are checked before patching.

## 3. GitHub branch and run history (verified via API at checkpoint)

| Milestone | Branch and run | Source SHA | CI state | Headset evidence |
|---|---|---|---|---|
| Exact Joey Build 3, pristine Mono | \`experiments/duoview-joey-current-clean-v1\`, run \`38453012351\` | \`64432d0442066715fa442660a0848cf4963640b0\` | **success** | **30 min Mono ID5, smooth** |
| Stage 1 ID6 safe Mono fallback | \`experiments/duoview-joey-safe-stage1-v1\`, run \`38466584996\` | \`eaa051c41f8224c8dc5108a630415444d59e790b\` | **success** | not tested |
| First experimental actual two-view CI | \`experiments/duoview-joey-fixed-center-v1\`, run \`38469274838\` | \`47476bc32e37f128f0ce0b6348dcb8d712450eaf\` | **success** | not tested |
| Hardened two-view release candidate | \`experiments/duoview-joey-fixed-center-v1\`, run \`38471717326\` | \`e27a61e076926b730af20f2914df9a978b404567\` | **in_progress**, job \`115552745015\` | **not tested; no artifact as of checkpoint** |

Do NOT use the first two-view successful artifact \`38469274838\` as evidence that the later hardened candidate is green. That older CI passed **6/6 independent tests including WARP** and **41/41 original Joey tests**; matching frontend, backend/aux DLL compilation and source hash/package checks also succeeded. Verified prior successful run artifacts:
- old prototype (NOT release): \`Joey-DuoView-FixedCenter-Stage234-1\`, artifact ID \`11851599763\`, archive digest \`sha256:fb0509686fa7f7c90cb8772519b2d37c35f6b47f3391413684e35d5e1443b71c\`.
- old prototype evidence: \`Joey-DuoView-FixedCenter-Evidence-1\`, artifact ID \`11851833776\`.
- Stage 1 artifact \`Joey-DuoView-Stage1-MonoFallback-1\`, ID \`11851600377\`.

The newest feature branch code commit before this checkpoint document is \`e27a61e076926b730af20f2914df9a978b404567\`. Documentation commits will advance HEAD without changing the already-started run's pinned source SHA; always compare run SHA to code SHA, not blindly to mutable branch HEAD.

## 4. Current working integration files / architecture

The OpenNR repo has older historical \`duoview/\` experiments. **Do not assume those older script pipelines are active.** Current pinned Windows build applies these in strict order to three exact cloned upstream repositories:

1. \`duoview/clean_restart/verify_exact_baseline.py\` checks original upstream source/SDK and completeness.
2. \`duoview/joey_stage1/apply_stage1.py\` adds ID 6 "DuoView Mono" to mode selection, extending the existing Mono-family transition lifecycle. Stage 1 by itself is an original Mono fallback, NOT real foveation.
3. \`duoview/joey_stage1/verify_stage1.py\` checks original pins and allowed source modifications.
4. \`duoview/joey_stage1/apply_stage234.py\` injects actual fixed-center two-view hooks and DX12 compositor into the pinned Joey source.
5. \`duoview/joey_stage1/verify_stage234.py\` checks exact allowed path list, SDK unchanged and after-build hashes.
6. \`duoview/joey_stage1/ProductionContractTests.cpp\`, \`ProductionWarpPinned.cpp\` and \`CMakeLists.txt\`: tests against headers actually copied into the modified Joey build, including a DirectX12 WARP/debug-layer run.
7. \`.github/workflows/duoview-joey-stage234.yml\` defines Windows tests, compilation, packaging and evidence uploads.
8. Prior analysis: \`duoview/DUOVIEW_JOEY_INTEGRATION_CONTRACT_2026-10-13.md\` and \`duoview/reviews/JOEY_STAGE234_CODE_AUDIT_2026-10-13.md\`.

\`apply_stage234.py\` currently modifies:
- Joey \`src/mods/VR.hpp\`, \`src/mods/VR.cpp\` — mode-6 gating, frame snapshot, last-frame state, guarded fallback/quarantine, settings.
- Joey \`src/mods/vr/FFakeStereoRenderingHook.cpp\` — 2 Unreal view count for fixed-center ID6, adjusted rectangles, same-camera view offset, center crop projection, main view-family observation.
- Joey \`src/mods/vr/D3D12Component.hpp/.cpp\` — per-command-context compositor ownership, current-frame pair acceptance, compositor invocation before XR eye copies, fallback and reset cleanup.
- Joey frontend mode labels and mode tests.
- New modules copied into upstream tree from OpenNR: \`DuoViewGeometry.hpp\`, \`DuoViewGaze.hpp\`, \`DuoViewFrame.hpp\`, \`DuoViewConfig.hpp\`, \`DuoViewState.hpp\`, \`DuoViewD3D12.hpp\`, \`DuoViewMonoCopyD3D12.hpp\`, generated \`DuoViewShaderSource.hpp\`.

**Mode behavior:** ID 0 is original Native Stereo, ID 5 is original Mono, and ID 6 is experimental Mono-family mode. Active two-view path is gated on STALKER 2 executable + DX12 + OpenXR and the required view layout. A fault quarantines the two-view renderer inside ID 6, so subsequent frames route through normal Mono rather than switching rendering mode while the XR copy lock is held. Check this at runtime; it is designed behavior, not an already proven stability guarantee.

**Geometry:** immutable center fovea ROI of 0.30 x 0.30 full-FOV fraction, 2.5x linear pixel density; peripheral view 0.25x linear resolution. At a baseline 3000 x 3000 Mono reference, approximate view raster pixels are 2250 x 2250 fovea and 750 x 750 periphery, total 5.625 million or **62.5% of baseline Mono 9 million pixels**. This is a mathematical pixel budget ONLY; two UE scene views plus compositor and copies may be slower or have Lumen/temporal artifacts. The XR output remains full resolution. Eye tracking intentionally absent until Stage 5.

**Design observations:** Joey \`MonoRenderingPolicy.hpp\` defers mode changes until GPU consumer retirement and frame boundary. \`FFakeStereoRenderingHook.cpp\` handles one vs two scene views, view rects/pose/projection and view-family count. \`D3D12Component.cpp\` contains the trusted Mono-to-doublewide XR copies. A genuine current-frame pair must not be confused with native left/right stereo. The old mixed-public-backend DuoView renderer exhibited 1–2 s interruptions in all modes; its code is only reference material, NOT the integration base.

## 5. Validation evidence and release-gate checklist

**Passing first experimental two-view run (38469274838)**:
- Windows exact authorized SDK checkout, verified pinned sources, guarded patches.
- 6/6 independent geometry/state/gaze/frame/config/WARP tests passed.
- Original Joey compatibility suite 41/41 passed.
- Full backend and auxiliary DLL compile passed, matching .NET frontend published.
- Code whitelist + hashes passed; zip and SHA file uploaded.
- This is compiler/CPU/WARP evidence, NOT headset/performance proof.

**Latest hardened candidate (38471717326)**:
- As of this checkpoint the run was IN PROGRESS; GitHub had not published artifacts.
- New tests against actual copied production modules were added for geometry, frame generation and DX12 WARP debug layer, beyond the archived reference tests.
- DO NOT claim those new tests passed until the new run does.
- Once completed, examine every step and read logs rather than trusting only an overall green dot.
- Verify archive contains frontend, uevr backend DLLs, auxiliary DLLs, READ_FIRST, exact source evidence and package checksum. Verify its archive digest against GitHub.
- Inspect warnings and ensure no unexpected source paths/SDK changes.
- A failed run gets a new fix commit, a new CI run, and a new checkpoint. Do not distribute artifacts from earlier commits.

## 6. Progress update / persistence protocol

At each meaningful milestone (CI result, failing compilation test, root-cause analysis, safety code change, first headset result):
- Send a **detailed user-visible checkpoint** with (a) what changed, (b) evidence, (c) known concerns, (d) next step.
- Update this canonical \`duoview/ACTIVE_HANDOFF_JOEY_FIXED_CENTER.md\` with the latest status and an appended checkpoint history.
- For high-risk changes or before a long build, create an immutable dated \`duoview/reviews/CHECKPOINT_YYYY-MM-DD_*.md\` and link it.
- Include *exact* repo, branch, complete commit SHA, Actions run/job URL, pass/fail step, and whether build artifact is installable or NOT READY.
- Mark all claims as **in-headset verified**, **CI-verified**, **source-inspected**, or **proposed/unverified**.
- If chat freezes, open this file in a new Work chat and request: "Resume from the exact GitHub handoff, inspect latest Actions run logs, preserve Build 3, and do not skip the release gate."

This process preserves source and reasoning. It does NOT provide automatic background execution unless a separate scheduled task is deliberately configured.

## 7. Unresolved safety and performance hazards — READ BEFORE SHARING BUILD

1. **GPU producer completion vs CPU observation:** CPU callbacks/view-family count and per-frame packet checks are not an authoritative proof that both real UE views finished rendering. Actual graphics queue/frame resource ownership and compositing must be validated in STALKER 2 headset or GPU capture. Preserve frame identity and the copy-context fence requirements.
2. **One-time frame hitch potential:** \`DuoViewD3D12.hpp\` can lazily compile HLSL using \`D3DCompile\`, create root signature/PSO/texture/descriptor heaps during compositor \`record\` for each command slot or after a resize. WARP proving functional correctness does not prove no hitch. Prewarm/serialize away from critical render submission for a polished build; quantify if needed before allowing repeated headset tests.
3. **Fallback isn't necessarily visually seamless:** On an incomplete pair it attempts original Mono copy of current atlas before quarantining ID 6. That atlas may not contain a full-resolution, full-FOV single Mono scene, so a single corrupted recovery frame is possible. The next frame should go back to original Mono path; this is design intent requiring validation.
4. **Main-family eligibility:** Original Mono frame gate expects one UE view. ID6 allows a 2-view scene family, with a 1-view contingency to preserve current-frame recovery. Auxiliary families, projection history and post-present handling must remain correct. An OpenXR projection layer must never be intentionally skipped on uncertain evidence.
5. **Joey scope:** Original Joey 0/5 should not have functional code changes. This is supported by explicit ID6 guards and original CI tests, not by a fresh 30-minute headset regression test on the modified executable.
6. **Temporal consistency:** Two unequal-view Unreal passes may not share compatible TAA/Lumen history/exposure/shadows. Center seam or mismatched lighting remains an unmeasured issue.
7. **Actual speedup unknown:** 62.5% scene-pixel budget is not frame-time, performance uplift or foveal PPD verified in headset. Additional scene-view CPU work, lighting/shadow passes, compositor cost and resource stalls could dominate.
8. **Shader color/format assumptions:** DX12 reference compositor and copies support selected output formats; should fail closed for unsupported formats and not silently assume all STALKER 2 HDR modes work.
9. **Packaging README stale:** The current \`.github/workflows/duoview-joey-stage234.yml\` static \`READ_FIRST.txt\` text says faults "request original Mono ID5", whereas the hardened source uses **internal ID6 quarantine**. Before final release correct the documentation, without changing code semantics accidentally. This discrepancy is known, not a validated functional failure.
10. **Test limitations:** Even complete CI green does not prove the exact headset/game runtime branch is reached, or profile/SteamVR injection works. Keep the tested clean rollback available.
11. **First-use allocation:** Per-command-slot \`unordered_map\` and compositor resource construction mean the first use can allocate on render-critical path. Review before calling it free of performance hogs.
12. **No eye tracking yet:** Do not confuse centered DuoView with final eye-tracked DuoView; diagnostics must not claim gaze active.

## 8. Testing and rollback (ONLY after final candidate is audited)

Install candidate into an **entirely separate folder**, keep original Build 3. Test first normal ID5 with same SteamVR/game settings, then switch to ID6 fixed center and confirm center vs periphery spatial detail. Watch CPU/GPU frametimes and SteamVR room takeovers while moving and during a scene change. ID6 fixed center does not use PSVR2 gaze. If any visual corruption/hitch/black screen/crash or missing projection frames, stop, return to the original Build 3 folder, and collect logs. Do not treat a user crash as permission to test many speculative builds.

## 9. Exact one-message restart instruction

> Continue my DuoView Mono UEVR STALKER 2 project. First read \`duoview/ACTIVE_HANDOFF_JOEY_FIXED_CENTER.md\` in \`liviutrn/OpenNR\` and the engineering audit in \`duoview/reviews/\`. The only headset-proven baseline is Joey Build 3 run \`38453012351\`, smooth Mono ID5 for 30 minutes. Latest hardened Stage 2–4 CI run at handoff was \`38471717326\` on commit \`e27a61e076926b730af20f2914df9a978b404567\`; verify its actual result before making changes. Keep the exact Joey backend/SDK/frontend pins, don't substitute older mixed-source code. Inspect all tests and log warnings, assess GPU/compositor/fallback hazards and create a safe installable fixed-center build only after it passes. Update the GitHub handoff on every meaningful checkpoint.

## 10. Checkpoint timeline

- 2026-10-13: user verified original Joey Build 3 Mono for 30 smooth minutes; no setup changes.
- 2026-10-13: Stage1 ID6 safe fallback ran successfully in CI.
- 2026-10-13: first fixed-center Stage2–4 run \`38469274838\` passed 6 independent + 41 original tests and packaging.
- 2026-10-13: safety changes to avoid mode-switch-in-XR-copy lock; added internal ID6 quarantine and 1-view recovery gate. New actual patched-production contract/WARP tests.
- 2026-10-14 ~00:45 local: latest hardened run \`38471717326\` still in progress; no verified latest artifact; saved this handoff.


## 11. Verified continuation checkpoint — 2026-10-14, 00:55 Europe/Bucharest

**Operator:** next ChatGPT session continuing previous handoff. **Confidence:** GitHub API confirmed the job result and source commits; real STALKER 2 headset rendering remains untested.

### CI for the previously running hardened candidate #11 FINISHED SUCCESS
- Run: https://github.com/liviutrn/OpenNR/actions/runs/38471717326
- Exact source commit: `e27a61e076926b730af20f2914df9a978b404567`
- Job: `115552745015`, **completed / success**.
- Pinned production contracts **2/2** passed, including the DX12 WARP production-header test.
- Independent DuoView tests **6/6** passed.
- Original Joey compatibility tests **41/41** passed.
- Backend and auxiliary DLL builds, matching frontend build, exact-source checks and artifact upload succeeded.
- Downloadable CI artifact (UNVERIFIED IN HEADSET): `Joey-DuoView-FixedCenter-Stage234-11`, artifact ID `11852692716`, GitHub artifact archive SHA-256 `615b685e0a4a555fc9e6becfe990be6858e0c1feea42ace7b95a9329c4a75c9b`.
- Evidence artifact `Joey-DuoView-FixedCenter-Evidence-11`, ID `11853391081`, archive SHA-256 `bdef304c57e4086f745e9322ce5ad2a006d057bb767a1037d72821fc741610c7`.
- The WARP test validated output pixels and same-image-to-both-eyes copying after a GPU fence. This does NOT establish that real STALKER 2 UE producer views finish in the correct ordering.
- Known warnings include unrelated original SDK/compiler warnings, EOL net6 frontend notices, Node deprecation and CMake deprecation. They were not CI failures.

### Post-#11 review conclusions
- The header `duoview/DuoViewD3D12.hpp` called `D3DCompile` from `Compositor::prepare()`, which is reached from XR-copy `record()` on first slot use and resize. This is a confirmed avoidable *shader compilation* hitch risk.
- `prepare()` still lazily allocates per-slot textures/heaps and creates PSO/root signature, which can impose first-use costs even after shader compilation is moved offline.
- Fallback quarantines mode ID6 internally rather than automatically selecting ID5. An incomplete packed atlas can cause a corrupt fault frame before next-frame original Mono resumes. Do not claim seamless fallback.
- CPU view-family/camera/rect/projection observations are not GPU producer-completion fences; stable headset behavior and temporal/Lumen agreement remain unproven.
- The package READ_FIRST for #11 mistakenly states failure "requests original Mono ID5", while actual behavior is internal ID6 quarantine. Corrected for next candidate.

### New atomic hardening commit and CI #12
- Source commit: `690fc4f1eb8c90fa73b2012a27157627cf53db53`.
- Exactly five changed files: `duoview/embed_shader.py`, `duoview/DuoViewD3D12.hpp`, `duoview/joey_stage1/apply_stage234.py`, `duoview/joey_stage1/verify_stage234.py`, `.github/workflows/duoview-joey-stage234.yml`.
- Windows SDK `fxc.exe` compiles VSMain and PSMain to DXBC in the build; a generated `DuoViewShaderSource.hpp` contains immutable bytecode arrays. Production compositor now points PSO descriptors at bytecode, never calls `D3DCompile` in live XR submission.
- Verification rejects any production compositor that still references runtime `D3DCompile` or lacks both bytecode arrays. The WARP production test compiles against the exact generated production header and will exercise both shaders.
- Package gate now checks original UEVR backend, frontend EXE, auxiliary DLLs, source hashes, and correct quarantine wording.
- Crucially this changes neither fixed geometry nor original Joey mode ID0/ID5 behavior. The restricted SDK pin remains exact and unmodified.
- New CI run: https://github.com/liviutrn/OpenNR/actions/runs/38474205084, job `115560745811`. **Status at checkpoint: IN PROGRESS.** Do NOT claim #12 passed or hand out #12 until it completes successfully. Examine the first failing build step if compilation fails (the new SDK fxc availability and HLSL compiler compatibility are unverified until this run finishes).
- Other OpenNR repository workflows triggered by the push may fail independently; evaluate the **dedicated** DuoView workflow on its own merits, not global red/green badges.

### Mandatory next actions
1. Check run `38474205084` job `115560745811`, read complete logs after completion and confirm all **2 pinned + 6 independent + 41 original Joey tests**, SDK verification, frontend/back-end compilation and package integrity.
2. If failed, fix the FIRST root cause and trigger another isolated CI run. Never fall back silently to shader compilation on an XR frame.
3. If successful, inspect artifact manifest, downloadable ZIP and content hashes. Treat as **headset-unverified experimental candidate** only. PSO/texture allocation can still hitch on first use, and incomplete-atlas fallback is not seamless.
4. Avoid submitting Stage 5 gaze changes before fixed-center behavior and initial frame pacing are established. Do not alter the original working Build 3.
5. Preserve exactly the stable Build 3: branch `experiments/duoview-joey-current-clean-v1`, run `38453012351`, build SHA `64432d0442066715fa442660a0848cf4963640b0`, 30-min verified Mono ID5.


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


### Stage5 final-candidate CI queued (after latest audit)
- Code changes through `95b038bfe4288e0f6ac9b88503b5274aec083f3b`, followed by CI-only commit `9ae1a97a90b522ab6d20575f3c1db505d8063c03` changing `cancel-in-progress` from false to true. No additional renderer source change.
- **Authoritative latest Windows CI** https://github.com/liviutrn/OpenNR/actions/runs/38477236745 ; source SHA `9ae1a97a90b522ab6d20575f3c1db505d8063c03`.
- At checkpoint run `38477236745` **PENDING**, with **ZERO artifacts** and no completed Stage5 compilation/test evidence. Earlier run `38476778406` got cancelled as obsolete; run `38476528278` on uncorrected gaze projection was still in progress.
- Nothing should be distributed as a validated Stage5 package until the latest CI job is COMPLETED success, all pinned PSVR2-gaze+WARP tests and original 41 tests pass, and downloadable artifact ID + sha256 exist. The older successful run #11 is fixed-center **without** eye tracking and does not satisfy the request.
- A specifically targeted hourly condition-check task was configured to inspect this run and later runs, inspect complete build logs, publish a grounded result and update the handoff only upon meaningful new events. Whether platform notifications are shown depends on notification settings.
- A source-only CAPI test/CI is NOT a real eye-tracking, frame synchronization, or STALKER2 VR test. Only a user headset run can establish those.
