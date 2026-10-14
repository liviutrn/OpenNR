# DuoView v26 — OpenNR controls and DLSS history protection

Superseded after user injection CTD. Continue with [v27 injection recovery](DUOVIEW_V27_INJECTION_RECOVERY_2026-10-14.md); Build34 is not a working headset baseline.

Branch: `experiments/duoview-v25-gaze-camera-always-on`. Windows Build34 verified and ready for headset testing.
Published build source: `310b505b1e430baf3981c5c79a9805bc752a5c54`.
Its tree `ede7269d4c0e2b9f168238774a6b7aa554f6db68` exactly matches the locally verified tree.
Windows run: [Build34 / 38605029465](https://github.com/liviutrn/OpenNR/actions/runs/38605029465).
The user approved the fixes and building and requested the last OpenNR stabilization controls plus a fix for gaze-dependent jitter and jelly-like settling.

## Source-backed changes

Exact reference: OpenNR r10 `3a403d6fea9cc73818b1cdd7473bd6fd9cb5cb98`, `runtime/open-shaders/src/Features/Upscaling/GazeCropPolicy.h`, `NativeOpenVRGaze.h/.cpp`, `FoveatedRender.cpp` and `FoveatedRender/Modes.cpp`.

The reference has stabilization through a central guard `min(2% full view,5% crop)`, fixation smoothing only for <=2 input-pixel changes, larger movements immediately bypassed, and quantization 0–64 input pixels (default8). Default smoothing is zero. These real controls are ported, with a toggle and restore-defaults button. Quantization scales to the observed foveal DLSS input size when a known foveal evaluation is matched. No continuous delayed crop following or speed cap.

The v25 gaze-directed camera and matching ray compositor remain. Crop position is frozen per producer frame. Tests verify instant deliberate movements, held fixation and zero position drift after movement stops. Tracking loss retains the coordinate while rendering fresh scene color.

New NGX hook uses official pinned NVIDIA headers `NVIDIA/DLSS@374959484e79a640feaba44c93ac8cfb0a03f5b5`. Header files are checked out in CI, never redistributed or substituted into Joey's restricted SDK.

Only known SuperSampling feature handles whose output dimensions uniquely match the current foveal source can receive a temporary Reset flag. The render-frame key comes from the existing protected OpenXR RHI assignment, not the latest game-thread gaze. Unknown, peripheral, equal-size ambiguous, unavailable-frame and non-DLSS features are passed through. The NGX parameter is restored after evaluation, and the game's own reset is preserved. Input dimensions inform pixel quantization.

History protection defaults ON, is toggleable, resets on a changed crop and its first stationary successor, then stops resetting on stable fixation. This protects against incompatible history continuing to slide after gaze stops, without feature/resource recreation. It is a containment strategy, not a claim that private Unreal velocity textures have been repaired. API hook status, matched evaluations and actual forced resets are visible in-game.

Runtime lifetime is protected with an atomic shared runtime snapshot, avoiding an added VR-lock dependency in DLSS evaluation. Device reset retains that snapshot while retiring frame history; runtime recreation clears it and publishes the new runtime. Hook targets are pinned; callbacks are installed disabled before enabling.

## Preserved behavior

ID6 only from startup and runtime recreation, direct constructor-hook initialization, compact engine atlas and full-size XR output, fixed-center off-axis mode when tracking OFF, optional primary-shading toggle, and original Joey/SDK/frontend pins. User-confirmed Joey Build3 is untouched. See the v25 handoff for full architecture and startup details.

## Validation and remaining uncertainty

Local CPU suites pass, including 8100 ray round-trips, instant quantized saccades, no stopped-crop drift, one-frame settling protection, fixed-crop history preservation, peripheral exclusion, NGX signed/unsigned Reset parameter handling, authored-reset preservation and restoration.

Final local check reran all nine CPU executables with assertions enabled after reapplying the latest patch to the exact backend/frontend pins: geometry, gaze, frame, config, state, gaze camera, temporal stability, pinned production contracts, and official NGX parameters. All passed. The patch scripts also compile and `git diff --check` is clean. Windows NGX tests explicitly retain assertions in Release builds. Local application excludes Windows shader embedding and cannot replace the Windows build or GPU WARP tests.

Windows CI compiled all changes, exercised WARP compositor mapping/slot reuse and official-SDK parameter contracts, ran all original Joey compatibility tests, and built the exact backend and matching frontend. Final source verification passed.

No STALKER2 GPU capture or PSVR2 execution is available here. The jelly symptom is consistent with temporal mismatch but its actual game root cause is not proven. Direct NGX protection does not patch TSR, Lumen or Ray Reconstruction private histories, and hook installation alone does not prove the game's feature/frame matching. Do not claim headset jitter fixed solely from CI. Final artifact identity and CI results will be appended after verification.

## Build publication status

An earlier automatic review rejected publication as insufficiently authorized. The user subsequently gave full authorization to publish and build this experimental branch. Shell Git has no configured GitHub credentials here; publication used the connected GitHub API and preserved the exact tested source tree. The resulting Windows workflow succeeded.

Build34 passed53/53 Windows tests:4 pinned production contracts,8 independent CPU/GPU tests, and41 original Joey compatibility tests. Matching frontend ID6-only/legacy-profile migration tests also passed. Both production backend and frontend built successfully. Assertion-based tests retained assertions in Release builds.

## Verified Build34 artifact

[Download Build34](https://github.com/liviutrn/OpenNR/actions/runs/38605029465/artifacts/11916511828), artifact `Joey-DuoView-OpenNR-v26-34`, ID11916511828. Evidence artifact ID11917006021. Build source remains `310b505b1e430baf3981c5c79a9805bc752a5c54`; subsequent handoff-only commits do not change it.

- Outer GitHub artifact SHA256: `288eff5493d86bbf29d4b725e4ea71034e110e7d7807a231f18ede6f4f8b3a73`.
- Inner install ZIP `Joey-DuoView-OpenNR-v26-34.zip` SHA256: `c6cfade8ec6738a9c16ea82a853ce04c6c1d809158fe659714c3d52c139c02c8`.
- `UEVRBackend.dll`:16,323,072 bytes; SHA256 `0132a10a72cfe8a73e660c5a72fbb1b945b0885d1d40bd2d1a60f7b9f875e070`.

Downloaded both artifacts, verified their GitHub digests and ZIP CRCs, checked the inner ZIP against its supplied hash, and independently matched all14 package files to the CI SHA256 manifest. Backend, LuaVR and nullifier DLLs are AMD64 PE images. Matching `UEVRInjector.exe` is present; README contains current v26/defaults/ID0 instructions. The backend includes the NGX exports and new stabilization controls. Packaged production source hashes match the new hook, policy, camera, state and geometry sources. No SDK headers or source files are packaged.

Extract the outer artifact ZIP, then the inner install ZIP into a separate directory, preserving Joey Build3. Use SteamVR OpenXR and STALKER2 DX12. DuoView ID6 is already selected; no ID0 warmup. In the in-game DuoView controls, restore OpenNR r10 tracking defaults (stabilization ON, smoothing0, quantization8, history protection ON). Headset acceptance should cover direct5000x5000 startup, runtime restart, rapid gaze changes and stopped-gaze image stability. DLSS UI matched-evaluation/reset counters report whether direct NGX protection actually reaches the game's foveal feature. These counters and synthetic tests do not establish STALKER2 temporal correctness.

## Atlas examples at 5000x5000 per eye

These are scene/view extents before DLSS input scaling, from the pinned Joey allocation/view policy and DuoView layout code; they are not measured FPS or whole-process VRAM usage. Normal Joey Mono uses one 5000x5000 scene view inside the original double-wide allocation. Full-resolution XR output remains required in every case.

| Mode/settings | Scene views | Scene atlas | Active view pixels | Atlas pixels |
|---|---|---|---:|---:|
| Native stereo | Two 5000x5000 eye views | 10000x5000 | 50,000,000 | 50,000,000 |
| Original Joey Mono | One 5000x5000 mono view | 10000x5000 | 25,000,000 | 50,000,000 |
| DuoView: 50%x50%, density1, periphery20% | Fovea2504x2504 + full-view periphery1000x1000 | 3504x2504 | 7,270,016 | 8,774,016 |
| DuoView: same crop, density2 | Fovea5000x5000 + periphery1000x1000 | 6000x5000 | 26,000,000 | 30,000,000 |

The source rectangles align to8 pixels. Atlas width is fovea width plus periphery width; height is their maximum height. For default DuoView, one 4-byte-per-pixel scene surface occupies about35.1MB instead of200MB in a double-wide atlas; actual games allocate multiple formats, histories, resources and final XR images. Atlas area falls82.45%; this does not imply82.45% lower total VRAM or higher FPS. Compact packing alone does not lower either view's chosen resolution. Low peripheral density is a deliberate quality tradeoff; density2 spends more pixels on the crop. The eye-tracked foveal camera rotates toward gaze and the compositor maps its rays back into the full mono output, so exact visible sharpness remains a headset acceptance item.
