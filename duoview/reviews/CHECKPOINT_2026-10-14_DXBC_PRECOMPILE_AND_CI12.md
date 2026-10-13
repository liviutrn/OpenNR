# DuoView Mono — Recoverable engineering checkpoint
**Date:** 2026-10-14 Europe/Bucharest
**Status:** Stage 2–4 hardened CI #11 successful; new offline DXBC compilation candidate #12 awaiting full Windows build; no game/headset test of either experimental candidate.


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

## Verification categories
- **Headset verified**: Only original clean Joey Build 3 Mono ID5 smooth for 30 minutes, as user reported.
- **CI verified**: fixed-center CI #11 success, 2 + 6 + 41 tests and artifacts.
- **Source inspected, not runtime proven**: Two UE view patches, same-pose frame packet, DX12 composition and internal quarantine, modified source #12.
- **Pending**: CI #12 result, DXBC bytecode validity in exact patched build, first-use PSO/heap/frame-time safety, real GPU producer ordering and seam quality.

## Next-session restart
Read `duoview/ACTIVE_HANDOFF_JOEY_FIXED_CENTER.md` and this checkpoint in `liviutrn/OpenNR`. Check CI #12 before any source writes. Do not touch Build3. Do not call CI green "headset stable." Do not use old mixed-version UEVR prototypes.
