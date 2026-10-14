# Stage 5 — projection contract recovery checkpoint (2026-10-14)

## Scope and hard baseline
- Repository: https://github.com/liviutrn/OpenNR
- Feature branch: `experiments/duoview-joey-fixed-center-v1`
- Original Joey baseline **untouched**: `experiments/duoview-joey-current-clean-v1`, original headset-proven Build 3 https://github.com/liviutrn/OpenNR/actions/runs/38453012351 at `64432d0442066715fa442660a0848cf4963640b0`; user's 30-minute Mono ID5 STALKER2 test without hitches.
- Feature development source is still exact pinned Joey UEVR `5ac7edc207866569334175e4ed8a7517971547f6`, authorized SDK `3cffbc82429b6165ceec2714f0f0d9ae48f55596`, and frontend `60be4b0f9a646109fd9fdf448bacd41477234091`. The source application pipeline verifies these identities during Windows CI.

## Independently verified failure
- Failed run: https://github.com/liviutrn/OpenNR/actions/runs/38477236745
- Run source: `9ae1a97a90b522ab6d20575f3c1db505d8063c03`; failed job `115571423806`.
- Exact first failed step: **Verify pinned production geometry and pair-state contracts**.
- CTest: **pinned-duoview-frame-and-layout PASS**, **pinned-psvr2-capi-projection-and-validation FAIL** (`asymmetric Mono optical projection`), **pinned-duoview-dx12-warp PASS**. 2 of 3 pinned tests passed. Remaining six independent tests, 41 Joey compatibility tests, full backend, frontend and installable packaging were skipped. The evidence-only artifact `11853933257` is NOT an installable build.
- Old fixture `duoview/joey_stage1/ProductionPSVR2GazeTests.cpp` set `p[0]=1,p[5]=1,p[11]=1,p[8]=+0.2`, used forward ray `{0,0,1}`, and asserted U=0.4. The production implementation returns U=0.6.

## Independent projection convention check
- Pinned Joey `src/mods/vr/runtimes/OpenXR.cpp::update_matrices` in Mono mode constructs a GLM `Matrix4x4f` with column-major indexing `matrix[column][row]`: `p[0]=1/horizontal, p[5]=1/vertical, p[11]=+1, p[14]=nearz`; the common Mono projection is +Z-forward.
- `VR::duoview_begin_frame` copies the 16 floats via `std::memcpy(frozen.data(), &projection[0][0], sizeof(frozen))`, preserving that storage order.
- `psvr2::projection_uv` correctly computes `x_clip=p[0]*right+p[4]*up+p[8]*forward`; `w_clip=p[3]*right+p[7]*up+p[11]*forward`; `u=(x_clip/w_clip+1)/2`.
- Thus for forward ray and `p[8]=+0.2`, `u=(0.2/1+1)/2=0.6`; with `p[8]=-0.2`, `u=0.4`. A positive `p[9]=0.1` maps a straight-ahead ray to `v=0.45`. For ray `{0.5,-0.25,1}` plus `p[8]=0.2,p[9]=0.1`, `u=0.85,v=0.575`. The old fixture's 0.4 assertion had the sign reversed. Note Joey Mono's actual generated common projection is symmetric (p[8]=0), so synthetic asymmetry is still useful regression coverage rather than evidence that runtime uses asymmetric Mono.
- `DuoViewGeometry.hpp::apply_foveal_crop` uses the same column-major GLM access convention; no production sign fix is required by this failed assertion.

## Targeted fix and CI
- Only modified `duoview/joey_stage1/ProductionPSVR2GazeTests.cpp`, correcting U to 0.6 and adding **negative asymmetric**, **combined horizontal+vertical**, and **off-axis ray** regression assertions. Production gaze, geometry, state, shaders, compositor, injected hooks, SDK and Joey modes ID0/ID5 are unchanged.
- Fix commit: https://github.com/liviutrn/OpenNR/commit/ce9c9abc67ec0dafa48634ae7a3a443377616de5
- Automatically triggered dedicated Windows run: https://github.com/liviutrn/OpenNR/actions/runs/38525471273, exact source SHA `ce9c9abc67ec0dafa48634ae7a3a443377616de5`, workflow number #19; **in progress at this checkpoint, NOT PASSED**.
- Unrelated legacy OpenNR workflows also run automatically and may fail; they are not the dedicated Stage5 release gate.

## Required completion evidence (NOT YET OBTAINED)
1. Inspect all pinned production tests, independent 6, original Joey 41, DX12 WARP, compiler/linker, exact proprietary SDK pin, frontend ID6 label, provenance and packaging steps from the full Windows job logs.
2. Obtain installable artifact ID, download the artifact ZIP, inspect the nested package and manifest, compare claimed SHA256 with independently computed hash, verify all DLLs/frontend EXE and checkout commit.
3. Review interaction and performance risks: same-frame UE producer/consumer GPU synchronization not proved by CPU state flags; fault atlas can be incomplete; first-use PSO/resource initialization could hitch depending on activation; gaze +Z source basis and per-eye consistency still headset-unverified; TAA/Lumen history, input and frame pacing need user testing.
4. Only distribute a green-CI, fully checked package as **HEADSET-UNVERIFIED EXPERIMENTAL**. Full release still requires user acceptance gates B-D against original Joey Build 3.

**Release gate A status at checkpoint: PENDING. No Stage5 installable artifact has been verified.**
