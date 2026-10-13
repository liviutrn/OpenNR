# DuoView Mono — revised engineering handoff and continuation plan

**Updated:** 13 October 2026, following the user's 10:36 Europe/Bucharest report.  
**Repository:** https://github.com/liviutrn/OpenNR  
**Runtime baseline:** `DuoView-Experimental-Windows-Injector-5`, compiled source `bd74b21f46aa51c6d535680a005682e2572d6965`.  
**Active baseline branch:** `experiments/duoview-uevr-v07-stalker-publicsdk`.  
**Status:** DuoView's visible foveation features work through Native Stereo bootstrap. Cold startup, ordinary Mono and periodic frame pacing remain broken or unreliable. **This is not yet a stable build.**

## 1. Read this first — the corrected direction

The original public-backend DuoView injector must be preserved. The user has now tested it and reports that its fovea, reduced peripheral resolution, eye gaze and increased foveal resolution work great. Do not discard that renderer or restart the project because the first injection crashed.

Deleting the old STALKER UEVR profile allowed a successful launch, but **did not permanently resolve startup**. A later launch produced the same Unreal DX12 Present error. The user's more precise finding is that injection works when initially selecting **Native Stereo**, followed by switching to **DuoView Mono**. Ordinary Mono produces a black screen. The old “profile deletion fixed the crash” conclusion is therefore superseded by a narrower bootstrap-dependent result.

The user also reports clockwork-like hitches in **every tested mode**, not just DuoView or eye gaze. Prioritize shared startup, presentation, runtime synchronization and persistent transition state. Do not begin by changing gaze smoothing, crop geometry, foveal density, feathering or the compositor's visual behavior.

The parallel Joey-preserving plugin was built during the initial crash investigation. It is a fallback experiment, **not the package the user tested successfully**, and has no game validation. Do not redirect the user to it as the new baseline without evidence that the original backend cannot be stabilized.

## 2. User intent and behavior to preserve

Render two real Unreal views of a single monoscopic camera pose: a full-FOV low-resolution peripheral view and a gaze-centered high-resolution foveal crop. Composite one full Mono image and submit it correctly to both OpenXR eyes. Preserve 6DoF, the shared optical basis, immutable per-frame gaze/settings, same-producer-frame composition and the native PSVR2 Toolkit bridge. No stereo depth, deliberate gaze smoothing or deadzone is requested.

The user cannot compile locally. Functional revisions need complete Windows GitHub Actions builds and an installable artifact or clearly experimental public prerelease. Keep OpenNR `main`, existing OpenNR releases and the user's original Joey installation separate.

## 3. What is established, and what is not

| Area | Current evidence | Remaining limit |
| --- | --- | --- |
| Windows compilation | Original Injector-5 compiled and packaged successfully | Compilation does not establish startup stability |
| Native → DuoView | User reports a working injection/switch route | Repeatability and exact initialization milestones are not recorded |
| Foveal image and peripheral reduction | User says they work great | No GPU capture proving all scene passes use the intended rects |
| PSVR2 gaze | User reports it works in this DuoView build | No independent calibration, latency or frame trace measurement |
| Increased foveal resolution | User reports the visual improvement works | No new quantitative PPD or GPU savings measurement |
| Ordinary Mono, ID 5 | User reports a black screen | Exact startup/switch sequence and gate rejection reason are missing |
| Direct startup in requested Mono/DuoView | User says Native Stereo is required initially; another Present crash occurred | Exact failing Present hook/layer/device cause remains unknown |
| Periodic hitches | User reports them in all tested modes; SteamVR screenshot shows a repeating pattern | Fresh Native-only process versus modes after a Mono transition is not distinguished |
| Old profile | Removing it allowed one successful launch | Responsible setting unknown; deletion alone is not a complete fix |

No fresh `UEVR.log` from the successful post-reset/hitching session has been supplied. Two original Unreal crash-report sets and one SteamVR timing screenshot are available. The latest launch crash is a textual report, **not a third supplied minidump**.

## 4. Exact original build and source provenance

- Build: https://github.com/liviutrn/OpenNR/actions/runs/38316421524
- Compiled workspace source: `bd74b21f46aa51c6d535680a005682e2572d6965`.
- Artifact: `DuoView-Experimental-Windows-Injector-5`; artifact ID `11777567376`.
- Original ZIP SHA256: `bf48e0ba7644182717e214d5acc5b14b6934978174777a643d9edbf7c95d9cdc`.
- Original backend file SHA256: `3b5f2677d3d2f25e6ad0739215ef9d61671db375e4d915a781176a5ad003917c`.
- Backend: public Praydog UEVR `4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d`.
- Public SDK: `elliotttate/UESDK-RenderDoc` `418729025bad57b094bf6b2e2b55734454c97de6`.
- Frontend: `joeyhodge/uevr-frontend` `60be4b0f9a646109fd9fdf448bacd41477234091`.
- Rendering IDs: Native Stereo `0`; ordinary Mono `5`; DuoView Mono `6`.
- Branch documentation head at this analysis's start: `8880adfae87eb621fcfe6c6a8372797b2a0f56cb`; its intervening changes were documentation, not a new injector.

Build transformations are `duoview/apply_public_mono.py` plus `public_mono.patch`, followed by `apply_public_duoview.py`. The workflow is `.github/workflows/duoview-public-backend.yml`. Do not confuse these with the earlier private-SDK compile probes or the newer standalone plugin workflow.

## 5. Crash evidence

Both supplied crash sets report UE 5.5.4 / DX12 on the RTX 5070 and:

```text
PresentInternal(SyncInterval) failed
D3D12Viewport.cpp:596
D3D12Util.cpp:1033
error 80004004
```

`0x80004004` is E_ABORT. It identifies an aborted Present result, not a specific bad resource, driver defect or hook root cause. Preserve the HRESULT; do not hide it with S_OK or retry indiscriminately.

Direct parsing of the two minidumps' ModuleListStreams established that both loaded the original experimental UEVR backend, `CheekyFoveatedDLSS.dll`, `CheekyFoveatedDLSSRuntime.dll` and `CheekyOpenXRLayer.dll`. The first additionally loaded `ReShade64.dll`; the second did not. ReShade is consequently not necessary for the earlier observed failure. The presence of a module does not prove it caused the failure, or that its feature was enabled. Likewise, loaded frame-generation DLLs do not prove active frame generation.

The latest recurrence plus the Native-first workaround strengthens the case for inspecting initialization and mode-dependent state. It does not prove that every historical crash has the same internal cause.

## 6. Source findings that should drive the next investigation

These are source observations. Their contribution to the reported behavior has not yet been established by runtime traces.

### A. Existing startup fallback is incomplete as a readiness contract

`Selection::initialize` in the ported Mono policy already initializes a requested Mono/DuoView method with active Native Stereo, leaving the target requested and pending. Therefore “set the initial active mode to Native” is **not a complete new fix**; part of that policy already exists.

`VR::service_mono_transition_present` principally waits for GPU consumers to retire. `mono_consumers_retired` can report true before meaningful rendering resources/frames exist. The game-thread transaction can consequently commit the requested method without proof that the title's native initialization, main family, source target and OpenXR submission are usable. Inspect this ordering rather than introducing an arbitrary startup delay.

The public port calls `m_fake_stereo_hook->on_frame()` before `service_mono_transition_present()`. Do not incorrectly describe it as entirely skipping the hook initialization call. The concern is the readiness criteria and interaction with pending/quiescing guards, not that specific call being absent.

The user's manual Native-first route is the working behavioral reference for an eventual automatic bootstrap state machine.

### B. Ordinary Mono and DuoView differ in view-index handling

The public base's stereo offset function has persistent `index_starts_from_one`, `index_was_ever_two` and `index_was_ever_negative` state. It can ignore raw index 0 after observing index 2. `apply_public_duoview.py` explicitly bypasses that old guard for DuoView and uses its precision-aware 0/1 view mapping. Ordinary Mono does not receive all of those DuoView-specific changes.

That is a concrete code difference to investigate for the ID-5 black screen. Record actual raw indices, double-precision detection, full-pass classification, callback masks and main-family view count. Do not blindly force 0-based indexing in every UE game.

### C. Frame validity may explain a Mono black screen

`OpenXR::note_mono_main_family` and `has_mono_frame` require matching pose/projection/generation and a validated main family. The DuoView integration expects two views for ID 6 but one for ID 5. If STALKER keeps a cached two-view family, or a callback is skipped/misclassified, ordinary Mono may be intentionally withheld despite a live game.

`update_poses` resets the gate entry for the frame slot; inspect repeated pose updates with the same frame number after callbacks have already marked projection/family validity. That is an ordering candidate, not a demonstrated reset bug.

Differentiate “missing rendered source” from “valid source rejected by metadata.” Keep stale-frame protection while repairing the actual producer/consumer association.

### D. Post-present gating suppresses unrelated housekeeping

The Mono patch makes `D3D12Component::on_post_present` return before the original body when transition guards or `m_mono_block_post_present` are active. `on_frame` sets `m_mono_block_post_present` from `mono_generation() != 0`.

The original body contains both `m_graphics_memory->Commit(command_queue)` **and** real-backbuffer clearing. Thus the new guard suppresses graphics-memory housekeeping as well as the operation it intended to guard. A nonzero generation persists after mode changes, so it is unsafe to assume this impact is confined to the current mode being Mono.

Audit separating required memory commit/retirement from mode-specific backbuffer clearing. Check allocation growth and commit cadence. This is a high-value, narrowly scoped correction candidate, but it cannot explain a genuinely fresh Native-only hitch by itself if the generation remains zero.

### E. Transition validity can extend into a non-Mono mode

`needs_frame_gate` returns true for Mono methods **or** when the current generation differs from the ready generation. The ready-generation and main-family rules need a complete exit transaction. After entering and leaving a Mono method, a currently selected Native mode can still be affected by the port's bookkeeping.

“All tested modes hitch” is accepted as the user's observation. To interpret it, distinguish a fresh Native-only run from Native selected after a DuoView/Mono transition. Do not dismiss the user's report, and do not infer a clean native path merely from the current menu label.

### F. Shared waits and Present parameters need measurement

The base DX12 OpenXR copy path waits for swapchain images and command-context fences. Those ownership barriers are required; removing them is not a safe hitch fix. Instrument their durations and distinguish game/GPU work from CPU waiting or missing app submissions.

The base Present hook can override SyncInterval and change DXGI Present flags. The Mono/DuoView port does not independently overhaul that shared hook. Record caller versus effective parameters, original versus replacement swapchain, queue/device identity, frame-generation state and failure results. Newer Joey code has other presentation safeguards, but do not assume an unrelated title's guard fixes STALKER or E_ABORT.

### G. Gaze and shader compilation are lower-priority hitch explanations now

The compositor caches its shader/pipeline/resources per retired command slot for stable dimensions/device/format. Persistent shader recompilation is not established by this path. Log rebuild counts if allocation churn is suspected.

The Toolkit bridge retries failed initialization at one-second intervals. That was a reasonable early candidate when only DuoView was reported to hitch. The user's cross-mode result makes it a lower-priority explanation for the common issue; do not make another gaze-off test the first prerequisite.

## 7. Revised execution plan

### Phase 1 — preserve and establish controlled runs

Archive Injector-5 and save the current profile that permits Native → DuoView. Retain the older failing profile only if available; never reconstruct it from guesses. Record backend hash, requested/active method, synchronization settings, frame-delay compensation, game version, final resolution and active plugins/layers.

Collect a short fresh-process run that stays Native Stereo without entering Mono/DuoView, a separate Native → DuoView run, and a precisely labeled Native → ordinary Mono attempt. Obtain `UEVR.log` for success, hitching and failure. Existing Unreal crash reports do not replace it. Compare with the user's known-working Joey package under the same scene/settings when needed. Isolate third-party layers/plugins through reversible backups in a separate comparison, rather than deleting the user's normal setup.

**Decision:** if fresh Native-only hitches before any Mono transition, prioritize shared presentation/runtime/engine paths. If hitches appear or change only after a transition, prioritize leaked mode state and housekeeping. If unmodified Joey also shows the same periodic pattern, include the game/runtime/driver/add-on environment in the investigation.

### Phase 2 — one bounded diagnostic build on the original backend

Keep the working DuoView visuals unchanged. Add timestamped, buffered diagnostics at actual boundaries:

- requested/active method, bootstrap state, generation and ready generation;
- main-family count/identity, raw view indices, projection/rect/camera masks;
- producer, render-thread/RHI and submitted frame numbers;
- explicit rejection bits for pose, projection, family, generation, source and copy;
- XR WaitFrame/BeginFrame/LocateViews/acquire/wait/release/EndFrame durations and results;
- command-slot fence waits, queue/device/source descriptors and recreation counters;
- Present duration/HRESULT, original/effective flags/interval and device-removed reason;
- graphics-memory commit count/allocation statistics where the bundled API supports them.

Use one monotonic clock across threads, a bounded event ring, aggregated periodic output and spike-triggered snapshots. Avoid per-frame synchronous file I/O, captures, driver probes or forced GPU synchronization that could create the hitch being measured. Do not log “successfully rendered” merely from two callbacks or command recording.

### Phase 3 — reliable cold bootstrap and mode transitions

Design explicit states: Native bootstrap → verified native-ready → quiescing/retired consumers → committed target mode → first valid target frame → steady state. Add reset/recovery and a defined exit path.

Require observed stable native main-view rendering, valid source/pose/projection and a successful native XR submission before switching to a startup-requested DuoView. GPU fences being idle alone is insufficient. Preserve the requested method in the profile while using Native only as temporary bootstrap; the user should not have to inject Native and click DuoView every launch. Define failure behavior and useful status instead of a silent black screen. Do not implement this as a fixed sleep or fake successful Present.

### Phase 4 — repair ordinary Mono and shared housekeeping

Use captured indices and family counts to repair ID 5's single-view selection, projection and submission. Keep ID 6's confirmed two-view path intact. Audit cached local-player/view-count initialization and repeated pose-gate resets. Restore required post-present memory housekeeping while guarding only operations that actually endanger the Mono source. Retire/reset ready-generation state cleanly on exit, reload and device reset.

Make separate, small changes with trace-backed explanations. A source defect that can be isolated independently may be fixed without waiting for every possible diagnosis, but do not label it the proven hitch root cause without correlated game evidence.

### Phase 5 — fix the measured common hitch and validate

Use the diagnostic timeline to patch the dominant periodic wait, missed submission, resource-recreation cycle, state leak or Present-parameter problem. If it is external to this backend, document the controlled comparison and apply only the supported remedy. Preserve all required barriers/fences.

Run the existing six portable/production WARP checks, targeted tests for the changed transition/index/housekeeping logic, strict source patch checks and the full Windows DLL/injector workflow. Publish an experimental artifact with exact source provenance and clear test instructions. A compiler pass is not final acceptance.

## 8. Acceptance criteria

1. Repeated cold starts into requested DuoView without manual Native-first intervention; record success/failure counts, not just one successful launch.
2. Native Stereo remains usable in a fresh process and after every supported mode switch.
3. Ordinary Mono produces a current centered 6DoF image, or is explicitly unavailable with a clear reason until repaired; no silent black screen.
4. Native ↔ DuoView ↔ Mono transitions, runtime reload, scene loading and device/resource recreation preserve frame ownership and do not hang or crash.
5. The reported periodic hitch disappears or is materially reduced under a documented same-scene test, with p50/p95/p99 frametimes, missed submissions and long-wait counts. At 120 Hz the native budget is about 8.33 ms; separate average over-budget rendering from additional periodic stalls.
6. The user's working fovea, reduced periphery, gaze, density controls and shared-pose image remain correct. No gaze smoothing/deadzone is introduced as a pacing workaround.
7. No unmeasured FPS/PPD gain is claimed; no old/stale atlas or fabricated pose is submitted to make a graph appear smoother.

## 9. Parallel Joey plugin — preserve, do not confuse with Injector-5

Branch: `experiments/duoview-uevr-v08-joey-plugin`.

- Published prerelease: https://github.com/liviutrn/OpenNR/releases/tag/duoview-joey-plugin-v08-build-3
- Final build: https://github.com/liviutrn/OpenNR/actions/runs/38360520420
- Compiled commit: `5da78be30c11b2b209fb0596a5cb9e7fe6446f3d`.
- Package ZIP SHA256: `d9af7e3c0831a5a9f75f4facc25e52b30ad7e4541091e0c322115883810d71d7`.
- Plugin SHA256: `e1f1f2f8bf238ecc64bd344a8724e5a0542562888621a878285bfb52c42546d9`.
- Preserved official Joey Mono backend SHA256: `19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966`.

That package keeps the official released backend unchanged, builds an adjunct plugin against public headers, and uses exact-release binary hash/prologue/operand guards. Modes 0/1/2/3 stage diagnostics, shared-pose views, fixed fovea and gaze. All six Windows tests, in-place atlas GPU readback, DLL loadability and plugin exports passed; the 14-entry downloaded ZIP was checked. **None of those results is a STALKER/PSVR2 game test of that plugin.** Its binary adapter is not a substitute for stabilizing the now user-tested source-integrated Injector-5.

## 10. Files and evidence supplied for continuation

The accompanying private evidence ZIP includes this revised handoff/plan, the original complete handoff ZIP, the second crash-report set, the user's SteamVR screenshot, and an original Injector-5 DuoView source snapshot with its workflow. The snapshot is anchored to `bd74b21...`, not the locally modified parallel plugin tree. Original crash reports may contain machine-specific data; the public GitHub handoff omits their bytes.

Important repository paths:

- `duoview/HANDOFF_CHATGPT_WORK.md` — entrypoint/status; this report supersedes old unconditional failure or fixed-profile conclusions.
- `duoview/public_mono.patch` and `apply_public_mono.py` — Mono startup, transition and submission policy.
- `duoview/apply_public_duoview.py` — ID 6, index overrides, immutable view pairs, gaze, compositor integration.
- `duoview/DuoViewState.hpp`, `DuoViewConfig.hpp`, `DuoViewFrame.hpp` — per-frame validity and pairing.
- `duoview/DuoViewD3D12.hpp`, shader files, mono-copy helper and `production_warp_test.cpp` — GPU composition/copy and standalone verification.
- `duoview/PSVR2NativeGaze.hpp`, `DuoViewGaze.hpp` — native provider and optical mapping.
- `.github/workflows/duoview-public-backend.yml` — complete original Windows injector build.
- `duoview/joey_plugin/` and `.github/workflows/duoview-joey-plugin.yml` — parallel fallback only.

**No new functional stability patch or new original-backend injector was built after the latest report.** This turn analyzes and prepares the requested plan/handoff. The next engineer should execute the original-backend diagnostic/bootstrap/housekeeping plan, preserve the confirmed DuoView renderer, and validate the results in-game.
