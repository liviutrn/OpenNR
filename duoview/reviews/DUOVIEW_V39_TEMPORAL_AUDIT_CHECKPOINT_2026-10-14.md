# DuoView v39 — Gaze Temporal Audit Checkpoint (2026-10-14)

**Status: NOT A GAZE FIX; DO NOT SHIP.** This report records durable verified work and explicit blockers. It is not a headset build acceptance.

## Provenance and protected baselines
- Repo: `liviutrn/OpenNR`; isolated development branch: `experiments/duoview-gaze-temporal-audit-v39`.
- Branch started from Build37 HEAD `c43bd57a988241d529f9ba75ea147d960fd330d8`, CI source `d82480ff784dd7c89ba533853e1cfe14ccfab3a2`.
- Build37 passing Windows Actions run: `38623649137`, original full build; **gaze/startup remain headset unverified**.
- Build3 original Joey MonoID5 passed user's 30-minute headset test, is not modified here. Baseline pins remain backend `5ac7edc207866569334175e4ed8a7517971547f6`, SDK `3cffbc82429b6165ceec2714f0f0d9ae48f55596`, frontend `60be4b0f9a646109fd9fdf448bacd41477234091`.
- v38 branch `experiments/duoview-gaze-pose-latched-v38` is NOT used; verifier mismatch and callback-order assumptions unproven.
- This branch keeps the Build37 two-view atlas and preserves the untouched original Joey source pins. **Do not promote this branch to release.**

## SOURCE VERIFIED findings
1. `DuoViewState.hpp::TemporalAudit` calculated pure crop current-to-previous motion with **reversed origin-delta sign**: oldOrigin−currentOrigin. Correct equation is `fw*(currentOrigin−previousOrigin)/cropExtent` for current→previous crop-local motion. Corrected in v39 with matching pinned contract assertion. This fixes a diagnostic **only**, not rendered image motion.
2. `State::consume()` assigns `last_completed_` **before** `D3D12Component::record` completes and before XR-copy successful submission is confirmed. Consequently `last_completed_` is a CPU *eligible/consumed* packet, **not a proven successful UE temporal-history update**. Do not use it to write previous matrices.
3. `apply_stage234.py` synchronizes current `FSceneViewInitOptions` projection; it explicitly does **not** repair private previous UE temporal state. Thus existing `TemporalAudit` cannot prove prior TSR/velocity/DLSS projection correctness.
4. `DuoViewPSVR2Gaze.hpp::Reader` returns cached optical UV up to 50ms. Toolkit frame counter and raw timestamp exist in ABI but are **not** correlated to the actual predicted head pose. False/no-new CAPI retains coordinate; invalid/blink clears it.
5. Current `CropStability` bypasses all older smoothing and guard values; valid raw gaze is immediate, fixed-center remains a control.
6. Original pinned UESDK `src/sdk/FSceneView.hpp` exposes typed current `FSceneViewInitOptionsUE5` projection and `FSceneViewStateInterface*` identity, **but no validated public API for the actual previous projection consumed by STALKER 2 temporal renderer**. Guessing a private prev-matrix offset is explicitly forbidden.
7. Cheeky pinned `src/crop_motion.hpp` defines `currentOrigin−previousOrigin` after unit scaling for NGX current→previous vectors. OpenNR r10 `GazeCropPolicy.h` exempts >2 output-pixel displacements from tiny fixation filtering. Neither validates a global NGX hook in UEVR.
8. STALKER 2's publicly documented Patch 2.0 (August 2026) migrated its engine from UE5.1 to UE5.5.4. **The exact installed executable's engine and temporal/upscaler setting remain unmeasured.** Cross-check STALKER public official Zone Kit 2.0 announcement / August 2026 performance coverage and actual executable at runtime.

## Changes committed to v39
- `duoview/DuoViewState.hpp`: fixes diagnostic expected crop vector sign, annotates lack of proof about UE consumer.
- `duoview/joey_stage1/ProductionContractTests.cpp`: regression expects positive source pixel motion for rightward ROI.
- `duoview/tests/FovealTemporalOracle.cpp`: independent reference from full world-point perspective and separately composed **production** `apply_foveal_crop`, covering output 2000²/3000²/3400×3172/4096×2160, ROI 0.30/0.50/0.80, densities 1.0/2.5 when atlas-valid, asymmetry, head yaw/pitch/translation, jitter, deterministic random points, boundary clamps and negative controls for wrong previous matrix, double correction, and inverted sign. The 3000/0.5/1.0 case implies +30 source px for +0.01 full UV origin; 3000/0.3/2.5 implies +150 for +0.02.
- `duoview/CMakeLists.txt`: standalone test wired into Windows/local CTest.
- `duoview/joey_stage1/audit_generated.py`: produces bounded source SHA/excerpts from **actually patched Joey files** in the Windows Actions workspace; not a proof of callbacks executing or UE prev history correctness. Private SDK contents deliberately excluded.
- `.github/workflows/duoview-joey-stage234.yml`: scoped branch trigger to this v39 branch, runs independent oracle in existing CTest phase, captures generated source audit into persistent CI evidence. This does not alter protected Build37 workflow on its own branch.

## Milestone gates — strictly not optimistic
- **A0 DONE:** live GitHub permissions/source SHAs; isolated branch from named Build37 HEAD.
- **A1 IN PROGRESS:** generated-source excerpts not yet independently reviewed. Windows CI run `38631505443` was queued/running when this checkpoint was written.
- **A2 PARTIAL:** game public version 5.5.4 probable; installed game's exact version, active temporal upscaler and source ViewState consumer NOT VERIFIED.
- **B0 PARTIAL:** existing OFF-by-default opt-in current/CPU-only temporal audit; bounded CI generated-source report pending. No safe read-only UE previous-consumer capture yet.
- **B1 BLOCKED:** actual consumed UE previous projection, jitter, viewport and velocity units missing. Engine 5.5.4 does not itself establish consumer ABI.
- **C0 IMPLEMENTED / NOT YET VERIFIED:** independent C++ oracle source committed and registered; CI test outcome pending.
- **C1 IMPLEMENTED / NOT YET VERIFIED:** negative wrong-previous-projection/double-apply/inverted-sign tests.
- **D0-D1 BLOCKED:** no safe engine-owned previous-history adapter. No speculative offset write or global NGX hook done; renderer unchanged except diagnostic sign.
- **E/F/G NOT STARTED:** do not hide jitter via smoothing before previous temporal coherence established.
- **H BLOCKED:** Windows CI compile, original compatibility/WARP, independent review, package hashes and PSVR2 test acceptance not yet complete. **No headset artifact should be distributed from v39.**

## Next exact engineering tasks
1. Wait for the dedicated Windows CI source/test report and inspect the newly generated hook audit line-by-line. If the audit fails an anchor, correct the audit contract without disabling it. Verify full original source pins.
2. Review source0 camera capture against any later camera modifications in the original 1.9 MB `FFakeStereoRenderingHook.cpp`; do NOT infer correctness from anchor ordering alone. The first-pass camera capture appears placed before an original `Modify Player Control Rotation` section and must be traced.
3. Determine exact STALKER executable engine and active TSR/TAA/DLSS mode; locate validated engine temporal consumer previous matrix, ViewState and jitter. If unsupported by SDK, design narrowly scoped source-supported probe. No arbitrary memory reads or writes.
4. Independently audit math oracle implementation for duplicate formula assumptions, incorrect jitter handling, sizes or head pose sign. Only accept if full Windows suite passes, plus negative controls.
5. If UE history already includes the changing previous fovea projection, NEVER add Cheeky offset; fix actual proven pose/frame/viewport mismatch instead. If not, supply last **successfully rendered compatible source view** previous projection at verified engine pre-temporal consumption point. Include history reset/cut/size compatibility and GPU-success.
6. Only **after** D/E evidence, add tiny 1–2 output-pixel OpenNR guard and immediate saccades, then HLSL/WARP/high-res-source/fences tests and full Windows artifact audit.
7. Keep Build3 rollback intact; do not ask for repeated headset tests.

**Operator constraint:** Current green Build37 CI proves compilation, not gaze stability. A v39 Windows result will likewise not prove the UE historical matrix fix because such a fix is not yet implemented. This report is intentionally explicit about that limitation.
