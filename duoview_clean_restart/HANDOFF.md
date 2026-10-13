# DuoView Mono — clean Joey restart (source-of-truth)

**Status:** NEW clean branch. **No DuoView engine changes are authorized on this branch until the exact baseline has been built and demonstrated to retain its smooth STALKER 2 behavior.**

## Fixed user goal
On STALKER 2 / PSVR2 / SteamVR OpenXR / DX12:
- Preserve the smooth recent Joey backend, including all original working modes and application frame cadence.
- Add a separate DuoView Mono rendering mode: TWO actual Unreal views of ONE mono camera pose, low-resolution full-FOV periphery plus eye-tracked high-density fovea, composited into a single mono image shown to both eyes.
- No OpenXR runtime-switching, sequential stereo/quad views, raw atlas presentation, speculative memory offsets, asynchronous retained wrong-frame images, or visible seam jitter. PSVR2 Toolkit gaze should be head-local and latched once per producer frame.
- User must receive fully compiled Windows injector from GitHub Actions and not compile locally.
- **No recurring 1–2-second loss of scene / SteamVR background & controller interruptions in any mode.** This is a hard release gate, not a performance optimization.

## Verified headset facts
1. The user tested the unmodified preserved Joey original baseline: **no periodic hitching**.
   - Exact preserved `UEVRBackend.dll` SHA256: `19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966`.
   - Original binary embeds or identifies commit `5ac7edc207866569334175e4ed8a7517971547f6` (October 11, 2026). The associated preserved control ZIP in prior chat was called `Joey_Unmodified_Baseline_UEVR_5ac7edc.zip`.
   - The official latest published Joey release (verified October 13) is https://github.com/joeyhodge/UEVR/releases/tag/101226HELLRAISERp1; tag commit `387ccb744b57387b438bab7027fd017a23df66a8`, a cherry-picked, **not identical DAG**, version of the Hellraiser fix. Never silently equate these two commits or their DLLs.
2. The old integrated DuoView Injector-5 and v13 really render foveated image in headset. User confirmed high-resolution fovea and deliberately reduced periphery and prior working PSVR2 gaze.
3. **v14 explicitly FAILED HEADSET TEST.** Same repeated 1–2 second scene dropouts as v13. User's screenshot shows UEVR status `Mono (Experimental): Waiting: DuoView resource/format or GPU submission failed`, with SteamVR CPU/GPU frame-timing intervals where application work drops out. The SteamVR background and controllers appear during lost scenes. V14 DX12/GPU integration reportedly records only ~0.112 ms for compositor+eye copies (last completed slot); a tiny compositor duration does not prove healthy frame submissions.
4. External Joey-original plugins builds 61/69/73 never achieved sustained actual paired rendered composites despite active hooks and loaded menus. They are NOT a proven alternative renderer.
5. v13 tried unconditional post-present DX12 graphic-memory bookkeeping; failed to remove hitches. v14 preserved pose evidence for repeated frame updates, removed order constraint, added log; CI passed and **user says hitches are unchanged**. Do not continue v15 patches of old source.

## Why old project cannot be a foundation
The integrated renderer was a mixed-port, **not** a direct modification of Joey's October 11 current backend:
- `praydog/UEVR@4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d` (August 30 engine).
- `joeyhodge/UEVR@becc96692839f0087ccef238f03af618051fb765` and `@db6729dd9f5745705b1cdec2ec6f51bdc9570983` (September 26 Mono code, manually ported).
- `elliotttate/UESDK-RenderDoc@418729025bad57b094bf6b2e2b55734454c97de6` (July 9 public SDK).
- `joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091` (September frontend).
- Our DuoView view-family/gaze/composition code added October 12–13.
The user reasonably suspects the August public engine and/or Mono port is incompatible with recent STALKER 2 patches. This is a *hypothesis*, not proven root cause.

The old August+ported-Mono-only control (NO DuoView) compiled successfully (CI https://github.com/liviutrn/OpenNR/actions/runs/38431096553, release https://github.com/liviutrn/OpenNR/releases/tag/duoview-mono-only-control-build-3). It has NOT been headset-tested. Do not use it as the new foundation.

## New fixed baseline (do not silently change)
GitHub: https://github.com/joeyhodge/UEVR
**Pin directly to user-tested source commit** `5ac7edc207866569334175e4ed8a7517971547f6` until clean reference reproduction succeeds.
Official release `101226HELLRAISERp1` tag commit `387ccb744b57387b438bab7027fd017a23df66a8` is a separately tracked candidate, NOT interchangeable without binary/source parity checks.
The commit `5ac7...` has Git submodule `dependencies/submodules/UESDK` pinned to `3cffbc82429b6165ceec2714f0f0d9ae48f55596`; URL is `https://github.com/joeyhodge/UESDK.git`. It returned GitHub 404 for our current connection and is NOT a reproducible public dependency.
**Do NOT just substitute the July 2026 public SDK to make builds pass**; that is the key mistake in the old project. We must find a source-compatible public SDK baseline or independently verify each needed interface/header, and then recompile/test the *UNMODIFIED recent Joey* before adding DuoView.

### Phase 0 — Baseline provenance and reproducibility
- Use the official *user-tested preserved* Joey DLL as the byte-for-byte control. Compare exact DLL SHA and release files, noting non-DIBR/DIBR variants explicitly. The packaged 16,240,640-byte `UEVRBackend.dll` may originate from an official DIBR artifact; verify by **SHA, not filename/size alone**.
- Checkout `joeyhodge/UEVR@5ac7...`, inspect compiler CMake, all real dependency versions and gitlinks. Fail closed if Joey private UESDK is unavailable; report actual missing headers/symbols without inventing definitions.
- Produce a Windows CI baseline compile with **zero DuoView source changes** and user-test that compile against the same STALKER 2 version. This is a non-negotiable gate.

### Phase 1 — Minimal DuoView pipeline without replacing existing runtime
- Keep current Joey's core `xrWaitFrame`, `xrBeginFrame`, `xrEndFrame`, original presentation, and GPU fence lifetime intact, unless absolutely required and proven by source and regression tests.
- Add a separately switchable mode 6 in backend, with exact source-based Unreal engine views (both same camera pose; high-density gaze crop and low-detail full-FOV view).
- If no verified way to render 2 cropped Mono views in latest source, stop and prove that missing interface before attempting GPU compositor.
- Avoid external ABI-inline-hook plugin experiment: its previous proof gates prevented any sustained composition.
- First confirm 1 true completed composite, then stable native fallback and mode transitions, then gaze tracking. No fake success counters.
- Only re-use layout math, view-building algorithm, gaze frame latch, shader/compositor helpers from original integrated success, **after architecture review and adaptation to current source.** NEVER wholesale cherry-pick the old Mono/OpenXR transaction port.

### Phase 2 — Quality/performance and safe publication
- PSVR2 gaze moves fovea correctly; no eye-gaze flicker/regeneration.
- Crop width and height 0.3/0.5, peripheral scale 0.2 and adjustable foveal density with actual render rectangles and measurable GPU savings.
- Long STALKER 2 test with no scene dropouts, no controller reappearance, no blackscreens/mode side effects, no controller input regressions. Unmodified Native/Stereo and original Mono remain unchanged.
- CI sources and commit SHA pinned; tests run full DX12 WARP copy including resource ownership/fence, view/projection consistency, frame cadence, restarts and settings.
- Archive exact DLL and logs, hashes and handoff. Never confuse CI passing with headset success.

## Historical links
Working prototype commit: https://github.com/liviutrn/OpenNR/tree/bd74b21f46aa51c6d535680a005682e2572d6965/duoview
Its source handoff: https://github.com/liviutrn/OpenNR/blob/bd74b21f46aa51c6d535680a005682e2572d6965/duoview/HANDOFF_CHATGPT_WORK.md
UI/render patch integration: https://github.com/liviutrn/OpenNR/blob/bd74b21f46aa51c6d535680a005682e2572d6965/duoview/apply_public_duoview.py
GPU compositor and tests in same historical directory.
v13 proven fovea but failed stability: https://github.com/liviutrn/OpenNR/releases/tag/duoview-working-prototype-stability-v13-build-10
v14 CI successful **but user headset failed**: https://github.com/liviutrn/OpenNR/releases/tag/duoview-proven-frame-pacing-v14-build-12
Exact August+Mono-only control: https://github.com/liviutrn/OpenNR/releases/tag/duoview-mono-only-control-build-3
External plugin failed: https://github.com/liviutrn/OpenNR/releases/tag/duoview-owned-copy-v12-build-73

## Immediately useful instruction for next Work chat
"Start clean from Joey @5ac7edc..., on the new experimental branch. First resolve exact UESDK source reproducibility and compile **unmodified** latest known-smooth Joey without any DuoView. Then reuse only verified foveation techniques of original Injector-5. All old v13/v14 code is historical. Do not merge the old August source, do not switch to an external hooking architecture, and do not ask for frequent unvalidated headset testing."
