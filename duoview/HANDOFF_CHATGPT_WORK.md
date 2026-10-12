# Current continuation status (2026-10-13)

The initial handoff below is retained as historical evidence. Continue from the active **public backend Windows injector** workflow and `duoview/WORK_LOG.md`, not the earlier private-SDK compile probe. Current source pins and render integration are documented in `duoview/UEVR_INTEGRATION.md`. Public Mono/DuoView patches, native Toolkit gaze, immutable camera/frame settings, real DX12 composition and matching injector packaging are implemented. Windows policy and production WARP tests have passed; consult the latest workflow for the full-DLL/injector result. No actual headset testing has been performed here.

---

# ChatGPT Work handoff — DuoView Mono for Joey UEVR / STALKER 2

**Handoff date:** 2026-10-13 (Europe/Bucharest). **Project is ongoing, NOT game-ready.**

## EXECUTION REQUEST FOR CHATGPT WORK

Take ownership of this GitHub engineering project and execute concrete development, not merely propose solutions. Work directly in the connected GitHub repository; inspect current Actions state and compile errors; iterate source patches, code review, Windows CI, and eventually a headset-testable UEVR binary. Be proactive with new blockers and check each build log. Keep working on the current task until as much as can be completed is actually completed; never claim an unfinished build succeeded or promise unmonitored background activity.

**First action:** inspect the most recent status/logs of GitHub Actions run [38310862046](https://github.com/liviutrn/OpenNR/actions/runs/38310862046), job **windows-build-probe**, on v07. At handoff it is still **in_progress** in the “Attempt real UEVRBackend.dll compilation” step, while **public-sdk-include-audit** passed. Do not infer that the build succeeded or failed from this last observation. Other older v06 runs may also be active: avoid confusing their results with v07. If the run failed, read the build logs artifact and actual compiler errors and fix the first causal errors (not cascades), then push another iteration with proper CI.

## User intent / nonnegotiable behavior

- STALKER 2 played through **Joey Hodge's UEVR Mono**, using a **PSVR2 headset on PC, SteamVR as OpenXR runtime**, on an RTX 5070.
- Keep the working original **Mono rendering method ID 5** intact. Add separate **DuoView Mono method ID 6**.
- Render *two different-resolution Unreal views of the same MONO camera pose*: one **full-FOV very low-resolution peripheral view**, and one **eye-tracked high-density foveal crop** of the full mono frustum; combine to **one full-FOV mono picture** and submit the same mono picture to both OpenXR eyes.
- This is **two-view foveated Mono**, NOT stereoscopic quad views and NOT two separated left/right camera poses. No artificial IPD. Preserve 6DoF head tracking. Both UE views must share camera rotation, position and a frozen gaze/optical projection snapshot. Only their projections, screen rects, and pixel densities differ.
- Native eye tracking via the existing PSVR2 Toolkit CAPI bridge is preferred. Avoid smoothing, gaze dead zones, image regeneration and any frame-to-frame crop flicker. Gaze can update every new renderer frame; **within** a frame all views/compositor use the exact same immutable gaze.
- Prioritize GPU cost and actual sharpness/PPD in the fovea. Allow configurable crop width/height, density and peripheral scale. Preserve existing Joey Mono behavior and other rendering modes.
- User **cannot compile locally**. A working **GitHub Actions Windows DLL/injector artifact** and ideally public GitHub release are required to enable headset testing. Do not ask the user to contact Joey or provide inaccessible private UESDK. The repo currently is an experiment branch in `liviutrn/OpenNR`; do not modify `main` or other working OpenNR releases.
- User wants proactive self-review, actual compiler verification and repeated fixes. If a true second reviewer can be invoked, use it; do not invent having used one.

## Key repositories / immutable pins

- **Working GitHub repository:** https://github.com/liviutrn/OpenNR
- **Primary active working branch:** https://github.com/liviutrn/OpenNR/tree/experiments/duoview-uevr-v07-stalker-publicsdk
- **General public SDK build branch:** https://github.com/liviutrn/OpenNR/tree/experiments/duoview-uevr-v06-publicsdk
- **Last independently GPU-validated compositor branch:** https://github.com/liviutrn/OpenNR/tree/experiments/duoview-uevr-v05
- **Original Joey Mono/DIBR backend:** https://github.com/joeyhodge/UEVR at exact commit `db6729dd9f5745705b1cdec2ec6f51bdc9570983` (Sept 26, 2026).
- **Newer accessible UESDK candidate:** https://github.com/elliotttate/UESDK-RenderDoc at `418729025bad57b094bf6b2e2b55734454c97de6` (July 9, 2026).
- **Inaccessible private Joey UESDK:** `https://github.com/joeyhodge/UESDK` gitlink `2ad9fefa67eb69634b9a1252f4b99876f5333671`; 404 for this account and user cannot contact Joey. Do not treat private access as a viable prerequisite.
- Public old alternative `Aeyth8/UESDK` dates from 2024 and has major missing headers; the July 2026 public SDK is materially closer.

## Direct source and docs to read

Start here in **v07**: `duoview/README.md`, `duoview/UEVR_INTEGRATION.md`, `duoview/PUBLIC_SDK_COMPAT_AUDIT.md`, `duoview/apply_stage1.py`, `duoview/apply_stage2.py`, `duoview/apply_stalker_publicsdk_abi.py`, and workflows in `.github/workflows/`.

The README/INTEGRATION files are inherited from v05 and describe the tested compositor but **still emphasize the old private-SDK flow**; v06/v07 CI works around that. Update docs as the implementation matures and make release README feature-focused.

Relevant source components:

| File | Function / status |
|---|---|
| `duoview/apply_stage1.py` | Strict pinned-upstream source transformation: adds method 6, existing guarded Mono switch compatibility, two UE views, tests; source-patch validation only |
| `duoview/apply_stage2.py` | Unequal UE view rects + off-axis foveal projection; **fixed-center test crop**, **no UEVR actual GPU composite yet** |
| `duoview/DuoViewGeometry.hpp` | Cropped layout, projected ROI, shader coordinate/feather model; unit tested |
| `duoview/DuoViewGaze.hpp` | Mono optical tangent frustum ray-to-UV, 50-ms validity cache without smoothing; not wired to PSVR2 yet |
| `duoview/DuoViewConfig.hpp` | Frozen per-frame gaze/crop/peripheral scale/density snapshot; unit tested but not hooked into UE |
| `duoview/DuoViewFrame.hpp` | Paired UE view and GPU completion fence/generation gating; unit tested but not hooked into UE |
| `duoview/DuoViewComposite.hlsl` | Standalone DX12 compute compositor (shader compiled and executed on WARP) |
| `duoview/DuoViewCompositeRaster.hlsl` | Preferred BGRA8 RTV fullscreen-triangle compositor (actual WARP execution and readback passed) |
| `duoview/DuoViewMonoCopyD3D12.hpp` | Single-width BGRA8 composite -> duplicate to both halves of double-wide OpenXR output; WARP pixel comparisons passed |
| `duoview/DuoViewWarpTest.cpp` | Windows D3D12 offscreen GPU test for compute, BGRA8 raster and full stereo-copy |
| `duoview/apply_stalker_publicsdk_abi.py` | Experimental STALKER 2 UE5.5 *compile-only* suppression of unavailable UE5.8 and UE5.0-5.3 SDK declarations |
| `duoview/audit_public_sdk.py` | Enumerates missing SDK includes and usage sites; not a full ABI audit |
| `duoview/stage2_geometry_tests.cpp` / `stage4_gaze_tests.cpp` / `stage5_frame_tests.cpp` / `stage8_config_tests.cpp` | Standalone regressions; passed Linux clang with warnings as errors, MSVC tests for earlier stages |

**Bug already fixed:** `FrameCoordinator::begin` originally allowed an older rendering `generation` to supersede a newer one. Corrected in v06 branch (commit `7edba00b83e284a3956fc412718da61c63653402`) and added regression test; inherited into v07.

## CI results / exact proven evidence

### Successful standalone GPU pipeline tests — *not* complete injector

- https://github.com/liviutrn/OpenNR/actions/runs/38307862007 (Stage 9, success)
- https://github.com/liviutrn/OpenNR/actions/runs/38308011935 (Stage 9, success)
- https://github.com/liviutrn/OpenNR/actions/runs/38308118245 (Stage 9, success)

Compiled with Windows Visual Studio 2022 + SDK. DX12 WARP GPU readback:
- Compute output foveal center RGB **[255,0,0]**, periphery **[0,0,255]**, feather edge **[43,0,212]**.
- BGRA8 raster path returned **identical pixel RGBs**.
- Single-width BGRA8 -> double-wide BGRA8 copies compared **1,024 pixel pairs over all four channels**, **zero mismatches** after fence signal.
- This validates the standalone hardware API path (WARP software D3D12), **not the actual rendering hook, game compatibility, performance, or eye tracking**.

### Public SDK real backend build attempts

- https://github.com/liviutrn/OpenNR/actions/runs/38308963146: CMake configuration failed because Joey's private SDK-only compatibility tests refer to `dependencies/submodules/UESDK/tests/DiscoveryValidationTests.cpp`. These private unit tests were disabled **only** for public SDK full-backend feasibility (`-DUEVR_BUILD_COMPATIBILITY_TESTS=OFF`); standalone regressions remain enabled.
- https://github.com/liviutrn/OpenNR/actions/runs/38309743472: Windows CMake **succeeded**, actual target `uevr` C++ compilation began and **failed** in `FFakeStereoRenderingHook.hpp` on missing `IStereoRenderTargetManager_58_Transitional` and `sdk::FSceneViewInitOptionsUE50To53`. Remaining override/unordered_map compiler errors are cascades; read full logs and seek root causes. Thus **public UESDK is NOT drop-in compatible**, including even headers that exist.
- v06 subsequent runs source tests passed; multiple Windows jobs may be in progress, their conclusions must be checked independently.
- **v07 main run:** https://github.com/liviutrn/OpenNR/actions/runs/38310862046 — `public-sdk-include-audit` PASSED; `windows-build-probe` still **in_progress** at last check in `Attempt real UEVRBackend.dll compilation`. **Refresh the status as the first action.**

### SDK missing-header audit

Of 66 distinct directly referenced UESDK headers from Joey, July public SDK has **56** but lacks **10**:

`BoundedDiscovery.hpp`, `DiscoveryMemory.hpp`, `FSceneViewLayoutPolicy.hpp`,
`KtjLObjectLayout.hpp`, `KtjLSceneViewLayout.hpp`, `KtjLStereoBootstrap.hpp`,
`MafiaDiscovery.hpp`, `ObjectLivenessPolicy.hpp`, `RtmDiscovery.hpp`,
`SceneDiscoveryState.hpp`.

This is only a header-presence inventory; deeper missing API classes/methods/ABI are not included. Do not stub headers without understanding exact memory layout and behavior.

### v07 experiment

Since STALKER 2 has been reported as using UE5.5.4, the v07 script tries temporarily **excluding UE5.8 transitional manager and UE5.0–5.3 InitOptions SDK branches**, instead of inventing virtual-table signatures/memory offsets. It is a **compile probe**, not necessarily safe for other games. Verify STALKER 2's installed engine version from the actual game when feasible, and inspect the source for every other UE version branch. If the script merely masks or breaks required definitions, abandon it and choose a safer public baseline. Also note the `UEVR_DUOVIEW_PUBLICSDK_STALKER2_ONLY` preprocessor macro is prefixed in the patched CPP and HPP, not globally defined.

## Renderer integration still outstanding — **critical path after backend build**

1. **Validate source patch semantics in the real renderer:** method ID 6 should produce exactly 2 UE render views with the **same Mono origin and rotation**, no stereo/IPD, distinct off-axis projection for gaze ROI vs full projection for peripheral view. Confirm actual `view_index`, one-based passes, matrix precision (UE5 doubles), clip-coordinate conventions, 2W×H allocation, and that the scene rects actually reduce shader work. Current `apply_stage2.py` only creates an **uncomposited atlas diagnostic**.
2. **Freeze gaze/settings before first UE projection callback** using `ConfigLatch`; both views and GPU compositor must use identical snapshot even when gaze changes between callbacks. `DuoViewFrame` should track **actual completed render passes**, not just view-family count, rect or projection callbacks.
3. **Place real DX12 GPU pass in UEVR:** Joey's `src/mods/vr/D3D12Component.cpp` has existing Mono copy around **lines 5003–5018** at pinned commit, using `uevr::mono::dx12::copy_scene`. Keep original method-5 branch unchanged. For method 6, take actual atlas scene source, transition resource state to `PIXEL_SHADER_RESOURCE`, render fullscreen triangle to dedicated BGRA8 single-eye-width RTV, transition for copy and duplicate to each half of existing OpenXR double-wide destination using `copy_composite_to_stereo`. Preserve resource state ownership, view formats, fence and lifetime, device removal/reset, transition 5<->6, and validated Mono OpenXR frame gate. **No copies from prior frames.**
4. **PSVR2 Toolkit CAPI:** already proven bridge from prior project exists in `liviutrn/OpenNR` branch `experiments/cheeky-psvr2-r10`, source `CheekyPort/overrides/openxr_layer/psvr2_native_gaze.hpp`. Can reuse combined ray logic, blink/tracking validity and 50ms cache, but verify transform into **actual common Mono optical projection**, not a naïve symmetric/per-eye tangent assumption. Zero gaze position smoothing and deadzone desired. OpenXR rather than OpenVR.
5. **Controls:** separate configurable crop W/H (50% and 30% examples), fovea density, periphery scale, feather and fixed-vs-gaze test mode; settings UI must not change one UE view mid-frame or demand repeated manual restarts.
6. **Test actual STALKER 2 UE5 DX12 + PSVR2:** shader alignment, headset resolution, vignette/feather seam, color/exposure, temporal history/TSR/TAA/Lumen/shadows, disocclusion, head motion, eye-gaze motion, and accurate GPU/CPU frametimes. An atlas pixel budget is **not a gameplay speedup**.

## Baseline calculations (theory, NOT measured gain)

User: 3000×3000 Mono ≈50 FPS; native stereo ~2000×2000 per eye ≈50 FPS (estimate). At fixed 3000×3000 full-Mono output, periphery 20% width and height and fovea density 1x:
- 50%-wide/50%-high fovea: 1500×1500 = 2.25M plus 600×600 = 0.36M peripheral pixels => **2.61M**, or **71% fewer *view pixels*** than baseline 9M.
- 30%-wide/30%-high fovea: 900×900 = 0.81M plus 0.36M => **1.17M**, **87% fewer *view pixels***.
- Do not claim 71–87% FPS/GPU time gain; Lumen, UE scene fixed costs, view count, full-size post, CPU and temporal history could severely limit gains. Report foveal PPD with real optical projection, not guessed headset FOV.

## Workflow/ops preferences

- Prefer actual compiler output, git-anchored source checks, testable changes, repeated CI.
- Isolate all experiments; do not overwrite the original installed Joey UEVR Mono or OpenNR main.
- Keep changes and docs in GitHub; GitHub Actions outputs must be easy to download. Produce a public release only if the binary has actually compiled and is clearly experimental/safe to test; use honest version naming.
- Don't require user local compilation, private Joey access, or user contact with Joey.
- Avoid fake green status: report whether specific checks are source-only, WARP GPU, full UEVR binary compile, or actual headset.
- If failed jobs are stale, identify latest run from branch HEAD; test only current code. In experimental branch many unrelated OpenNR workflows fail: count only named DuoView workflows and investigate real errors.
- Work may use connected GitHub app, cloud browser and other tools; obtain user authorization for any external services or actions as required.

## Exact next instructions

1. Fetch run `38310862046` and its Windows job logs (or newest v07 run by branch HEAD). If final error, solve the **earliest root error**, preferably without fabricating an Unreal ABI layout.
2. Inspect/fix `apply_stalker_publicsdk_abi.py` and test patch against pinned source. Verify no additional header/C++ references make UE5.5 compile impossible with that SDK.
3. Evaluate better accessible public UEVR/UESDK revisions if v07 has deep incompatibilities. If needed rebase original Mono feature onto a compatible public source rather than fake SDK headers.
4. Create repeatable successful **full backend Windows build** with real `uevr` DLL. Publish Actions artifact on successful build; do not call uncomposited stage-2 mode usable.
5. Integrate actual DX12 composer, PSVR2 gaze and UI; add production tests; rerun Windows build until testable; then hand user exact artifact and staged STALKER 2/PSVR2 validation steps.

**Take over from the current verified status. Do not repeat finished standalone GPU stages merely as busywork.**
