# DuoView Mono UEVR — Build 29 continuation handoff

Prepared 14 October 2026, Europe/Bucharest. This document supersedes earlier progress checkpoints for the latest delivered build. Read it completely before changing code.

## 1. Start here: actual status and next action

**Latest testable build: v22 Build 29.** Full Windows CI succeeded and its downloaded injector package was independently inspected. **No headset result for Build 29 has been reported in this conversation.** It is ready for testing, not established as production stable.

- Download: https://github.com/liviutrn/OpenNR/actions/runs/38557341481/artifacts/11891093120
- Successful run: https://github.com/liviutrn/OpenNR/actions/runs/38557341481
- Artifact name: `Joey-DuoView-Temporal-v22-29`.
- Artifact ID: `11891093120`.
- Compiled source: `bd8024c9e83debaaee6890d36c756f186e8421e1`.
- Repository: https://github.com/liviutrn/OpenNR
- Active branch: `experiments/duoview-temporal-shading-v22`.
- Latest existing verification-document commit before this new handoff: `89ffb4bf35b787e4b92885bd075c6bdb8b86292d`. Documentation commits after the compiled source are not different binaries.

First independently verify the exact run, artifact and source. Then incorporate Liviu's Build 29 headset feedback. Do not produce another speculative build before understanding any reported defect. Preserve the original Joey Build 3 and all comparison builds/branches. No CI job remains to be completed for Build 29.

## 2. User goal, environment and constraints

Target: STALKER 2, DX12, PSVR2 on PC, SteamVR as the active **OpenXR runtime**, PSVR2 Toolkit CAPI eye tracking. SteamVR being the runtime does not mean this experimental renderer uses the OpenVR submission path.

The goal is a two-source Mono foveated renderer: reuse working Joey Unreal two-view rendering for a high-resolution moving foveal source and lower-resolution full-FOV periphery, using the same Mono camera. Composite these into the headset output. This is not four independently rendered stereo views. User values high foveal clarity and smooth frame pacing; changes must retain original Joey mode behavior and the restored controls.

User explicitly requested these additions after the old-behavior restoration:

1. Stabilize gaze-driven crop positioning using lessons from OpenNR's stable crops.
2. Investigate shading improvement, with an in-game toggle that starts OFF and can be enabled **after DuoView has settled**; full Native Stereo Fix can be buggy.
3. Address real crop/image jumping and projection/history/motion-vector coherence, not merely natural eye movement. Examine OpenNR and Cheeky DLSS crop work.

Do not claim CPU tests prove game Lumen, TSR, motion vectors, shading or headset frame pacing. User wants complete Windows GitHub Actions artifacts, meaningful tests, inspected packages, durable repository handoffs and clear progress updates. Existing SDK credentials work; do not ask for them again.

## 3. Exact upstream pins and protected baseline

| Component | Repository | Exact commit |
|---|---|---|
| Backend | `joeyhodge/UEVR` | `5ac7edc207866569334175e4ed8a7517971547f6` |
| Original restricted SDK | `joeyhodge/UESDK` | `3cffbc82429b6165ceec2714f0f0d9ae48f55596` |
| Frontend | `joeyhodge/uevr-frontend` | `60be4b0f9a646109fd9fdf448bacd41477234091` |

The restricted original SDK is checked out using the existing Actions secret `UEVR_SOURCE_TOKEN || PAT_TOKEN`. It is unchanged and not bundled as source. Do not substitute the earlier reconstructed/public SDK or copy private SDK source into a public package. Existing SDK discovery setters are used; no guessed Unreal memory offsets are introduced.

**Joey exact-source clean Build 3 is the protected control:** run `38453012351`, source `64432d0442066715fa442660a0848cf4963640b0`. User tested original Mono ID5 for 30 minutes with no hitches/problems and no setup changes. Never overwrite its install or branch. The two-source DuoView integration is experimental ID6; Native Stereo ID0 and original Mono ID5 keep their original routes.

## 4. Comparison builds and corrected user observations

| Build | Exact source / run | Verified user observation / purpose |
|---|---|---|
| Old Injector 5 | `bd74b21f46aa51c6d535680a005682e2572d6965`; run `38316421524` | User retested: good foveal shading, worse peripheral shading, twitchy gaze; historical hitching reference. |
| Joey DuoView Build 19 | `ce9c9abc67ec0dafa48634ae7a3a443377616de5`; run `38525471273` | User reported working gaze-driven fovea and no hitching, but twitching and peripheral shading disparity. |
| v21 Build 26 | `28dae2e13666b4f5513b6666546e8620d0926ce4`; run `38543842360` | Verified Windows package restoring old source order, atlas and gaze mapping; no headset result established here. |
| v22 Build 29 | `bd8024c9e83debaaee6890d36c756f186e8421e1`; run `38557341481` | Latest delivered stability/projection/shading experiment; headset feedback pending. |

Old Injector 5 download: https://github.com/liviutrn/OpenNR/actions/runs/38316421524/artifacts/11777567376

Build 26 download: https://github.com/liviutrn/OpenNR/actions/runs/38543842360/artifacts/11884263766

**Critical correction:** earlier recollection that the old build had perfect shading in both sources was superseded by the user's retest. Do not repeat it. Shading/twitching were also present in the old reference. Good shading in both eyes with global Native Stereo Fix was specifically confirmed in **Native Stereo ID0**, not DuoView ID6. User had suggested view0 for fovea and view1 for periphery; this is now the default.

Old public backend pin was `praydog/UEVR@4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d`. We restored its visual integration choices on the current exact Joey base, not its old backend or frame/present gates.

## 5. Architecture and inherited safeguards

Source edits are applied to pristine exact-pinned backend/frontend by scripts in this repository; the repository is not a full copy of the applied private backend dependency tree. Stage 1 adds ID6 with guarded Mono lifecycle. The Stage 2–5 integration enables two source views only for the matching STALKER 2 DX12 OpenXR path.

Producer-side state freezes frame key/generation, settings, output dimensions, full projection, near clip, crop layout and gaze choice. Both source passes use one captured Mono camera. Source rectangle, projection, family and camera observations validate the pair. The foveal pass uses an off-axis cropped projection; periphery uses the full projection. A DX12 raster compositor combines their atlas regions, then the original XR submission path supplies the eye copies.

Fovea occupies the atlas region beginning at x=0; periphery follows the foveal width. Atlas/layout validation constrains admissible density/crop combinations. Effective menu sizes matter more than slider requests.

On an invalid/incomplete pair, ID6 quarantines the two-source renderer and subsequently routes through original Mono inside ID6. The fault frame attempts a current-frame Mono copy but can contain incomplete atlas pixels. Do not promise an invisible fault frame or stale-image fallback. Reselecting ID6 is the documented retry path.

DXBC shaders are compiled offline by actual Windows fxc in CI. PSOs/textures are prewarmed at swapchain setup. No new per-frame shader compilation or GPU waits were added. Format/swapchain reconstruction can still occur; no headset pacing guarantee follows from these safeguards.

## 6. Restored controls/features retained from Build 26

- Default source roles: Unreal view0 fovea, view1 periphery; source selector remains available.
- Old gaze coordinate path restored: PSVR2 device ray mapped to OpenXR -Z, transformed by inverse left **optical** rotation before projection. This is not inverse world-space head pose.
- Persisted quality controls: foveal width/height, density, peripheral scale, blend feather, gaze, border highlight and source diagnostics.
- Old source defaults: crop 0.50 × 0.50, density 1.0, periphery 0.20, feather 0.08, gaze ON, source0. User's favorite historical tuning is unknown; do not present these as personal tuning.
- Width/height sliders reach 1.0; density range 0.25–4.0 and peripheral scale 0.05–0.50 are subject to layout admission. Restore-old-settings button restores the original visual defaults, not a historical personal profile.
- Source diagnostic: 0 blend, 1 periphery only, 2 fovea only/dark outside ROI.
- Menu displays effective sizes, role, gaze validity/UV, freshness and pixel budget.
- Optional GPU timing, default OFF, measures compositor plus both-eye copies, **not full Unreal rendering**. Query resources/frequency prewarm during setup. Record/read only while enabled, on retired command slots, without added waits. The setting is frozen per source frame.

## 7. New Build 29 modifications

### A. Crop-origin stability

New `DuoViewCropStability.hpp`, connected through immutable state/config and UI. UI `Stable gaze crop (OpenNR r10 policy)` defaults ON and is persisted; crop guard is adjustable from 0–5% of crop extent, default 5%.

Inspected reference: `experiments/cheeky-psvr2-r10`, `CheekyPort/overrides/src/OpenNR_R10_GazeCropPolicy.h`, attribution commit `3a403d6fea9cc73818b1cdd7473bd6fd9cb5cb98`. Cheeky override logic preserves compatible overlapping crop history with backend motion handling.

The new policy holds the old origin while desired movement stays within `min(0.02 full UV, crop_extent × guard_fraction)`. Larger movement recenters immediately. Repositioning aligns to the actual foveal source pixel grid, nominally four source pixels; small guards can reduce the step. Guard zero retains nominal four-pixel alignment. Edge clamping can clip alignment but remains bounded. It uses rounded source dimensions, including fractional density and non-square output; tests include density1.8 at3400×3172.

There is **no OneEuro filter, extra temporal smoothing, slew or fixation-time slider**. An initial redundant smoothing control was removed before final delivery. Do not describe the final build as smoothing gaze with a 12ms filter.

Missing/invalid gaze can hold the last crop position for100ms after the last usable read, while `gaze_valid` stays false. CAPI's existing50ms sample/cache policy is unchanged. These are separate intervals, so do not equate ROI hold with fresh sample validity. After expiration it returns to center. No old image or pose is reused.

Resets occur on generation, output size, crop extent, density, source role or clock rollback. Policy changes are staged and committed only with accepted frame state; rejected/out-of-order frames cannot corrupt accepted crop state.

### B. Actual projection coherence repair

Confirmed defect in the preceding integration: `State::begin` froze a projection, but the actual projection hook updated the runtime and reread its live projection before applying the crop. The rendered projection could therefore differ from the packet used by gaze/composition.

Build29 `apply_frame_projection` copies all16 frozen matrix elements into both actual Unreal view projections, then applies the crop only to the selected foveal view. Near clip is captured once and validated. Nonfinite projections are rejected. Joey's existing runtime update remains for lifecycle compatibility; its live matrix no longer overrides the packet basis.

Unreal still owns current/previous ViewStates, temporal histories and native velocities. Compatible crop translations keep dimensions/resources stable and do not cause our own resets. Tests check world-point reconstruction, previous/current local-UV displacement and frozen-matrix behavior. They **do not verify STALKER 2 velocity textures or Lumen/TSR history in the headset**.

This is not a full Cheeky DLSS history port. Adding Cheeky's post-render crop velocity correction here could double-compensate because DuoView already changes the native render projection. No guessed `PrevViewInfo`, raw velocity texture mutation, or per-frame camera cut was added.

### C. Runtime-only independent-primary shading experiment

UI label: `Independent primary shading (experimental, runtime only)`. Default OFF on every injection and rendering-method transition; deliberately omitted from persisted options. User can enable it after ID6 settles.

At the matching main viewport FSceneView constructor, retain normal source eye/index/state selection. For the secondary constructor only, require family count1, readable/nonzero distinct source ViewStates, both source rectangle/projection observations, captured Mono camera and the current frame's latched toggle. Temporarily relabel SECONDARY as PRIMARY. The existing constructor scope guard restores init options afterward. UI records whether adaptation actually applied or is waiting for safe evidence.

The family list/count and ViewState pointers are not hidden/remapped. No separate capture target, separate BeginRenderViewFamily transactions, frame-count decrement or XR copy reroute is introduced. Off is latched for the next producer frame.

**This is not the full global Native Stereo Fix.** That original implementation also changes family handling/render transactions/capture behavior and stays gated to Native Stereo ID0. Do not globally enable it in ID6. The constructor-only experiment might improve primary-dependent lighting, but paired-primary rendering and shading parity remain untested in-game. It may have no effect or regressions; UI “applied” means the constructor change occurred, not that shadows are correct.

## 8. Source files and build workflow to inspect

At compiled source `bd8024c9e83debaaee6890d36c756f186e8421e1`:

| Files | Role |
|---|---|
| `.github/workflows/duoview-joey-stage234.yml` | Exact checkout, patches, Windows tests/build, identity verification, package/upload |
| `duoview/clean_restart/baseline.lock.json`, `verify_exact_baseline.py` | Original pins, SDK completeness and provenance |
| `duoview/joey_stage1/apply_stage1.py`, `verify_stage1.py` | ID6 and guarded baseline patch |
| `duoview/joey_stage1/apply_stage234.py` | VR UI/settings/lifecycle, actual source camera/projection hooks, constructor toggle, DX12 copy integration |
| `duoview/joey_stage1/verify_stage234.py` | Allowed changed paths, unchanged SDK, source hashes, required production integration |
| `duoview/DuoViewConfig.hpp`, `DuoViewState.hpp` | Frozen settings/frame state, source evidence, guards, projection helper |
| `duoview/DuoViewCropStability.hpp` | New crop stability policy and Windows macro fix |
| `duoview/DuoViewGeometry.hpp`, `DuoViewGaze.hpp` | Atlas/frustum geometry and gaze projection |
| `duoview/PSVR2NativeGaze.hpp`, `DuoViewPSVR2Gaze.hpp` | CAPI and optical gaze path |
| `duoview/DuoViewD3D12.hpp`, `DuoViewMonoCopyD3D12.hpp` | Composition, copies, prewarm/timing |
| `duoview/DuoViewComposite.hlsl`, `DuoViewCompositeRaster.hlsl`, `embed_shader.py` | Source blend and offline shader compilation |
| `duoview/joey_stage1/ProductionContractTests.cpp`, `ProductionPSVR2GazeTests.cpp`, `ProductionWarpPinned.cpp`, `CMakeLists.txt` | Tests against actual applied headers |
| `duoview/stage2_geometry_tests.cpp`, `stage4_gaze_tests.cpp`, `stage5_frame_tests.cpp`, `stage8_config_tests.cpp`, `stage10_state_tests.cpp`, `production_warp_test.cpp`, `CMakeLists.txt` | Independent CPU/WARP tests |

Applied backend files of special interest: `src/mods/VR.hpp`, `VR.cpp`, `src/mods/vr/FFakeStereoRenderingHook.cpp`, `D3D12Component.hpp/.cpp`, injected DuoView headers. Frontend changes add the ID6 option to matching original frontend/tests. Follow the allowed-path sets in the verifier for the exact complete applied file list.

Other older public-SDK/reconstruction scripts remain in repository history; they are **not the active Build29 build path**. Read workflow paths before applying a similarly named older script.

Related reports: `duoview/reviews/OLD_LOGIC_NATIVE_FIX_INVESTIGATION_2026-10-14.md`, `OLD_BEHAVIOR_V21_RESTORATION.md`, `TEMPORAL_SHADING_V22_HANDOFF.md`. Older “running/pending” entries are historical checkpoints; their final delivery sections supersede them. This document gives the consolidated current status.

## 9. Validation evidence and exact package hashes

Independent final job-log inspection confirmed **3 pinned + 6 independent + 41 original compatibility tests = 50 passed**, no test failures. Pinned tests include CAPI projection/validation and DX12 WARP. Original frontend tests/build, full backend and auxiliary DLLs, final source-identity comparison and upload all passed.

Downloaded archive checked independently: outer/inner ZIP CRCs, inner checksum sidecar,14 package entries, required injector files, original pin metadata,17 applied backend source hashes (excluding generated shader header), every packaged frontend source hash, and all3 DLLs as AMD64 PE32+. Outer digest matches GitHub artifact metadata. CI's final hash check confirms source remained unchanged through compile, including the generated shader source.

| Item | SHA256 |
|---|---|
| Outer artifact ZIP | `377023d903c336d0a0b732586a8ed1c076ac99f9a93217ee233d3910f9acba7a` |
| Inner injector ZIP | `f01a77181fe06d41202f6dbfb484fd9d2d17a60ef7519980425d98dda3d32caa` |
| `UEVRBackend.dll` (16,296,960 bytes) | `a8811ad707387e9b2f402079fe11e0b968f9cae5ac9f36226f072a306e5fb076` |
| `LuaVR.dll` | `e73f851d029e4c9d5d13d04901b0d33dc977937d1241087fc76c8b09cb00e754` |
| `UEVRPluginNullifier.dll` | `7928efdae7e2fbb5cfa47c84c684b788aef01ca1ae4763471bd3b7ed03a05b46` |

Evidence artifact ID11890993211 contains source/test provenance, not the injector. Do not give it as the build download.

Local portable tests/contracts passed too. Exact patches were applied to fresh original-source worktrees for hash comparison. Linux shader subprocess was mocked **only for source comparison**; no locally mocked shader was shipped. Actual Windows fxc ran in CI. No local Linux result is claimed as a complete Windows/game test.

## 10. CI history relevant to avoiding repeated mistakes

- Build25 restoration failed due test-only timestamp-frequency declaration ordering. Fixed for successful Build26.
- Initial v22 source `a6ba9c6dfa3c511bd908f363b6e5642a96419982`, run27 `38549696664`, was superseded before delivery.
- Source `688cb6cdc147240140ef02b1c69af813263958a4` corrected foveal sampling-grid alignment and removed redundant temporal filter control; run28 `38550827946` passed50 tests but full DLL compilation failed because Windows `min/max` macros expanded new standard calls. It produced no injector.
- Final `bd8024c9e83debaaee6890d36c756f186e8421e1` parenthesizes `(std::min)` / `(std::max)` calls to prevent macro expansion. Explicit local macro-exposure compilation passed, then Build29 passed the entire Windows pipeline.

Do not “fix” the final code back to unprotected standard min/max calls. Standalone tests can pass while the real Windows include environment fails; always compile the full backend before delivery.

## 11. Headset test and next engineering decisions

1. Extract Build29 separately; keep Build3/Build26 installations intact. Run STALKER2 DX12 with SteamVR as OpenXR runtime and calibrated Toolkit gaze.
2. Choose ID6, match preferred crop/density/peripheral settings. Keep source diagnostic0, stable crop ON, shading OFF. Restore-old-settings can clear inherited visual tuning, but defaults are not the user's favorite settings.
3. Compare fixation, rapid gaze moves and head movement. Distinguish crop-border movement from rendered-content jumps, shimmer/ghosting and shadow changes. Toggle crop stability OFF for a matched comparison.
4. After ID6 settles, enable **Independent primary shading**. Observe applied/waiting status, compare periphery shadows/lighting and frametime. Disable it to verify reversal. Mode transitions reset it OFF.
5. If needed, use periphery/fovea source diagnostics. Optional GPU timing measures only blend/eye-copy overhead. Use original Mono ID5 as control and Build26 for before/after.
6. Record periodic hitches, startup crash, quarantine, content jump, gaze-loss behavior, history artifacts and longer-session stability. CAPI/WARP/CPU tests cannot replace this.

If shading improves and pacing remains good, validate multiple scenes/transitions before proposing defaults or production promotion. If the toggle regresses, keep it off and diagnose safe pair evidence/engine assumptions; do not blindly port the full Native Fix capture machinery. If image jumping persists, determine whether geometry, source pairing, engine temporal history, CAPI sampling or compositor mapping is implicated before adding filters or motion offsets.

No further implementation was authorized by the final user message; it asks for this handoff to continue in a new chat. Avoid unrelated development or duplicate speculative builds. Ask only for missing information that affects the next concrete step.

## 12. Workspace and continuity notes

All delivered code changes are committed remotely on the isolated v22 branch. Local worktree status can look dirty because code was committed through GitHub APIs rather than by moving the local HEAD; this is not evidence the delivered source is uncommitted. Fetch/compare before resetting anything.

Original scratch root: `/workspace/scratch/1b49e46a830d`. Relevant local worktrees: `DuoViewNext` (patch source), `JoeyV22Verified` and `FrontendV22Verified` (fresh exact applied source used for final hash comparison). Earlier `Joey`, `Frontend`, `JoeyNext`, `JoeyV22Final` etc. are prior comparison/iteration trees, not authoritative final source. Scratch may disappear; GitHub source and artifacts are authoritative.

Downloaded verified artifact scratch path: `/tmp/Joey-DuoView-Temporal-v22-29-artifact.zip`; inspection script `/tmp/inspect-duoview-artifact.py`. Neither is required to resume because exact download/source/hashes are recorded above. Do not include restricted SDK source or credentials in a handoff ZIP.

Suggested next-chat opening: “Continue DuoView from this Build29 handoff. Verify the exact GitHub source and artifact first, preserve Joey Build3 and Build26, and incorporate my latest headset results before making the next change. Build29 is Windows-verified but not yet headset-validated.”
