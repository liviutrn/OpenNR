# DuoView v22 — independent source audit, spec and corrective patch record
Date: 2026-10-16
Status: **SOURCE-ONLY / NOT COMPILED / NOT HEADSET VERIFIED / NOT RELEASE-READY**
Repo: `liviutrn/OpenNR`
Audit target: `experiments/duoview-joey-v22-fixed-center-recovery`
Original Sol head before this audit: `a8a66a9f12f939aa2d26e1ff8aae1163e9d907ee`
Protected baseline: `experiments/duoview-temporal-shading-v22`; preserve original tested Joey Build 3 (run 38453012351).

## User-approved functional spec

1. **DuoView ID6 on every STALKER2 DX12 launch** (OpenXR and native OpenVR), independently of a previous session's failure state. Manual selection is possible after initial autostart.
2. Render two genuine UE source views from a shared frozen Mono center camera: fovea and periphery, with configurable source view index 0/1, fixed horizontal center and adjustable vertical center [0,1].
3. Disable actual eye-gaze acquisition and gaze-driven crop movement. Retain source controls: crop W/H, peripheral scale, foveal density, feather, source order, diagnostic, optional timing.
4. Secondary UE view must have distinct non-null ViewState from primary and have successfully executed the guarded Native Stereo Fix-style source-constructor pass+view-family masking transaction, not merely exist as a second rectangle. This is a **source necessary condition**, not proof of visual parity.
5. Composite a valid two-view atlas before submitting the same Mono full-FOV scene to both headset eyes with correct per-eye optical bounds and live HMD pose.
6. If DuoView repeatedly fails, switch via original Joey GPU-retired Mono-family transaction to **real Mono ID5**, never automatically Native Stereo ID0, never display a partial atlas as though it were Mono. Grace of 60 initial failed **game ticks**; four distinct failed ticks after first valid composite. Only one fault per tick. Manual retry of ID6 remains possible.
7. Keep the pinned Joey UEVR, private UESDK and frontend identity unchanged. Do not modify tested Joey Build 3 or original v22 baseline. Keep workflow `workflow_dispatch` only. Do not compile until separately approved.

## Source findings and corrections made

### P0-F01: A complete geometric pair could use aliased or untreated shading sources — corrected at the source gate
Original `duoview/DuoViewState.hpp::consume` only required family, projection, camera and both rectangles. It ignored `scene_states[]` and `shading_applied`, permitting a complete-looking but potentially wrong-lit periphery. It now requires distinct nonzero current source ViewStates **and** the secondary constructor transaction to have set `shading_applied`. The standalone regression contract now tests missing sources, same-source alias, untreated secondary, and accepted corrected secondary.

**Remaining limitation:** C++ source-side proof does not establish pixel-identical Lumen/shadows to Native Stereo Fix. If the guarded constructor never becomes applicable, the stricter gate intentionally declines the scene and eventually requests ID5 rather than presenting known-bad shading. This must be examined in a real STALKER2 headset test.

### P0-F02: Callback multiplicity could spuriously trigger Mono fallback — mitigated, not formally closed
Original `VR::duoview_abort` incremented `m_duoview_consecutive_failures` for every callback, so several setup/projection/compositor callbacks inside a single failed game tick could exhaust the four-failure threshold at once. Patched `apply_stage234.py` now assigns an atomic game-tick serial in `on_pre_engine_tick`, deduplicates with CAS, and gives success in the same tick priority. The game-thread fallback consumer rechecks the failure threshold before requesting Mono ID5. The standalone helper `is_distinct_failed_tick` has unit contract cases.

**Remaining limitation:** the serial represents a game tick, not a perfectly latched Unreal render-frame ID. When game/render threads are pipelined, late callbacks may land in the following tick. A runtime-tagged frame key would be a stronger final design; source compilation and instrumentation are still required. A valid compositor recording is not proof of SteamVR Submit / OpenXR display success.

### P1-F03: Persisted Mono ID5 could defeat next-launch auto-DuoView — corrected
Original first-ready-tick autostart requested ID6 only if saved/requested ID was Native Stereo ID0. A prior-session failed run persisted Mono ID5 and thus prevented the next session from trying DuoView. First eligible STALKER2 DX12 tick now requests ID6 unless it is already requested, then leaves later manual selections alone.

**Remaining limitation:** Joey's original Mono-family Selection intentionally defers commitment until GPU retirement; a high-resolution initial ID0 allocation may still occur before ID6 commits. No claim that all high-resolution bootstrap crashes are fixed.

### P1-F04: Broken source gates and misleading future package instructions — corrected
`verify_stage234.py` had the same smoothing token twice and omitted critical persisted settings for vertical center and fovea view selection. It now checks those names, treated-secondary gate, atomic tick accounting and restart to ID6. Manual CI's `READ_FIRST.txt` was incorrectly describing eye tracking ON, an internal quarantine and OpenXR-only support; it even required the stale phrase `QUARANTINED internally` to package. Workflow text and release guard now describe fixed-center OpenXR/OpenVR, DuoView->real Mono, separate test copy and headset-unverified status, using a `Joey-DuoView-v22-FixedCenter-` artifact prefix. The patch script's obsolete description was also updated.

## Preserved implementation invariants

- In the pinned Joey backend, Stage1 changes `is_using_mono()` to include **both** ID5 and ID6. Do **not** mistake the unchanged original Joey `is_using_mono()==ID5` code for the effective Stage1-patched version when reviewing the OpenVR shared projection.
- Source patches apply *in CI*, by `duoview/joey_stage1/apply_stage234.py`, after `apply_stage1.py`. The `OpenNR` tree does not contain a fully transformed copy of Joey's giant C++ files.
- `DuoViewState.hpp` and regression tests are linked to the patch script's copy step; `verify_stage234.py` guards edited backend/frontend paths and pinned SDK, though it is not a compiler.
- OpenVR records the DuoView composite into a dedicated double-wide resource then uses the existing SteamVR per-eye copies and pose submission; ID5 copies the left engine half to both eyes. OpenXR uses the existing double-wide swapchain.
- No automatic Native Stereo ID0 request was introduced in the corrected DuoView fault policy.
- Stable baseline branch and original tested Build3 remain untouched.

## Unresolved P0/P1 review and runtime gates

1. **P0**: Run exact-anchor patcher against the pinned original Joey UEVR and authorized UESDK, then full Windows C++ compile, CMake contracts, WARP GPU tests, matching frontend and hash verifier. None has been run on this audit's head. Static reading is not compile validation.
2. **P0**: Prove constructor transaction enters for STALKER2 SECONDARY source (first source current-frame `ViewState`, view-family singleton, temporary PRIMARY relabel, mask restoration on every exceptional/early-return path). Check actual Lumen/shadows in game rather than trusting `shading_applied`.
3. **P0**: Prove 6DoF on both OpenXR and native OpenVR using headset pose and canted-eye optical calibration. Specifically reject head-locked presentation and blank second source.
4. **P0**: Validate GPU lifetime: OpenVR one-slot `wait(INFINITE)`, compositor command execution, output texture state, SteamVR copy consumer retirement and device/reset/resize. Establish bounded stalls and no allocator reuse before fence retirement. Do not remove waits without an explicit safe multi-slot design.
5. **P0**: Verify startup at high resolution (Native ID0 exposure during deferred Mono-family commit), no VRAM crash, and 6->5->6 manual retry. Check per-frame failure accounting with threaded instrumentation.
6. **P1**: Test DLSS/screen-percentage and format changes, atlas/output dimension match, PSO prewarm, sRGB handling, texture growth and per-eye bounds. The compositing guards correctly reject dimension mismatches, but this can force fallback.
7. **P1**: Exercise hidden eye tracking OFF, 0..1 vertical positioning, source selection UE0/UE1, 50%x50% fovea, 0.2 periphery default, diagnostic isolation, and UI/profile serialization.
8. **P1**: Audit other games to confirm new OpenVR Mono capability remains STALKER2 DX12-only, and check original Joey ID0/5 behavior has not regressed.
9. **P1**: Generic repository push workflows may still trigger and fail for reasons unrelated to the manually held DuoView build. The DuoView workflow itself remains `workflow_dispatch`; no DuoView Windows build was dispatched during this audit.

## Exact post-audit source checkpoints

- Source gate correction: `ff892c0b9c001fd0e4541cba37f141de23e48d7e`
- Negative source-pair contracts: `35362135c9d114dd04f56dbd6e9d76d47f65c169`
- Distinct game-tick predicate: `82d400965207d3018249803afeaaf231d2000ec0`
- Runtime fallback/autostart correction: `9dedce3b8e47ae4521d14e2834be347d3f6498da`
- Fault helper tests: `8d62ad8255de169d6ccc02eb3364364d813c861f`
- More complete source verifier: `6cab4a04ad90d1b9d29f702c56d4cffe13e3171c`
- Corrected prospective package instructions: `723bebf4f340e9e22a2966b31c295086d0bcb7bc`
- Corrected patch-script documentation: `c77c1ee7eacc8e3d6d6fd0911aface117bf2c12b`

## Current verdict

**Source changes are committed for Astra review, NOT signed off as functional in-game or ready to compile/release automatically.** The known unguarded secondary source, same-tick multiple fault callbacks, prior-ID5 auto-start regression and misleading package gate have concrete corrections. The main remaining blockers require pinned Windows compilation and actual PSVR2 game behavior. No backend DLL, ZIP headset build or compilation was created during this source-only audit.


## Addendum — independent OpenVR submission audit (same day)

### P0-F05: A GPU-recorded composite was incorrectly marked presented before SteamVR accepted either eye — corrected
The original v22 OpenVR path invoked `vr->duoview_frame_success()` as soon as the compositor command was recorded and enqueued, *before* `VRCompositor()->Submit` for left/right eyes. Thus the four-failure policy could continually reset despite SteamVR rejecting a presented eye. The fixed `apply_stage234.py` now tracks the left-eye result, reports right-eye submit errors, and only calls `duoview_frame_success()` after **both** Submit calls return `VRCompositorError_None`. The source verifier requires this gate. It does not establish that asynchronous GPU work ultimately completes, or that the pose and optical bounds are correct.

Additional commits:
- OpenVR both-eye success gate: `ddf4820a50d52cb4a255bc1b1776b512ea8a5449`
- Verifier gate for both-eye success: `0bbc5e1980cedc6ece9f3dde8c9f3d666ec0818a`

### Independent no-compile static spot checks
Through GitHub, compared the two new exact-anchor OpenVR submit snippets to pinned `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`: each appears **exactly once** in that source. Confirmed the source has the guarded secondary ViewState/parity test, game-tick CAS, DuoView restart condition, two-eye SteamVR success guard and correct future package wording. Confirmed `duoview-joey-stage234.yml` has `workflow_dispatch` and no `push` trigger.

Historical run `38902027894` / workflow run #139 **completed successfully** at `708b6e184cd94131ecec182f7a260cad8fa8b468`; that is an **earlier commit** and must not be used to certify this independently patched audit head. No new Windows DuoView compilation was launched for this audit.

Source-only remaining warnings: game-tick fault deduplication does not prove exact cross-thread render frame attribution; C++ compile, source anchor execution in Stage1+Stage234 order, real SteamVR optical/pose behavior, UE Lumen parity and headset tests are still needed.
