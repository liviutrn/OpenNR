# Astra adversarial source review handoff — Joey DuoView v22 fixed-center recovery
Date: 2026-10-16. **Status: SOURCE REVIEW ONLY. DO NOT COMPILE, BUILD, OR SHIP.**

## User-approved brief and boundary
User wants the new STALKER 2 / UEVR DX12 DuoView to start in mode 6, render two *monoscopic* Unreal source views (a high-quality fixed-center fovea and a lower-resolution periphery), share one HMD-tracked center camera, blend through DuoView DX12 composite, and submit the monoscopic image to both PSVR2 eyes. Eye tracking is disabled; vertical crop center is adjustable. Preserve the original Joey source/backends and original standalone Mono ID5 / Native Stereo ID0. Ensure the peripheral source has lighting/shading equivalent to Native Stereo Fix's correctly independent secondary source.

**Failure policy was changed by the user:** prefer persistent working DuoView ID6; if it genuinely cannot render, safely transition to actual Joey Mono ID5, never automatically request Native Stereo ID0. The unfinished source provides up to 60 failing *observations* before first valid DuoView composite, or 4 consecutive failed observations after first success, then asks for a GPU-retired mode-6 to mode-5 transition on the game thread. User does NOT want infinite blank frames or an atlas copied as false Mono.

The user explicitly requested **no new compilation before Astra reviews**. In `.github/workflows/duoview-joey-stage234.yml`, all push triggers have been removed, leaving `workflow_dispatch` only. Do not press Run Workflow or enable push triggers without user authorization. Earlier #139 was started before this hold and is not validation of latest source.

## Exact source of truth
- Main repository: `liviutrn/OpenNR`
- Source-review branch: `experiments/duoview-joey-v22-fixed-center-recovery`
- Base reference: `experiments/duoview-temporal-shading-v22`, do not overwrite
- Original Joey UEVR pin: `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`
- Original authorized UESDK pin: `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`
- Matching frontend: `joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091`
- Preserve previously user-verified Joey Build 3 / run `38453012351` unchanged
- **IMPORTANT**: the runtime changes live largely as *exact-anchor Python patches* in `duoview/joey_stage1/apply_stage234.py` to the pinned Joey backend at build time, not as a prepatched UEVR source tree. Review BOTH the exact expected original source and the replacement strings.
- `duoview/joey_stage1/verify_stage234.py`: unchanged pins, allowed changed-file manifest, source invariants and hashes
- `duoview/joey_stage1/ProductionContractTests.cpp`: tests (written but NOT newly compiled/executed)
- `duoview/DuoViewState.hpp`, `DuoViewConfig.hpp`, `DuoViewD3D12.hpp`, `DuoViewCropStability.hpp`: renderer/frozen state and GPU contracts
- `duoview/stage10_state_tests.cpp`: legacy fixed/tracked helper tests
- Workflow: https://github.com/liviutrn/OpenNR/actions/workflows/duoview-joey-stage234.yml

## Work now present in the source-review branch
1. Fixed-center mode6 in game, `DuoViewFixedCenterVertical` control (0–1), gaze reads disabled in production; render/crop snapshot latched once per UE frame.
2. Source view 0 (fovea by default) and view 1 (periphery by default); shared Mono pose and frozen source projection. No deliberate right-eye physical offset.
3. Secondary source constructor adapts stereo pass SECONDARY -> PRIMARY **and** temporarily hides the current main FSceneViewFamily singleton, restoring original view count and constructor pass through Joey's original cleanup. This mirrors one source-side part of Native Stereo Fix WITHOUT globally enabling Native Fix capture/submit.
4. Critical source-audit correction: `can_native_fix_secondary_source` must accept a valid current *primary* scene/rect/projection/camera while the secondary constructor is still running; it cannot demand secondary camera/projection observations published AFTER that constructor. An explicit new pre-secondary regression scenario is in `ProductionContractTests.cpp`.
5. Strict no-fallback was REMOVED. Persistent failure calls `m_rendering_method->request(RenderingMethod::MONO)` on `on_pre_engine_tick`, processed by original Joey Mono-family GPU-retirement and frame-boundary logic. Failure counter cleared on successful DuoView composite; no source code deliberately requests native ID0 as a fallback.
6. In OpenVR, mode6 has a DX12 compositor feeding the existing pose-aware OpenVR left/right eye submit. To make mode5 fallback meaningful, a single Mono engine view's **left half** is copied to the right eye, with canted-eye-aware common Mono projection and per-eye view bounds. OpenVR Mono availability is scoped to **STALKER2 DX12 ONLY**. All other titles retain the original Joey OpenXR-only Mono rule.
7. GPU release / reset logic adds retirement checks for OpenVR DuoView output/context and per-eye copy consumers; compositing now checks `CommandContext::wait(INFINITE)` outcome before recording.
8. Current quality controls retained: fovea W/H, peripheral scale, center vertical, pixel density, feather, source-index switch, debug views, GPU timing. Eye gaze is intentionally not offered for this new fixed-center branch.
9. The Windows source branch and all changes remain isolated; the original v22 and Build3 have not been replaced.

## High-priority adversarial review questions — DO NOT ASSUME PASS
### P0 — frame/time and fallback correctness
- Is the four-failure/60-startup-observation state machine actually *per frame* under all OpenXR/OpenVR submission/recreate callbacks, or can several failure calls in one frame falsely advance it? If necessary deduplicate by atomic frame key.
- Does mode-6 -> mode-5 selection truly complete using `service_mono_transition_present` / `service_mono_transition_game_thread` without Native Stereo exposure, stale atlas, GPU lifetime race or rejected OpenVR Mono eligibility? Check actual `Selection.initialize` bootstrap (which internally defers with active ID0), especially high-resolution startup.
- Do renderer initialization failures, incomplete source pair, invalid XR frame/projection and device resets all become observable failures rather than infinite silent blank frames? Confirm game thread can still run to complete fallback.
- If success arrives between setting fallback flag and the game thread consuming it, intended behavior is to keep DuoView; verify no unintended mode thrash.
- Confirm safe 6->5->6 manual retry and saved profile behavior.

### P0 — STALKER2 Native Stereo Fix source parity
- Does the secondary constructor see the **actual current-frame** PRIMARY view-state pointer and correct FSceneViewFamily singleton, and does the relabel/mask restore on every control flow path?
- Do `can_native_fix_secondary_source`, view-family RT identity, temporary pass, first-view scene state and physical second-view source identity prove *actual* distinct source rendering without accidentally turning both into the same view?
- Native Stereo Fix in pinned Joey has more logic than pass relabeling (capture generation, view-state ownership and per-frame backend handling). Which parts are **required** specifically to match Lumen/shadows for the *peripheral* source? Do not assert visual parity without a live headset test.
- Verify first view fovea source 0 / second view peripheral 1 behavior with native-source parity. Also test fovea_view=1.

### P0 — OpenVR true Mono and 6DoF presentation
- Validate common binocular frustum signs and quaternion conversion against OpenXR's original `mono_geometry` path and SteamVR's `GetProjectionRaw`.
- Verify output texture is full-width, GPU states correct, and `m_openvr.copy_left` / `copy_left_to_right` use **identical completed Mono** while preserving per-eye OpenVR cropping and HMD pose.
- Confirm first startup and rendering-method switch recalibrate OpenVR projection and correct both eye bounds; do not accidentally make the display head-locked.
- OpenVR currently has a **single compositor command context** and `wait(INFINITE)` before each use; assess potential GPU/CPU serialization, frame hitches and need for safe bounded multi-slot GPU resources. Do not blindly replace blocking waits with unsafe allocator reuse.
- Inspect all resource lifetime/teardown branches and failed prewarm/texture creates.

### P1 — code/packaging correctness
- Check every Python exact-anchor in `apply_stage234.py` against exact upstream pinned Joey text, plus literal C++ syntax and all API members; do not infer a successful compile from old CI.
- Review `verify_stage234.py` source-gate for accidentally false-positive or false-negative string checks (it is no replacement for a compiler).
- Verify source path whitelist, SDK immutability, UI/options serialization, frontend ID6 labeling, game-specific capability conditions and absence of other-title regressions.
- Audit shader PSO prewarm, fallback to ID5 during XR frame stage, CVar/screen percentage, swapchain growth at very high resolutions, compositor source vs dest formats and GPU timings.
- No eye tracking/motion vector history repair is required in THIS branch.

## CI history and release rule
- #113 Windows build PASS on an earlier, much simpler fixed-center checkpoint.
- #127 FAIL on later OpenVR source: two nonexistent logging macros (`SPDLOG_INFO_ONCE` and `SPDLOG_ERROR_EVERY_N_SEC`) in OpenVR.cpp. Both changed to existing `spdlog::info/error`.
- #137 FAIL due exact-anchor string inadvertently modified in patch script; corrected.
- #138 FAIL due a stale validator expectation after fallback redesign; corrected.
- #139 was initiated PRIOR to user disabling builds and PRIOR to the latest source-review patches. No completed binary or runtime validation of final source exists. DO NOT run Windows CI now.
- Latest reviewer-approved build would need SDK-pinned Windows full compatibility tests, frontend, WARP, DLL/artifact hashing, then a real STALKER2 PSVR2/OpenXR and SteamVR OpenVR trial. Until then **no verified release binary**.

## Astra requested output
Provide a prioritized, adversarial static engineering review with exact file/function/snippet anchors, proposed corrections and severity. Enumerate all compile-time risks, incorrect conditional branches, stale GPU state/resource hazards, impossible frame guards, Native Stereo Fix mismatches, and Mono fallback corner cases. **Do not compile, dispatch workflow, generate a headset test build, or merge until the user explicitly authorizes it.** Offer a minimal patch plan or audited code changes on the SAME source-review branch only if user later requests implementation.
