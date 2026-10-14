# DuoView Mono UEVR — Master Eye-Gaze / Temporal Stabilization Engineering Handoff

**Created:** 14 October 2026  
**Owner/project:** `liviutrn/OpenNR` — DuoView Mono on Joey Hodge UEVR, STALKER 2 DX12 / SteamVR OpenXR / PSVR2  
**Intended audience:** A new ChatGPT Work session and a senior VR rendering engineer directing a junior engineer.  
**Status:** **Implementation plan only.** Nothing in this document establishes a new fixed, compiled or headset-tested gaze-stable build.

> **The assignment:** Stabilize **both** the border of DuoView’s moving eye-tracked high-resolution foveal crop **and** the world image rendered **inside** it, especially during head yaw/pitch while the user fixates a stationary world object. Fixed-center crop is **already perfectly stable in the user's headset testing**. The fovea MUST remain a **genuine separately Unreal-rendered high-resolution off-axis view**—not stretched/upscaled low-resolution peripheral pixels. Preserve fast/immediate saccades. Reuse the **source-backed mathematical and frame-coherence principles** from **OpenNR r10** and **Cheeky Foveated DLSS**. Do not substitute slow smoothing, indiscriminate history resets, guessed Unreal memory offsets, or crash-prone global NVIDIA NGX interception.

---

## 1. Rules of evidence, operator conduct and immediate priorities

Throughout this document:

- **USER-VERIFIED:** Actually observed in STALKER 2 on PSVR2 by user. Strongest real-world evidence, but not a controlled internal GPU trace.
- **SOURCE-VERIFIED:** Read from the specified repository file, branch or pinned upstream source.
- **CI-VERIFIED:** Specific GitHub Actions build, tests, packaging. Not equivalent to headset acceptance.
- **HYPOTHESIS:** Plausible explanation requiring proof from actual UE rendering/temporal state.
- **IMPLEMENTATION PROPOSAL:** What must be designed and verified; does not currently exist.

Do **not** silently convert a hypothesis into a fact. Do **not** tell the user a build is fixed because it compiles. Do **not** ask the user to test every diagnostic change. Preserve source and checkpoint documentation for a new chat if engineering sessions fail. Before any GPU build, examine the **actual generated patched Joey source**, not only the checked-in patch Python and standalone header tests.

**Priority order:** (1) freeze correct source/baselines; (2) determine precise callback order/temporal data and build independent math oracle; (3) correct Unreal foveal **previous-frame** temporal contract if demonstrably wrong; (4) synchronize gaze and head pose; (5) add **small**, nonlaggy OpenNR fixation guard; (6) run comprehensive tests, audit and only then request **one** PSVR2 headset acceptance.

---

## 2. User observations and boundaries

### 2.1 Confirmed observations

- **USER-VERIFIED:** DuoView fixed-center fovea is **perfectly stable**, even with head movement. Do not regress it.
- **USER-VERIFIED:** When gaze tracking is enabled, crop position shakes/trembles/jumps. The **scene image within the moving fovea** additionally jumps, shakes or becomes jelly-like. Most noticeable while moving the head and trying to keep eyes on the same object.
- **USER-VERIFIED:** Earlier smoothing to maximum made border appear less shaky mainly because the crop almost stopped following gaze. This is **unacceptable**; fast eye response is required.
- **USER-VERIFIED:** The old hitching DuoView prototype rendered impressively high-quality/high-PPD fovea, with functioning eye gaze, but had severe 1–2-second hitches. Do not assume that old exact commit is definitively “v14” without tracing provenance.
- **USER-VERIFIED:** Build19 on modern Joey was first usable **no-hitch** DuoView proof of concept; gaze moved but was twitchy; periphery shadows/lighting poorer than fovea. Native-stereo shading fix could help shading but disrupted DuoView when used incautiously; the user wants it as a post-enable in-game toggle.
- **USER-VERIFIED:** Clean unmodified Joey Build3 ran **30 minutes in STALKER 2 Mono ID5 without hitching**. The setup was unchanged. Protect it.
- **USER-VERIFIED:** Prior Build34/35 experiments with NVIDIA/NGX/launch changes caused injection CTD, including `nvapi64_impl`, `_nvngx`, `UEVRBackend` in stack. No valid proof that NGX itself was faulty, but the hook approach is unacceptable risk.
- **USER-VERIFIED:** In OpenNR r10 and in the successful **Cheeky SR crop path**, gaze movement behaved much more stably. Cheeky **NR** has also shown gaze flicker/regeneration; do not claim all Cheeky reconstruction is uniformly stable.

### 2.2 Product goal and constraints

- STALKER 2 DX12 / RTX 5070 / PSVR2 Toolkit + SteamVR OpenXR.
- Two **genuine UE scene views**, same monoscopic camera: **high-density narrow off-axis fovea** plus **low-resolution full-FOV periphery**; DX12 composite a full-FOV Mono image and submit the same to both XR eyes.
- Preserve the quality controls: crop W/H, foveal density, peripheral scale, feather, true source index 0/1, periphery/fovea isolation debug, conditional GPU timing and opt-in independent primary shading.
- Tiny fovea e.g. 0.30 × 0.30 at density 2.5 is an important use case, potentially ~50 PPD in favorable setup; **this performance number is historical anecdote, not a measured Build37 metric**.
- Absolutely **no** simulating the crop by magnifying low-res periphery, no replacing the dual-view approach with full quadviews, no forced native-stereo-only renderer, no global NVIDIA hook, no unbounded diagnostic polling, no casual modifications to original Joey IDs 0/5.
- User prefers fewer, high-confidence headset tests, public Windows Actions artifacts, exact SHA provenance and detailed durable engineering records.

---

## 3. Exact provenance and current engineering state

### 3.1 The sacred Joey baseline

| Item | Exact pin / state |
|---|---|
| Repo | https://github.com/liviutrn/OpenNR |
| Joey backend | `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6` |
| Joey private UESDK | `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596` |
| Matching frontend | `joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091` |
| Build3 CI | https://github.com/liviutrn/OpenNR/actions/runs/38453012351 |
| Protected branch | `experiments/duoview-joey-current-clean-v1` |
| Real headset result | **USER-VERIFIED:** original Mono ID5 smooth for 30 minutes, no hitches |
| Prior handoff hash | `64432d0442066715fa442660a0848cf4963640b0` is recorded in earlier repo handoff; reverify whether it denotes source commit/artifact before labeling it a DLL hash |

Use `duoview/clean_restart/baseline.lock.json`, pinned branch checkout and `verify_exact_baseline.py` to validate sources. The UESDK may be restricted to Epic-authorized GitHub accounts. CI expects the `UEVR_SOURCE_TOKEN` / `PAT_TOKEN` secret; if source is inaccessible, **stop** rather than substitute a public or reconstructed SDK.

### 3.2 Builds/branches and what they mean

- `experiments/duoview-joey-fixed-center-v1` / Build19: first modern POC with moving tracked gaze, no large hitches in user test, but twitch, lighting quality, feature gaps.
- `experiments/duoview-v24-instant-gaze-temporal-audit` / Build33 source commit `d6b0a2bcd416073c41475f717aac03265c9687fd`: current projection reconciliation, instant raw gaze, source-state identity audit; **USER-VERIFIED** fixed center fine but tracked crop poor. Startup often required manual Native Stereo ID0 then DuoView ID6.
- Build34 and Build35: crash-prone NGX/bootstrapping candidates—**do not use as an implementation base**.
- `experiments/duoview-build33-lowres-native-bootstrap-v37`: Build37 retains Build33 two-view atlas and gaze code; adds initial Native0 scale 0.30, safe ID6 transition after warmup, and later resolution restoration only after successful composite submissions. Intended to reproduce the manual working ID0→ID6 sequence, **but startup is not headset-accepted**.
- **CI-VERIFIED:** Build37 Actions https://github.com/liviutrn/OpenNR/actions/runs/38623649137 completed **SUCCESS** on **CI source commit** `d82480ff784dd7c89ba533853e1cfe14ccfab3a2`. A documentation commit advanced the Build37 branch to `c43bd57a988241d529f9ba75ea147d960fd330d8`. Two artifacts observed: `Joey-DuoView-Temporal-v24-46`, artifact ID `11924695210` (11,516,035 bytes), and `Joey-DuoView-FixedCenter-Evidence-46`, ID `11923054797` (47,396 bytes). The CI result **does not** prove startup, scale restoration, gaze or temporal correctness in-game. The artifact archive/internal ZIP hash was not independently inspected here: recheck before release.
- `experiments/duoview-gaze-pose-latched-v38`: **unbuilt and not headset-tested** experimental branch after Build37. Two code commits `4ba06dc70ab70c38c5b1c85b51f3a4fdbb0e5562` (`DuoViewState.hpp` late-gaze logic) and `2d3639c119d5b2cab81ecdba71ebd1da0eba4f2f` (`apply_stage234.py` late CAPI sample). Architectural review document commit `2c879bd8850b9dde4b7adf4f65af451e27f34372` was the branch HEAD when reviewed. **Do NOT label v38 a fix or build on it blindly**: section 12 identifies concrete verifier and callback-order hazards.

### 3.3 Existing handoff references

1. `duoview/reviews/DUOVIEW_OPENNR_CHEEKY_GAZE_ARCHITECTURE_2026-10-14.md` — previous source comparison.
2. `duoview/reviews/DUOVIEW_BUILD37_LOWRES_NATIVE_BOOTSTRAP_HANDOFF_2026-10-14.md` — Build37 source/launch transition and caveats.
3. `duoview/ACTIVE_HANDOFF_JOEY_FIXED_CENTER.md` — long earlier engineering state; contains historical “pending CI” entries, so check live GitHub state.
4. `duoview/reviews/DUOVIEW_V23_BUILD32_GAZE_STABILITY_HANDOFF_2026-10-14.md` — why smoothing did not solve instability.
5. `duoview/reviews/OLD_LOGIC_NATIVE_FIX_INVESTIGATION_2026-10-14.md` and `duoview/reviews/TEMPORAL_SHADING_V22_HANDOFF.md` — old/new renderer and shading differences.
6. `.github/workflows/duoview-joey-stage234.yml` — Windows pinned-source test/build/package, **push branch filter currently targets Build37 branch**, not v38 or any new branch.

**Implementation decision:** Create **another isolated development branch**, either fork the Build33 source pin (manual startup = cleaner temporal control) or Build37 code pin (automatic startup may be desired but still unproven). Document which branch and exact SHA. Never overwrite Build3, Build33, Build37 or other work. Do not conflate “newest branch” and “known good.”

---

## 4. Production DuoView data flow — understand before changing anything

### 4.1 In-repo critical file map

| Path | Actual role |
|---|---|
| `duoview/joey_stage1/apply_stage1.py` | Patches pinned original Joey for isolated rendering method ID6 fallback |
| `duoview/joey_stage1/apply_stage234.py` | **Primary integration**: modifies original Joey `VR.cpp`, `VR.hpp`, `FFakeStereoRenderingHook.cpp`, `D3D12Component.cpp` and frontend; includes current projection reconciliation |
| `duoview/joey_stage1/apply_native_lowres_bootstrap.py` | Build37 Native0/scale/ID6 transition and SceneView hook arming |
| `duoview/joey_stage1/verify_stage234.py` | Exact modified/new path whitelist and production-source invariants; don't disable to make CI green |
| `duoview/DuoViewGeometry.hpp` | Two-view layout; true off-axis projection crop; composition coordinate model |
| `duoview/DuoViewState.hpp` | Frame slots, camera/rect/projection/main-family observations, immutable frame config and temporal audit |
| `duoview/DuoViewPSVR2Gaze.hpp` | 328-byte Toolkit CAPI ABI; combined ray→optical Mono→projection UV; freshness/50ms hold |
| `duoview/DuoViewGaze.hpp` | Ray, UV and optical math |
| `duoview/DuoViewCropStability.hpp` | v24 instant gaze state; v23 filtering/guard ignored |
| `duoview/DuoViewConfig.hpp` | Immutable per-frame parameters, ConfigLatch and generation/key semantics |
| `duoview/DuoViewFrame.hpp` | FrameKey, FrameCoordinator frame identity and fence contract |
| `duoview/DuoViewComposite.hlsl` | Reference HLSL fovea/periphery blend; has stale “not implemented” comment |
| `duoview/DuoViewCompositeRaster.hlsl`, `duoview/DuoViewD3D12.hpp`, `duoview/embed_shader.py` | **Actual production raster compositor / embedded DXBC**; verify runtime uses this shader, not the reference compute shader |
| `duoview/joey_stage1/ProductionContractTests.cpp` | Geometry, per-frame state, current projection, simplified temporal math |
| `duoview/joey_stage1/ProductionPSVR2GazeTests.cpp` | CAPI ABI/+Z projection tests |
| `duoview/joey_stage1/ProductionWarpPinned.cpp`, `duoview/production_warp_test.cpp` | DX12 WARP/reference GPU checks |

### 4.2 The real source code is generated in CI

The checked-in repository is **not** an in-place fork of Joey's `FFakeStereoRenderingHook.cpp`. The Windows job checks out pinned Joey, applies `apply_stage1.py`, `apply_stage234.py`, then `apply_native_lowres_bootstrap.py`. Your first job is to inspect the **fully generated Joey code** with exact anchors, not to pretend modifying `DuoViewGeometry.hpp` alone fully installs a fix.

Typical Windows Actions sequence, adapt paths to cloned workspace:

```powershell
python workspace/duoview/joey_stage1/apply_stage1.py backend frontend evidence
python workspace/duoview/joey_stage1/apply_stage234.py backend frontend workspace/duoview
python workspace/duoview/joey_stage1/apply_native_lowres_bootstrap.py backend
python workspace/duoview/joey_stage1/verify_stage234.py backend frontend evidence

git -C backend diff -- src/mods/vr/FFakeStereoRenderingHook.cpp src/mods/VR.cpp src/mods/vr/D3D12Component.cpp src/mods/vr/runtimes/OpenXR.cpp
```

### 4.3 Actual intended path (Build33/37, SOURCE-VERIFIED)

1. `VR::duoview_begin_frame()` creates source-frame snapshot in `UGameViewportClient::Draw` context, uses a predicted producer key, full Mono **LEFT** projection and near clip, and currently reads Toolkit gaze early.
2. `FFakeStereoRenderingHook::adjust_view_rect` selects two fixed **atlas rectangles**: fovea `(x=0,y=0,width=fw,height=fh)`, periphery `(x=fw,y=0,width=pw,height=ph)` in scene allocation `atlas_width=2*output_width`, `atlas_height=output_height`. **Atlas rectangle never follows eye**; the *frustum sampled in it* changes.
3. `calculate_stereo_view_offset` after Joey Mono camera transformations records source view0 camera and reuses it for view1; prove actual hook call order and whether view0 pose capture is after all transforms.
4. `calculate_stereo_projection_matrix` applies frozen full/current foveal off-axis projection through `apply_frame_projection`; `FSceneView` constructor patch reconciles current `FSceneViewInitOptionsUE5/UE50To53::projection_matrix` against the expected current projection.
5. `State::consume` ensures one main family, two rects, projections, cameras and valid key, but observation ≠ proof of UE **GPU-successful source** or temporal history commit.
6. DX12 raster compositor blends periphery sampled at full-output UV with fovea sampled at `(fullUv - cropOrigin) / cropExtent` from the atlas; Joey Mono copies composed full-FOV output to both XR eyes after GPU recording/fencing.
7. SceneView source ViewState identities are observed, and `TemporalAudit` computes **expected crop pixel delta** and “stable states,” but **does NOT read the previous matrices actually consumed by TSR/DLSS/velocity passes**.

### 4.4 Exact geometry snippet and crucial limitation

`DuoViewGeometry.hpp::apply_foveal_crop` modifies GLM-style column-major `matrix[column][row]` clip-space X/Y rows **relative to W**, leaving depth/W untouched:

```cpp
const auto x_scale = 1.f / (l.u1 - l.u0);
const auto y_scale = 1.f / (l.v1 - l.v0);
const auto x_shift = (1.f - l.u0 - l.u1) * x_scale;
const auto y_shift = (l.v0 + l.v1 - 1.f) * y_scale;
for (int col = 0; col < 4; ++col) {
    const auto old_x = matrix[col][0];
    const auto old_y = matrix[col][1];
    const auto old_w = matrix[col][3];
    matrix[col][0] = old_x * x_scale + old_w * x_shift;
    matrix[col][1] = old_y * y_scale + old_w * y_shift;
}
```

The generated patch explicitly comments that **private previous ViewState, velocity buffers and TSR history are NOT written**, because guessed offsets would crash or double-compensate. This is the highest-value gap to test, **not proof they are incorrect**. Unreal might store the correct previous crop itself, or might not; only inspecting the real temporal consumer will settle that.

### 4.5 Frame-key and lifecycle details

`VR::duoview_key(uint32_t frame)` returns `{mono_generation(), uint64(frame)+1}`. `duoview_producer_key()` calls it with `internal_frame_count+1` (prepared NEXT frame); `BeginRenderViewFamily` uses observed engine `frame_count` to resolve key. Verify this mapping in actual callbacks. `ConfigLatch::retire()` clears `cached_` but **not `last_key_`**; same-generation frame-counter rewind on reinit could reject new data. A correct generation bump may cover this; prove it rather than weakening stale-frame gate.

### 4.6 CAPI source reality

- Toolkit `Status` ABI is `0x148` bytes; combined calibrated direction, magic/size validity, blink and nonfinite checks are handled.
- Toolkit basis X-left/Y-up/Z-forward converted to Mono X-right/Y-up/Z-forward. `optical_ray` applies inverse **left optical rotation**, then `projection_uv` uses Joey's **+Z-forward** perspective (important: `p[11]=+1`, do NOT use generic OpenXR -Z mathematics here).
- Reader currently uses `GetTickCount64()` and stores **cached UV** for up to 50ms. `Status::frame_counter` and `Status::timestamp` exist but are **not used** to pair a sample to the predicted XR head pose. On nonblocking CAPI false/no-new-frame, it holds valid UV. This is an independent potential source of head-motion jitter.
- The producer passes `get_eye_transform(0)` and its frozen Mono projection. Do not silently substitute per-eye FOV into the **combined Mono** frustum.

---

## 5. OpenNR r10 — the exact reusable pieces and what NOT to copy

**Source revision:** `build/2.20.1-v06-r10-stable`, not generic OpenNR HEAD.

**Files:**

- [NativeOpenVRGaze.cpp](https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r10-stable/runtime/open-shaders/src/Features/Upscaling/NativeOpenVRGaze.cpp)
- [GazeCropPolicy.h](https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r10-stable/runtime/open-shaders/src/Features/Upscaling/GazeCropPolicy.h)
- [test_gaze_crop_policy.cpp](https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r10-stable/runtime/open-shaders/tests/cpp/test_gaze_crop_policy.cpp)
- [FoveatedRender Core.cpp](https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r10-stable/runtime/open-shaders/src/Features/Upscaling/FoveatedRender/Core.cpp)

### 5.1 Proven implementation details

- `NativeOpenVRGaze` queries OpenVR `IVRSystem_026::GetEyeTrackedFoveationCenter` via vtable slot 35 (verified against OpenVR ABI in its source), returns per-eye **NDC** foveation centers, converted to top-left UV as `u=(x+1)/2, v=(1-y)/2`.
- `ResolveForFrame` **caches a single crop result for an engine frame**, with exact configuration, sizes, base regions and dynamic-gaze flags, so VRS/DLSS/NR passes don't silently use different ROIs.
- The source tracks raw/current/filtered gaze, reacquisition, validity, per-eye crops and last acquisition. Missing asynchronous sample can be held for 50ms; change of valid/lost tracking governs history transition.
- `GazeCropPolicy::Filter` filters **only tiny fixation noise**. It bypasses immediately if displacement measured in output pixels exceeds **2px** on either axis.
- `GazeCropPolicy::ResolveOrigin` holds previous crop position inside a guard and otherwise quantizes/snap-centers new origin. Large movements are immediate; no continuous slow-chasing follower required.

Representative original logic (simplified only for variable naming):

```cpp
if (!width || !height ||
    abs(sample.x - previous.x) * width  > 2.0f ||
    abs(sample.y - previous.y) * height > 2.0f)
    return sample; // deliberate change bypasses filter
const float alpha = smoothingMs > 0
    ? elapsedMs / (smoothingMs + elapsedMs) : 1.0f;
return previous + (sample - previous) * alpha;

const float desired = clamp(sample - extent * 0.5f, 0, 1 - extent);
const float guard = min(0.02f, extent * 0.05f);
if (havePrevious && abs(desired - previousOrigin) <= guard)
    return previousOrigin;
const float step = pixels
    ? min(float(quantizationPixels) / pixels, guard) : 0;
return step > 0 ? clamp(round(desired / step) * step, 0, 1 - extent)
                : desired;
```

**Very important trap:** `guard=min(0.02,cropWidth*0.05)` is in normalized **full-screen UV**. For a 0.30-wide crop on a 3000px output, `0.015 * 3000 = 45 output pixels`. User does NOT want a visually frozen follower; copy the structure and tests but initially prefer an **explicit ~1–2 full-output-pixel guard/quantization** unless evidence supports a larger guard. Expose control later only if needed. The >2px filter rule and the origin guard are **different mechanisms**.

**History caveat:** r10 source currently marks changing crop origins as a downstream renderer history-reset event in its own pipeline where no exposed-region validity mask exists. This is **not** authority to reset UE TSR or NGX every pixel of eye movement. Doing that in DuoView can produce visible re-generation/flicker. OpenNR r10's moving region exists in a post/render pipeline, **not as a new UE FSceneView projection**. Transplant fixation policy, not a fictional UE history fix.

---

## 6. Cheeky — the stronger model for crop-origin motion and frame coherence

**Pinned upstream:** `ClarkCheekyKent/CheekyFoveatedDLSS@4e47eefe51a512dcaf76bbdc672dcdab5251fc71` (v0.5.5 in local repo documentation).  
**Local adapted branch:** `experiments/cheeky-psvr2-r13-duoview-eye-select` (includes r10 policy copy, r12 NR changes, r13 eye-filtering).  
**User evidence:** Cheeky SR gaze crop is stable/no regeneration after modifications; Cheeky NR still had flicker historically.

### 6.1 Concrete Cheeky source paths

- [src/crop_motion.hpp](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/crop_motion.hpp): source crop movement equation and vector unit scale.
- [src/crop_motion.cpp](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/crop_motion.cpp): privately corrected D3D11/D3D12 resources; GPU submission lifetimes.
- [src/d3d12_backend.cpp](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/d3d12_backend.cpp): whether to preserve/restart history and submit private corrected vectors.
- [src/gaze_foveation.cpp](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/gaze_foveation.cpp): `calculate_coordinated_crop`, `ScopedCoordinatedCrop`, state-per-view, eye mapping and diagnostics.
- [src/gaze_policy.cpp](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/gaze_policy.cpp): temporal eye sample policy, reset reason and large-jump thresholds.
- [src/gaze_projection.hpp](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/gaze_projection.hpp): source projection matching (do not guess which eye from DLSS call order).
- [openxr_layer/openxr_layer.cpp](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/openxr_layer/openxr_layer.cpp): `xrLocateViews`, located eye pose, submitted FOV, gaze pose and display-time snapshot.
- [local OpenNR R10 policy copy](https://github.com/liviutrn/OpenNR/blob/experiments/cheeky-psvr2-r13-duoview-eye-select/CheekyPort/overrides/src/OpenNR_R10_GazeCropPolicy.h)
- [local Cheeky r12 patch](https://github.com/liviutrn/OpenNR/blob/experiments/cheeky-psvr2-r13-duoview-eye-select/CheekyPort/scripts/apply_r12.py)
- [local Cheeky r13 patch](https://github.com/liviutrn/OpenNR/blob/experiments/cheeky-psvr2-r13-duoview-eye-select/CheekyPort/scripts/apply_r13.py)

### 6.2 Exact key Cheeky invariant: crop-origin motion is NOT scene motion

From `src/crop_motion.hpp`:

```cpp
// NGX vectors point current -> previous.
// previousLocal = currentLocal + sceneMotion
//               + currentOrigin - previousOrigin.
inline bool crop_motion_offset(const FoveationGeometry& previous,
        const FoveationGeometry& current, bool input_pixel_units,
        float scale_x, float scale_y, CropMotionOffset& offset) noexcept {
    offset = {};
    if (!isfinite(scale_x) || !isfinite(scale_y) || scale_x == 0 || scale_y == 0)
        return false;
    const double dx = double(input_pixel_units ? current.input_base_x
                                               : current.output_base_x)
                    - double(input_pixel_units ? previous.input_base_x
                                               : previous.output_base_x);
    const double dy = double(input_pixel_units ? current.input_base_y
                                               : current.output_base_y)
                    - double(input_pixel_units ? previous.input_base_y
                                               : previous.output_base_y);
    offset = { float(dx / scale_x), float(dy / scale_y) };
    return isfinite(offset.x) && isfinite(offset.y);
}
```

The math is portable. **The NGX hook API is not.** It matters whether motion vectors are in input/output-pixel units or normalized. The sign above assumes Cheeky's current→previous NGX convention; UE velocity buffers **must be measured/verified**. Copying an offset without knowing whether Unreal already includes it can **double-correct** history and make shaking WORSE.

### 6.3 Exact production conditional in Cheeky DX12

From `src/d3d12_backend.cpp` in upstream around lines 1736–1775:

```cpp
bool motion_reset = !view->has_crop;
if (!contract.reset && !key_changed && view->has_crop && crop_changed &&
    contract.preserve_history_on_crop_move) {
    correct_motion = crop_motion_offset(view->last_crop, crop,
        contract.motion_vectors_low_res, contract.motion_vector_scale_x,
        contract.motion_vector_scale_y, offset);
    if (!correct_motion) { motion_reset = true; offset = {}; }
}
if (resize_motion || correct_motion) {
    auto* corrected = prepare_crop_motion12(command_list, inputs.motion_vectors,
        /* validated input rectangle, offset and output dimensions */);
    if (corrected) {
        parameters->Set("MotionVectors", corrected);
        parameters->Set("DLSS.Input.MV.Subrect.Base.X", 0U);
        parameters->Set("DLSS.Input.MV.Subrect.Base.Y", 0U);
    } else motion_reset = true;
}
if (contract.reset || key_changed || motion_reset ||
    (crop_changed && !contract.preserve_history_on_crop_move))
    parameters->Set("Reset", 1);
```

It records **actual** history resets and motion corrections; updates last crop only following actual successful evaluation. It uses **private**, lifetime-managed motion textures, not mutating game vectors in place. Neither `parameters->Set(...)` nor private NGX evaluation should be transplanted into DuoView.

### 6.4 Cheeky controlled reset policy

`evaluate_gaze_reset(...)` in `src/gaze_policy.cpp` resets for first valid frame, reacquisition, view remap, crop dimensions change, or a **large** jump (per-axis threshold `max(64 pixels, round(regionSize*jump_reset_ratio))`). Small origin movement may preserve history only **when correction is valid**. The r12 `apply_r12.py` changed NR handling to tolerate tiny (~0.5%) floating scale rounding and added NR history diagnostics. This explains how other projects avoid reconstruction flicker; **not** proof that UE's own TSR accepts the exact same reset controls.

### 6.5 Cheeky alignment to real OpenXR view

The Cheeky OpenXR layer observes `xrLocateViews` at display time and both the **located view pose** and **submitted projection/FOV**. It can project gaze into the actual source eye. A `ScopedCoordinatedCrop` associates crop to the correct DLSS view within an operation rather than resampling inside subpasses. This is the model for DuoView's **single immutable packet per rendered source frame**.

But Cheeky processes DLSS view IDs (and r13 opt-in source-eye filtering), whereas DuoView uses two artificial Unreal **Mono source passes** and submits same final image to both XR eyes. Do NOT equate a Cheeky “eye 0” with DuoView UE pass0 or XR left eye without checking mapping.

---

## 7. The geometry and temporal contract the next engineer must prove

### 7.1 Define spaces precisely

- `U_n = (u_n, v_n)` = normalized **full Mono frustum** UV of a projected world point on frame n.
- `o_n = (u0_n, v0_n)` = foveal ROI top-left within the full Mono image.
- `s = (cw, ch)` = ROI width/height as a fraction of full Mono image.
- `L_n = (U_n - o_n) / s` = **foveal viewport-local normalized UV** (componentwise division).
- `R_n = (fw, fh)` = actual **high-res foveal UE source viewport** pixel extents. These may differ from full Mono dimensions and from prior frame after scale changes.
- `A = atlas top-left` = fixed GPU scene atlas placement. **NOT** moving gaze ROI. Fovea source starts at atlas x=0, periphery x=fw.
- `P_full,n` = full Mono projection, correct asymmetric tangents and +Z-forward convention.
- `C(o_n,s)` = off-axis clip-space crop transform currently applied by `apply_foveal_crop`.
- `P_fovea,n = C(o_n,s) P_full,n` (subject to verified matrix multiplication convention and exact jitter insertion).
- `V_n` = actual UE camera world-to-view transform.
- `J_n` = engine temporal jitter, which must not be double-applied.
- `H_n` = history epoch / owner / ViewState identity.
- `K_n` = producer frame key / matching submitted frame and camera pose identity.

### 7.2 Reference reprojection derivation (unjittered)

For a stationary world point `X`, full UV current/previous are `U_n=project(P_full,n*V_n*X)` and `U_(n-1)=project(P_full,n-1*V_n-1*X)` in the project's correct matrix convention. Then:

```text
local_current  = (U_current  - o_current ) / s
local_previous = (U_previous - o_previous) / s
motion_current_to_previous_in_fovea_pixels = R * (local_previous - local_current)
  = R * [ (U_previous - U_current) + (o_current - o_previous) ] / s
```

If the source sizes differ, adapt coordinate mapping **or declare histories incompatible**, rather than blindly using common `R`. Current→previous sign in this equation must be inverted if a particular UE input declares the opposite convention. Jittered motion requires engine-specific treatment on top of this **unjittered reference**.

**Working example A:** output 3000×3000, crop width 0.50, density 1.0, so source width 1500. With head and world static, move ROI u0 from 0.25 to 0.26: `1500 * (0.26-0.25)/0.50 = +30 foveal source pixels` of current→previous crop-local motion. But the **composited object's full-screen position must remain constant**. Treating +30 as object motion after composition is wrong; treating 0 as crop-local temporal motion is wrong.

**Working example B:** 3000 output, crop width 0.30, density 2.5 → source width 2250. ROI +0.02 UV → `2250 * 0.02/0.30 = +150 source pixels`. It is possible to trigger substantial temporal misreprojection with small changes in full FOV.

**Working example C:** stationary world object under deliberate head yaw/pitch and world fixation. `(U_previous-U_current)` is nonzero due to head motion and `(o_current-o_previous)` moves because gaze follows the object. Their interaction can nearly cancel in fovea local space. Comparing only crop origin without head pose is insufficient. The true movement and foveal temporal result must be checked against a **world-point CPU oracle**.

### 7.3 The dangerous double-compensation case

If UE already builds motion vectors using exact previous `P_fovea,n-1` and current `P_fovea,n`, then the `o_n - o_n-1` term is **already implicit**. Adding a Cheeky-style crop-origin correction again corrupts it. The primary mission is to discover whether Unreal's actual temporal previous projection/velocity includes this movement or not. **Never inject a correction solely because the equation exists.**

### 7.4 Core invariants

1. Both source views share one **fully processed** Mono camera pose for same UE producer frame.
2. Source0/1 current projections and `FSceneViewInitOptions` match one frozen snapshot.
3. **Previous foveal temporal projection** equals the projection from the **last successfully rendered compatible foveal source frame**, not full FOV/current cropped projection/periphery's projection.
4. Previous view/camera, jitter, viewport rect, screen percentage and source ViewState/history owner are compatible with the previous projection.
5. Foveal source size is genuinely high resolution, not enlarged peripheral color.
6. Exact ROI for source projection = exact ROI in compositor `CropUv`, no second late sensor sampling.
7. Temporal motion with moving ROI matches world-point oracle and has correct sign/units.
8. Fixed center remains identical to prior working baseline.
9. Missing sample, blink, hot mode transition, scale change and camera cut cannot reuse incompatible history.
10. No frame contamination across generation/source ViewState or mismatched GPU/submit frame.

### 7.5 Asymmetric FOV and matrix conventions

Historic HMDQ PSVR2 per-eye tangents included outer ~1.841771, inner ~0.947191 and vertical ±1.328981, **but they are NOT the exact current shared Joey Mono combined frustum**. Use **actual** `P_full` from pinned Joey. Test off-center projection terms and +Z-forward (`p[11]=+1`). Matrix is GLM-like column-major `matrix[col][row]`. Do not silently plug symmetric FOV or change Y sign.

---

## 8. Competing root causes, ranked but not declared proven

**H1 — Previous-frame UE projection / viewport / motion vectors inconsistent with moving fovea.** Highest priority, consistent with jelly inside crop and fixed-center control. `apply_stage234.py` currently reconciles **current** `FSceneViewInitOptions` but not private previous temporal state. **Hypothesis until actual UE velocity/TSR/DLSS consumption is inspected.**

**H2 — CAPI gaze and predicted head pose not paired.** `Reader` caches UV up to 50ms and ignores Toolkit `timestamp` and `frame_counter`. Samples chosen during early `AdjustViewRect` may precede final head pose. Significant candidate for boundary movement when head turns.

**H3 — Frame key, callback order or producer/compositor latch split.** `duoview_producer_key()` predicts engine frame; source callbacks and composer rely on matching recorded frame. One early or late ROI use can jump independent of history.

**H4 — Raw sensor micro-jitter.** v24 intentionally ignores guard/quantization; even corrected geometry would have small border twitch from true sensor jitter. r10 tiny fixation guard can help **after** image reprojection is correct.

**H5 — ViewState reuse/switch, periphery shading, TAA jitter, screen percentage, Lumen/exposure histories.** Can increase apparent shake/seam/darkness; don't conflate lighting parity with gaze root cause.

**H6 — Optical transform/offset signs or active view mapping.** Test raw Toolkit→Mono and current UE projection vs actual source with asymmetric view; fixed center rules out only gross static problems.

**H7 — Native DLSS private history behavior.** Possible, but do not use that suspicion to justify global NGX hooks: Build34/35 crashed.

**Question to answer first:** What are the **actual previous projection/view/jitter/rect** and motion vectors consumed by STALKER 2's active temporal path when gaze crop changes? Does it already include the correct `currentOrigin - previousOrigin` term?

---

## 9. Detailed implementation milestones, with gates and assigned work

### Stage A — Freeze baselines; inspect the actual patched renderer

**Task A1:** Create a separate branch from a **named clean source pin**. Prefer Build33 manual ID0→ID6 for isolation if Build37 boot path not accepted; or Build37 code pin if startup is indispensable. Protect Build3/Build33/Build37 unchanged. Record branch, exact commit SHA, exact SDK/frontend/backend submodules, checked source hashes and test artifacts.

**Task A2:** Generate source with the original pinned CI patch sequence. Inspect actual generated `backend/src/mods/vr/FFakeStereoRenderingHook.cpp` line-by-line around `adjust_view_rect`, `calculate_stereo_view_offset`, `calculate_stereo_projection_matrix`, `sceneview_constructor`, constructor restoration, source view/scene state and family logic. Inspect `VR::duoview_begin_frame`, `D3D12Component::record` and `OpenXR` frame/submit/scale logic. Annotate exact order, thread and frame key for each callback. Do not assume callback order in UE matches expected names.

**Task A3:** Determine actual **STALKER 2 UE 5.x version** and active temporal path *for tested settings*: TSR? temporal AA? UE DLSS SR? Lumen history? The handoff does not prove an exact engine minor version or a specific upscaler mode. Use supported runtime/source inspection, not guesses. If unknown, explicitly mark the blocker.

**Task A4:** Verify current foveal source0/1 mapping and independent/stable UE `FSceneViewState` objects. Do not treat XR left/right eyes as DuoView source views. Confirm `duoview_key(internal_frame_count+1)` and actual family `frame_count` map identically under frame generation and after swapchain reinitialization.

**Deliverable A:** source-backed callback diagram, pinned SHAs, exact modified-file diff, runtime temporal technique, and a compact baseline matrix:

| Test | Fixed center | Tracked gaze |
|---|---|---|
| World-fixation stationary head | Expected stable | Report current defect/evidence |
| World fixation + head yaw | **USER-VERIFIED stable** | **USER-VERIFIED shaky/jelly** |
| Saccade response | N/A | Must remain immediate |
| Fovea true UE pixels | Expected | Must independently verify |
| Startup | manual path previously worked | Build37 CI only, runtime unverified |

**Gate A:** No unresolved source pins or silent SDK substitution. Continue to B only when actual generated hooks are inspected.

### Stage B — Minimal passive source-backed temporal observability

Do **not** begin by writing to private UE memory. DeepSeek mentioned `FSceneView::PrevViewInfo`, `PrevViewProjMatrix` and `PrevViewRotationProjMatrix` as research pointers. These names/field availability and offsets in **this exact UE runtime/SDK** are **not verified**. They may be version-dependent, stored in `FSceneViewState` or renderer-private structures, or exposed differently; verify before dereferencing.

**Task B1:** Introduce **OFF-by-default**, bounded one-shot temporal snapshot, capturing only validated, safe fields for a single main family. Suggested record schema (PSEUDOCODE; proposed not present):

```cpp
struct DuoViewTemporalTrace {
    FrameKey producer_key, engine_key, submit_key;
    uint64_t sample_arrival_qpc;
    uint32_t toolkit_frame_counter;
    int64_t toolkit_timestamp;     // raw clock domain unknown until calibrated
    float raw_gaze_u, raw_gaze_v, resolved_u0, resolved_v0;
    Rect fovea_atlas_rect, periphery_atlas_rect;
    CameraPose first_mono_camera, second_mono_camera;
    double full_P[16], foveal_P[16], ctor_observed_P[16];
    uintptr_t fovea_ViewState_id, periphery_ViewState_id; // IDs, not blind deref
    bool main_family, gaze_finalized, consumed, prior_matrix_known;
    uint64_t history_generation;
    // Optional ONLY after ABI proof:
    double previous_UE_foveal_P[16], previous_UE_V[16];
    float previous_jitter_xy[2], current_jitter_xy[2];
    Rect previous_UE_view_rect;
};
```

**Task B2:** Tie the capture to the actual production callback, **not unit-test-only path**, off with zero per-frame polling/logging. Fixed-size ring of 8–16 records or one-shot snapshot; avoid allocations and disk output on render thread, nonblocking copy out after safe point. Avoid GPU waits. No unknown pointer reads. Include generation, view source0/1, producer/composer frame identity and actual fovea P. Instrument active temporal prev P only through a **verified** engine API/offset/hook.

**Task B3:** Compare actual previous UE projection used by temporal consumers to the known projection of last compatible fovea frame. Record whether active temporal velocity is current→previous, normalized/pixel units, pre-/post-upscale, jittered/unjittered. Validate ViewState identity. Inspect screen percentage and viewport transformations—not only matrix. If no safe way to read prev data, report **BLOCKED** rather than inventing offsets.

**Task B4:** Minimal test cases: (i) fixed-center; (ii) forced constant gaze UV with eye tracking toggle still on; (iii) deterministic programmed crop origin ±1px/3px/large; (iv) stationary world fixation with simulated yaw; (v) lost gaze/reacquisition; (vi) both source view selections; (vii) source frame missed. Avoid many user HMD tests; prove with CPU/oracle where possible.

**Gate B:** A real read-only temporal coherence verdict and documented location **or** explicitly identified ABI blocker. Do not introduce guessed previous-history writer.

### Stage C — Write an independent CPU reference oracle

Suggested pure standalone files **to create**, not assumed to exist: `duoview/FovealTemporalContract.hpp` and `duoview/tests/FovealTemporalOracle.cpp`, or extend pinned `ProductionContractTests.cpp` while retaining an independent mathematical implementation.

Define a `TemporalSourceFrame` containing `P_full`, actual `V`, ROI, source width/height, atlas source rect, engine jitter and epoch. Implement two **independent** calculations:

1. Reference world-point full UV then `(U-o)/s`, and current→previous local source pixels.
2. Motion implied by candidate current/previous cropped UE matrices and actual viewport mapping.

Compare within a documented subpixel tolerance, using double precision and correct +Z/column-major conventions. Negative tests must **fail** if previous matrix is deliberately uncropped/current/periphery and **fail** if crop delta is double-added.

**Mandatory fixtures:** 2000×2000, 3000×3000, 3400×3172, 4096×2160; 0.30/0.50/0.80 ROI; 1.0/2.5 densities; symmetric/asymmetric frusta; ROI steps of 1,2,3,10,30 output pixels and 0.01/0.02 normalized; noncentral gaze and clamp near corners; head yaw ±2° and ±10°, pitch/translation, stationary world point and independent gaze; view source0/1; jitter ±0.5 pixel; camera cut/teleport, epoch, generation reset; absent sample, blink/no-new, 50ms TTL; source format/rect changes; random bounded world points with deterministic seed. Assert full composite point remains **world-locked** under crop-only moves.

**Worked numeric assertions:**

```text
3000 output, cropW=0.50, fovea density=1.0: fw=1500.
ROI origin 0.25 -> 0.26, static scene:
expected current->previous crop-local motion = +30 source px.
Full-output world UV must remain identical.

3000 output, cropW=0.30, fovea density=2.5: fw=2250.
ROI origin +0.02 full UV, static scene:
expected current->previous crop-local motion = +150 source px.
```

Use *actual* prior/current projection plus pose in yaw test. Distinguish atlas placement `(0,0)` from changing ROI origin. If source dimensions change, invalidate/rebootstrap history unless a version-verified UE mechanism handles dimension transforms.

**Gate C:** math oracle passes, intentionally wrong prior-projection path fails, tests don't merely call the same function twice.

### Stage D — Implement UE temporal correction at correct **pre-consumption** point

This is the **main** engineering task. Choose according to evidence, not preference:

- **Case D1:** If Unreal already stores accurate **previous gaze-cropped projection** and compatible history, **DO NOT ADD Cheeky OFFSET**. Inspect viewport mapping, temporal jitter, screen-percentage scaling, camera pose, source ViewState ownership and matched frame/gaze. Fix precisely the incorrect term.
- **Case D2:** If actual previous projection is uncropped/current/peripheral, correct or supply the **actual previous successfully rendered foveal projection and corresponding view/viewport/jitter** using a **version-validated Unreal integration** before velocity/TSR/DLSS computes histories. Prefer Unreal-native FSceneView/renderer functionality if exposed by verified SDK/source; no random pointer field write.
- **Case D3:** If the matrix is correct but the native temporal motion field is missing crop-origin delta, adjust **only the affected foveal input** in a safe, tightly scoped engine renderer path, with correct sign/units and no global NVIDIA hook. Confirm that the adjustment is not already implicit.
- **Case D4:** If no safe prior-view interface can be established from the pinned engine/SDK, **STOP with specific blocker and proposed additional instrumentation**. A bounded RDG/renderer interception may be future work but is not a 2-line change; no unverified memory writes.

Illustrative **noncompilable** history structure / decision:

```cpp
struct FovealHistoryCandidate {
    FrameKey prior_key;
    uint64_t epoch;
    uint64_t source_viewstate_identity;
    Mat4 actual_previous_fovea_projection;
    Mat4 actual_previous_view_matrix;
    ViewportRect previous_viewport;
    Vec2 previous_engine_jitter;
    UV previous_foveal_origin;
    bool successful_engine_history_commit;
};

bool reuse = candidate.successful_engine_history_commit &&
    same_generation_and_consecutive_frame(candidate, current) &&
    same_validated_viewstate_owner(candidate, current) &&
    compatible_dimensions_projection_mode(candidate, current) &&
    !camera_cut_or_mode_transition(candidate, current);

// Read/compare the engine's actually consumed prev matrices here.
// If wrong, use ONLY an ABI/source-verified engine API/hook to repair them.
// If unavailable, fail closed; DO NOT write arbitrary private offsets.
```

**Important:** `State::consume()` proves CPU observations and source pair eligibility, not automatically successful UE temporal-history GPU commit. Do not use an incomplete frame as `prior` just because source0/view0 projection callback ran. Model previous successful view-state history separately. Validate no shared fovea/periphery state, no stale previous matrix after scale switch, no wrong stereo source index.

**History invalidation rules:** camera cuts/teleports, renderer generation reinit, missing compatible prior frame, source view index remap, aspect/projection type change, resolution/crop dimension change, temporal technique change, source ViewState destruction/reassignment, game level/GC transitions, genuine crop nonoverlap. Reuse with motion correction for **small overlapping crop moves**, NOT reset on every tiny movement. Native engine camera-cut/history controls may be used only if proven safe. The v23/v24 history idea of resetting NVIDIA feature on every gaze change caused flicker/crashes and must not recur.

**Gate D:** actual traced temporal prev/current information matches independent oracle, head-yaw test passes mathematically, zero double compensation, fixed-center unchanged, no unknown-memory modification.

### Stage E — Synchronize gaze with actual Mono camera and source frame

Use OpenNR’s one-frame crop and Cheeky’s sample/projection metadata discipline.

**Task E1 — CAPI reader data model.** Consider exposing (without ABI changes) a metadata-rich packet:

```cpp
struct GazeObservation {
    Ray calibrated_combined_ray;
    uint32_t toolkit_frame_counter;
    int64_t toolkit_timestamp;    // raw clock; units not yet validated
    uint64_t host_arrival_monotonic;
    bool newly_sampled, valid, blinked;
};
```

Currently Reader returns only cached UV. Preserve fallback semantics: nonblocking `false` ≠ invalid; no-new sample holds last valid for max 50ms; invalid size, missing combined flag, blink, nonfinite/wrong forward direction invalidate immediately. **Do not reproject a held ray against unrelated newer optical transforms** or assume CAPI timestamps equal OpenXR `XrTime`. Correlate clock domains **only if measured and monotonic**; no guessed timestamp conversion.

**Task E2 — source latch timing.** Layout/sizes can be prepared in `AdjustViewRect`; final gaze should ideally be frozen once corresponding camera pose is known **before either UE projection/constructor consumes it**. But callback order is not guaranteed. Only implement two-phase layout→gaze finalization if Stage A verifies it safe, backed by ordering tests. Otherwise retain one immutable earlier snapshot and solve proven source/key mismatch differently.

**Task E3 — exact immutable packet**

```text
FrameKey+generation / actual UE frame / XR pose frame identity
+ calibrated sample ID/timestamp and validity
+ final Mono camera pose used by UE source0 and source1
+ frozen full Mono projection, applied crop ROI and foveal P
+ atlas rectangles and selected UE source indices
+ prior compatible foveal history epoch/view state/P/V/viewport/jitter
=> pass identically through both UE source views and the DX12 compositor
=> submit same composed Mono frame to both XR eyes
```

No separate gaze read at compositor time. Compare `duoview_producer_key()` and `duoview_key(frame_count)` explicitly. Prevent split-frame settings sampling while UI sliders change.

**Task E4 — optional OpenVR comparison.** OpenNR uses native per-eye OpenVR NDC foveation center; Toolkit returns calibrated combined direction. Build a **diagnostic-only** side-by-side mapping into same true Mono basis to see whether Toolkit CAPI+left optical is miscalibrated. Do not swap one to another in production or confuse source frame eye and XR eye.

**Gate E:** eye UV under deterministic head/eye scenario tracks single frame/pose and producer+compositor match; no extra lag, no alternating last-valid/center, no new calls in IDs 0/5.

### Stage F — Port small OpenNR fixation/noise guard

Only after D/E (correct temporal image): adapt `GazeCropPolicy::Filter` + `ResolveOrigin` to DuoView’s `duoview/DuoViewCropStability.hpp`, with one **full-output-pixel** size notion. Suggested initial 1–2px quantization/guard and immediate movement beyond the small fixation threshold; do NOT blindly set 45px r10 guard, 85ms smoothing or a velocity cap. Remember r10 conditional is **strict >2px**, exact 2px may still filter if smoothing is enabled.

Unit-test 1000 frames alternating ±0.5px, 1px, 2px tiny drift, 3px >threshold, smooth pursuit, 50px and 500px saccades. Verify new accepted coordinate wins within **same new UE rendered frame**, not gradual follower. Clamp ROI to valid 0..1 and respect source rectangle. Both `apply_foveal_crop` and actual production compositor must consume exactly the same snapped origin. Reacquire invalid gaze and change frame generation carefully.

**Gate F:** no visible raw small border shake expected from sensor microjitter, immediate saccades, world-point/temporal oracle still passes. No cosmetic “stability” from slow lag.

### Stage G — End-to-end compositor, shading and performance validation

- Verify production **raster** compositor and embed shader (`DuoViewCompositeRaster.hlsl`, `DuoViewD3D12.hpp`) rather than outdated comment in `DuoViewComposite.hlsl`. Inspect generated actual DXBC/PSO and map `CropUv` to source UV with half-texel bounded samples.
- Add WARP GPU tests with **world-coordinate encoded** high-frequency grid rather than only colors. ROI move 1px, 3px and large saccade; compare expected world position against CPU oracle, no atlas bleed, no seam translation, correct foveal detail, feather debug and periphery-only/fovea-only diagnostics. Check both eye copies after actual GPU fence. Verify source0/1 selection and fixed center.
- Prove independent UE high-res foveal source: actual UE render rectangle, foveal projection and detail exist before compositor. Explicitly rule out low-res periphery magnified into ROI.
- Check periphery darker shadows/Lumen/exposure separately; the experimental “Independent primary shading” toggle defaults **OFF** and only enables after source pair stable. Don't turn shading workaround into a secret mandatory gaze dependency.
- Audit descriptor/PSO/resource prewarming, DX12 allocations, fences and render thread. No shader compilation, new allocation storms, blocking waits or per-frame history logs. Query GPU frametime only with its toggle, read retired slots.
- Original fallback can currently show a **single corrupt incomplete-atlas fault frame** before ID6 quarantine resumes original Mono on the next frame. This is a **known limitation**, not claimed seamless recovery; preserve fail-closed invariant.

**Gate G:** WARP + CPU reference agree with actual production shader, source fovea truly high density, no frame-source mismatch, no performance regressions evident in offline instrumentation.

### Stage H — Full independent audit, CI, package, ONE headset test

**CI work:** Strict bounded patch anchor checks; exact dependency pin verification; pinned `ProductionContractTests`, `ProductionPSVR2GazeTests`, WARP, all independent DuoView tests, full original Joey compatibility suite (historically 41/41), backend `UEVRBackend.dll` and auxiliary DLL builds, frontend rendering mode tests/publish, `verify_stage234.py --final`, source manifests, DLL+ZIP SHA-256 and read-first instructions. Verify the **dedicated Actions run** rather than unrelated repo workflow badges. Make new branch workflow trigger/dispatch explicit; do not assume Build37 branch-only `on.push` will build a new branch.

**Independent code review:** Find double-counted crop delta, wrong current→previous sign/units, wrong matrix row/col, viewport rect and jitter mismatch, unverified private UE previous offsets, source0/1 ViewState aliases, stale frame key after reset, hidden gaze smoothing, every render-thread allocation/log, unsupported HDR/source format, cross-thread lifetime or GPU fence hazard, NGX hooks accidentally restored. Run regression on unchanged ID0/ID5 behavior at source/tests level. A code review should identify actual line/commit references, not repeat optimistic handoff prose.

**Only then produce one candidate:** successful full Windows Actions run, actual artifact ID/link and zip/hash, exact code SHA, generated read-first, separate installation directory, rollback to protected Build3. Mark “offline verified / headset NOT verified” until user actually tests.

**Controlled headset acceptance script:**

1. Install experimental artifact in **separate folder**, keep original known-good Build3 intact. Record game temporal/upscaler setting, runtime version and render scale.
2. Fixed center first: world-lock head yaw/pitch, both eyes and foveal detail, no twitch. If this control regresses, stop.
3. Enable tracked gaze: stationary head/stationary fixation; tiny pursuit; immediate large saccades; no raw boundary jump beyond normal pupil accuracy.
4. Fix eyes on a stationary world texture/edge while moving head yaw/pitch: foveal **content stays world-locked**, no jelly, tearing, regeneration or moving double image. This is **the principal pass/fail**.
5. Blink and tracking loss >50ms / reacquisition, near ROI edge, view source0/1 if stable, scale/mode transition, controlled native shading toggle OFF then ON after render stability.
6. Observe fpsVR/UEVR GPU/CPU frametime, visible hitches, two-eye Mono output, source/fovea pixel density, Lumen shading difference. Capture only limited gated evidence.
7. On crash/black screen/hitch recurrence, revert immediately to Build3 and preserve precise logs. No indiscriminate repeated patch-and-test.

**Release acceptance:** user confirms crop boundary + world image inside stable under gaze and head motion, instant saccades, genuine high-density source, no CTDs/hitches, fixed center/Joey IDs unaffected. Tests/CI alone cannot establish this.

---

## 10. Engineering test matrix and required quantitative proofs

### 10.1 Independent CPU oracle pseudo-API

```cpp
// PROPOSED, not a presently compilable SDK or patch.
struct TemporalFrame {
    FrameKey key;
    Mat4 full_P;          // actual UE Mono projection
    Mat4 world_to_view;  // actual UE camera
    UV crop_origin, crop_extent;
    uint32_t fovea_width, fovea_height;
    Rect source_atlas_rect;
    Jitter current_jitter;
    uint64_t history_epoch;
    bool valid_engine_history;
};

Vec2 expectedLocalUV(const TemporalFrame& frame, WorldPoint X) {
    Vec2 full = projectWithPerspectiveDivide(frame.full_P * frame.world_to_view, X);
    return (full - frame.crop_origin) / frame.crop_extent;
}
Vec2 expectedCurrentToPreviousPixels(
    const TemporalFrame& prev, const TemporalFrame& now, WorldPoint X) {
    return Vec2{float(now.fovea_width), float(now.fovea_height)} *
           (expectedLocalUV(prev, X) - expectedLocalUV(now, X));
}
```

Actual math library operator order must match column-major UE/GLM correctly. Verify with a separately derived point-projection routine, not merely calling the same implementation twice. Incompatible frame source sizes should be invalidated unless explicit normalized conversion is proven.

### 10.2 Required groups of tests

| Group | Variations | What must fail if implementation is wrong |
|---|---|---|
| Static scene, gaze moving | +1px,+3px,+0.01 UV, small fixation jitter | Object's **full-output position changes** or crop-local current→prev MV omits offset |
| Moving head, fixed world gaze | ±2°,±10° yaw, pitch, translation, offcenter projection | UE predicted source motion disagrees with world-point oracle; jelly under fixation |
| Asymmetric FOV | center shifted, nonzero projection off-axis entries, PSVR2-like tangents | Wrong NDC sign or assuming symmetric FOV |
| Temporal jitter | jitter phase and units, motion jittered vs unjittered, screen percentage | Moving/flickering image due double jitter |
| Atlas/view mapping | source0 and source1 swapped, changing foveal density, feather | Wrong view/crop projection, low-res impostor or atlas bleed |
| History compatibility | camera cut, lost source frame, mode/scale reinit, level/GC, ViewState replacement | Old previous projection incorrectly reused |
| Toolkit tracking | CAPI false/no-new, blink invalid, max 50ms hold, reacquisition | Alternating center jump or stale wrong-pose mapping |
| Consumer frame identity | predicted producer vs actual UE frame vs composite vs XR submit | Stale/submitted wrong ROI; one-eye mismatch |
| 1/3px WARP | actual embedded raster shader and source pixel-coded grid | Half texel seam, wrong ROI sampling or atlas bleed |
| IDs 0/5 | source guards, full compatibility suite | Modification leaks into protected original Joey modes |

Quantitatively report source projection and expected prior projection error, projected point residual (pixels), frame-key mismatch count, ViewState changes, history invalidation count/reasons and **only** user-reported visual performance after headset acceptance. Do not invent thresholds or frame times; propose a subpixel precision tolerance for pure double math, then justify the actual GPU threshold.

### 10.3 Example single-frame audit summary

```text
DuoView diagnostics, frame K=(generation=G, frame=N)
method=6, mainFamily=true, sourceViews=2, foveaSourceUE=0
Toolkit sample counter=S, rawTimestamp=T (clock domain=unresolved), ageMs=A
UE camera source0=source1? YES/NO
current expected P_fovea == ctor P_fovea? YES/NO
previous consumed UE temporal P == actual previous fovea P? YES/NO/UNAVAILABLE
prev ViewState same owner and consecutive? YES/NO
expected from oracle current->previous crop-local delta: (...,... ) px
observed engine vector implied delta: (...,... ) px / UNAVAILABLE
source ROI == compositor ROI? YES/NO
source key == family key == submitted key? YES/NO
any history invalidation? reason=..., count=...
```

This is a **proposed diagnostic report**, not currently implemented. OFF by default, one-shot bounded capture, no noisy logging while rendering.

---

## 11. Important gotchas / explicit forbidden shortcuts

### 11.1 Do not assume a particular UE private “PrevViewInfo” field

DeepSeek suggested `FSceneView::PrevViewInfo`, `PrevViewProjMatrix`, `PrevViewRotationProjMatrix`. Those may be relevant **concepts** in UE5, but there is **no source verification yet** that these exact fields/offsets are safe in the pinned STALKER 2/Joey UESDK. Depending on UE version, previous state may reside in `FSceneViewState`, renderer-specific `FPreviousViewInfo` or private temporal structures. Establish engine version, exact type and writer/reader before touching pointers. If a safe reader/writer cannot be found: **report blocker** and design a supported scoped renderer hook, not unknown-offset memory patch.

### 11.2 Do not double-correct motion vectors

If UE generated motion using correct `P_fovea_prev` and `P_fovea_now`, the crop origin term is **already in motion**. Cheeky's additive correction only applies in its controlled case where crop offset was **not** otherwise represented. Explicitly create a negative unit test where additive correction worsens results and reject such a build.

### 11.3 Don't reset Nvidia/UE history every gaze move

Exact Cheeky selective reset uses compatibility and overlap. OpenNR r10's own history reset condition is tied to its different pipeline. An unconditional history flush on every 1px move creates regeneration and may consume CPU/GPU / reallocate features. Builds34/35 showed injection hazards near NGX. Don't intercept `_nvngx` again.

### 11.4 Avoid a fake high-res crop

Compositor can blend a texture at arbitrarily high output resolution without ever rendering new UE detail. A high-res foveal texture needs an actual high-density UE scene view with off-axis projection and correct shading. Assert source view rectangles/projection and high-frequency detail before calling it a quality fix.

### 11.5 Fixed-center success constrains every change

Do not modify static-center path unnecessarily. Source code should behave **bit-for-bit/equivalently** to last accepted fixed-center geometry absent gaze and avoid new view order changes. If a transform is “more correct” but breaks fixed-center, source assumptions are wrong or the regression unacceptable.

### 11.6 The historical hitched build is not the baseline

The old hitching prototype is valuable as a quality-reference and proof that high density can work; it used an earlier/mixed path and is not a safe modern production backend. Preserve Joey's clean Build3 and don't cherry-pick old backend/SDK binary glue to mimic the old version.

---

## 12. v38 experimental branch audit: **DO NOT BUILD OR DEPLOY UNCHECKED**

Previous session experimented with reading gaze after the first processed Mono camera in `experiments/duoview-gaze-pose-latched-v38`:

- `DuoViewState.hpp` adds `gaze_finalized`, a deferred flag on `State::begin`, and `finalize_gaze` to update ROI without resizing source atlas. `projection()` rejects frames if finalization hasn't happened.
- `apply_stage234.py` changes `VR::duoview_begin_frame` to allocate layout pending gaze; adds `VR::duoview_finalize_gaze` after first source camera offset; gates projection and constructor on finalization.
- **Not compiled / not CI-tested / not headset-tested** and **not the temporal previous-projection fix**.

**Concrete incompatibility identified:** `duoview/joey_stage1/verify_stage234.py` still checks for literal string `m_duoview_gaze.read_uv(frozen,optical)` in generated `VR.cpp`. New v38 code calls `m_duoview_gaze.read_uv(frame->projection,optical)`. Thus existing verifier is **out of sync**, regardless of compiler status. When changing it, replace string matching with **real new source contract assertions**, do NOT just remove the safety gate.

**Other targeted checks before considering v38:**

1. Did `calculate_stereo_projection_matrix` or `FSceneView` constructor execute before view0 offset is finalized? The new strict gate can invalidate a perfectly valid frame.
2. Is camera source0 captured **after** all Joey and other mods' final transforms? Source1 truly reuses same pose? Another late engine modification could still split the pair.
3. `ConfigLatch::for_frame` freezes an initial centered layout; `State::finalize_gaze` then mutates its own `ViewFrame` config, not the latch's cached copy. Confirm no other code later reads stale latch center and causes split consumers.
4. Existing Build37 `.github/workflows/duoview-joey-stage234.yml` listens only to Build37 branch pushes; v38 / new branches will not automatically run same workflow. Update trigger safely or use a reviewed workflow_dispatch where allowed.
5. Reader still does not expose sensor timestamps/counters for actual CAPI→predicted head pose association. The change only alters **call placement**; it doesn't prove timing correspondence.
6. The code still doesn't change actual UE *previous* temporal matrices, so it cannot be called an H1 solution.

**Recommendation:** Keep v38 as a separate hypothesis and **do not use it as a new baseline**. Prefer fresh clean branch from exact Build33/37 pin and implement the source/temporal oracle first. Only cherry-pick v38 if exact callback ordering and correctness tests pass.

---

## 13. Full senior-engineer task board for next chat

The implementing engineer should mark every item **DONE / BLOCKED / NOT STARTED**, name exact commit, evidence and test result. Do not start Stage H merely because no time remains.

- [ ] **A0** Clone and source-pin known Joey backend/frontend/private SDK; freeze original Build3 and Build37; choose clean new branch.
- [ ] **A1** Generate and inspect actual patched Joey code after *all* patch scripts, validate frame key and callback order.
- [ ] **A2** Determine game's exact UE engine minor version, actual temporal technique and source ViewState allocation/identity.
- [ ] **B0** Read-only bounded temporal logging OFF by default, capture current/previous UE data only where source/ABI verified.
- [ ] **B1** Prove/disprove previous foveal projection mismatch, jitter/viewport mismatch, or wrong source MV convention.
- [ ] **C0** Independent world-point oracle and tests for dynamic ROI/head motion, asymmetric FOV and jitter.
- [ ] **C1** Add wrong-previous-matrix and double-correction failure counterexamples.
- [ ] **D0** Implement minimal **engine-owned** previous temporal state repair if proven necessary; or correct actual wrong viewport/velocity input. No speculative offsets or NGX hooks.
- [ ] **D1** Epoch-compatible previous history management and successful-frame marking with proper source ViewState.
- [ ] **E0** Metadata-rich Toolkit sample observation, document clock domains; preserve false/no-new/validity/blink behavior.
- [ ] **E1** Freeze exact gaze/pose/crop packet at proven-safe point shared by two UE views and compositor; validate actual source frame key.
- [ ] **F0** Port *small* OpenNR r10 policy, immediate saccades, deterministic one-per-frame crop; no slow-chase smoothing.
- [ ] **G0** Production raster shader WARP tests and independent actual UE high-density source evidence.
- [ ] **G1** Lighting/shading toggle isolated, no accidental switch to Native Fix when DuoView needs Mono; budget and frame-pacing audit.
- [ ] **H0** Exact-source pinned Windows build; original full compatibility tests; source verifier updated honestly; artifact hash and manifests.
- [ ] **H1** Independent skeptical source/security/performance audit; fix all critical regressions before any headset test.
- [ ] **H2** Release **one** controlled PSVR2 test candidate with actual link, SHA-256, setup and Build3 rollback.
- [ ] **H3** Record user's headset acceptance separately from CI results and update permanent engineering handoff.

**Absolute stop conditions:** no original SDK access; no safe proof of UE historical data layout; current→previous sign unverified; math oracle fails; verifier fails; source frame mismatch; GPU stale image or one-eye frame risk; new NGX global hook required; crash, black screen or severe hitch in user's acceptance.

---

## 14. Independent review checklist after implementation

Give another model this prompt (fill exact branch/commit):

> Independently audit DuoView Mono UEVR eye-tracked fovea at repository `liviutrn/OpenNR`, branch `[EXACT_BRANCH]`, SHA `[EXACT_SHA]`. Do **not** trust a previous assistant's handoff or a green CI alone. Read actual generated patched Joey `FFakeStereoRenderingHook.cpp`, `VR.cpp`, D3D12 and OpenXR frame submission, and pure helper tests. Determine exact STALKER 2 UE version/temporal path. Prove current and previous foveal projection, view matrix, viewport, jitter and temporal history owner agree with real rendered source and the independent world-point oracle. Compare math to Cheeky `crop_motion_offset` (current−previous origin) and OpenNR r10 frame caching/guard, but never import NGX-specific hook or assume it applies in UE. Check lack of double-compensation, gaze sample/pose clock correlation, frame-key correctness, true high-density UE foveal pixels, 0/5 isolation, shading parity, resource/fence lifetime, stale-image fallback, injection safety, all Windows test results and actual package SHA. Report concrete source line defects and severity, and distinguish tests/CI from PSVR2 headset proof.

---

## 15. Copy/paste first message for the fresh ChatGPT Work chat

> **Take over DuoView Mono UEVR gaze stabilization** in `https://github.com/liviutrn/OpenNR`. Read the complete handoff `duoview/reviews/DUOVIEW_GAZE_STABILIZATION_MASTER_IMPLEMENTATION_HANDOFF_2026-10-14.md` and `duoview/reviews/DUOVIEW_OPENNR_CHEEKY_GAZE_ARCHITECTURE_2026-10-14.md`. The user headset-tested that **fixed-center foveal crop is PERFECTLY stable**, but enabling tracked gaze makes both the **crop border** and the **actual separately rendered high-res image inside** tremble/jelly, especially while turning the head and fixating a stationary world object. Slow smoothing is NOT a fix. Borrow OpenNR r10's one-frame gaze policy/small fixation guard and Cheeky's exact crop-origin temporal motion math, **but implement appropriate Unreal pre-temporal current/previous view history correction only after proving what actual UE temporal consumers receive**. Do NOT magnify low-res periphery, do NOT use global NGX hooks, do NOT guess `PrevViewInfo` offsets. Keep Joey Build3 (run `38453012351`, 30-minute verified) untouched; Build37 run `38623649137` passed CI but is NOT headset-accepted; v38 late-gaze edits are unbuilt, have verifier mismatch and are not a complete fix. Create an isolated clean branch, perform Stages A–H, run independent math/WARP/full Joey Windows tests and a skeptical audit, maintain detailed checkpoints, and provide ONE carefully verified Windows artifact with a real SHA and rollback before asking me to test. Distinguish verified source/CI from hypotheses.

---

## 16. Reference index (important permanent links)

### Joey / DuoView

- Main repo: https://github.com/liviutrn/OpenNR
- Build37 successful workflow: https://github.com/liviutrn/OpenNR/actions/runs/38623649137
- Build37 code branch: https://github.com/liviutrn/OpenNR/tree/experiments/duoview-build33-lowres-native-bootstrap-v37
- v38 experimental branch: https://github.com/liviutrn/OpenNR/tree/experiments/duoview-gaze-pose-latched-v38
- Generated integration script: https://github.com/liviutrn/OpenNR/blob/experiments/duoview-build33-lowres-native-bootstrap-v37/duoview/joey_stage1/apply_stage234.py
- Exact source verifier: https://github.com/liviutrn/OpenNR/blob/experiments/duoview-build33-lowres-native-bootstrap-v37/duoview/joey_stage1/verify_stage234.py
- Native0 bootstrap script: https://github.com/liviutrn/OpenNR/blob/experiments/duoview-build33-lowres-native-bootstrap-v37/duoview/joey_stage1/apply_native_lowres_bootstrap.py
- Foveal geometry: https://github.com/liviutrn/OpenNR/blob/experiments/duoview-build33-lowres-native-bootstrap-v37/duoview/DuoViewGeometry.hpp
- Frame state: https://github.com/liviutrn/OpenNR/blob/experiments/duoview-build33-lowres-native-bootstrap-v37/duoview/DuoViewState.hpp
- PSVR2 gaze: https://github.com/liviutrn/OpenNR/blob/experiments/duoview-build33-lowres-native-bootstrap-v37/duoview/DuoViewPSVR2Gaze.hpp
- Crop policy: https://github.com/liviutrn/OpenNR/blob/experiments/duoview-build33-lowres-native-bootstrap-v37/duoview/DuoViewCropStability.hpp
- Current composite reference: https://github.com/liviutrn/OpenNR/blob/experiments/duoview-build33-lowres-native-bootstrap-v37/duoview/DuoViewComposite.hlsl
- Pinned contract tests: https://github.com/liviutrn/OpenNR/blob/experiments/duoview-build33-lowres-native-bootstrap-v37/duoview/joey_stage1/ProductionContractTests.cpp
- Earlier source comparison: https://github.com/liviutrn/OpenNR/blob/experiments/duoview-gaze-pose-latched-v38/duoview/reviews/DUOVIEW_OPENNR_CHEEKY_GAZE_ARCHITECTURE_2026-10-14.md
- Original unpatched Joey SceneView callback (large file): https://github.com/joeyhodge/UEVR/blob/5ac7edc207866569334175e4ed8a7517971547f6/src/mods/vr/FFakeStereoRenderingHook.cpp

### OpenNR r10

- r10 branch: https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r10-stable
- Native gaze and frame cache: https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r10-stable/runtime/open-shaders/src/Features/Upscaling/NativeOpenVRGaze.cpp
- Crop policy: https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r10-stable/runtime/open-shaders/src/Features/Upscaling/GazeCropPolicy.h
- Crop policy tests: https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r10-stable/runtime/open-shaders/tests/cpp/test_gaze_crop_policy.cpp

### Cheeky

- Pinned upstream: https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/tree/4e47eefe51a512dcaf76bbdc672dcdab5251fc71
- Crop motion formula: https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/crop_motion.hpp
- D3D12 history/correction: https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/d3d12_backend.cpp
- Coordinated crop/view matching: https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/gaze_foveation.cpp
- Reset policy: https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/src/gaze_policy.cpp
- OpenXR pose/display time and gaze: https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/4e47eefe51a512dcaf76bbdc672dcdab5251fc71/openxr_layer/openxr_layer.cpp
- Local r10 copy: https://github.com/liviutrn/OpenNR/blob/experiments/cheeky-psvr2-r13-duoview-eye-select/CheekyPort/overrides/src/OpenNR_R10_GazeCropPolicy.h
- r12 NR patch: https://github.com/liviutrn/OpenNR/blob/experiments/cheeky-psvr2-r13-duoview-eye-select/CheekyPort/scripts/apply_r12.py
- r13 eye-source filter: https://github.com/liviutrn/OpenNR/blob/experiments/cheeky-psvr2-r13-duoview-eye-select/CheekyPort/scripts/apply_r13.py

**Final senior-engineer instruction:** Be skeptical, preserve genuine high-res Unreal rendering, prove the actual temporal interface first, implement the minimum correct change, reject unverified memory writes, perform independent mathematical and GPU tests, audit, only then ship a controlled headset candidate. No status or compiler result should ever be represented as proof the shaking is fixed without direct headset evidence.