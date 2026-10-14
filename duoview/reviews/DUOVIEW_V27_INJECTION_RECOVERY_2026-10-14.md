# DuoView v27 — injection recovery without NGX hooks

Current branch: `experiments/duoview-v25-gaze-camera-always-on`. Windows Build35 verified and ready for headset testing. User has fully authorized publication and building and explicitly permits removal of the NGX hook.

Published build source: `d2a496086e05b34318263e33a6bf7ac945ef16ee`, tree `35c9f941e3bd5f601926417af6fbabea064e725a` (exact local match). [Build35 / run38612708276](https://github.com/liviutrn/OpenNR/actions/runs/38612708276) succeeded. Exact baseline/SDK and patch verification passed.

## Build34 rejection and evidence

User reports immediate injection CTD in STALKER2. The submitted minidump records an execute access violation at address0 on the RHI thread. Its stack passes through NVIDIA's NGX model and `_nvngx.dll`, then Build34's hook forwarding call. The exact downloaded Build34 backend maps return RVAs0x452cbc and0x453199 to SafetyHook forwarding and the new NGX evaluation wrapper.

The dump's evaluation frame has no matched producer snapshot and its temporary Reset scope is inactive. This excludes an applied forced-history-reset flag on that particular call. It does not prove which internal NVIDIA assumption failed. Injection logs confirm NGX interception was installed during bootstrap, before a complete two-view source frame. Build34's incomplete-frame path could send8x8 dummy rectangles to Unreal's upscaler; the constructor was also still initializing. No out-of-memory error is established by this report.

The supplied crash files remain private inputs and are not published with this branch.

## Corrections

Removed direct NGX CreateFeature/EvaluateFeature hooks, parameter adapters and reset policy, their UI toggle/counters, official NGX dependency and associated nonshipping ABI test. The production backend uses the original Joey CMake source list again. There is no dormant toggle to re-enable this hook. Unreal and the game's upscaler manage their own histories; v26's forced DLSS history reset is no longer present.

Startup and incomplete snapshots now use the real compact layout's rectangles instead of8x8 placeholders. If resolution is unavailable, the shared allocation/rectangle planner uses two128x128 rectangles in a256x128 atlas. Pending or unknown precision cannot fall through to a full native-sized viewport. Frame validation still withholds incomplete sources from XR submission. The bootstrap geometry is preventive hardening, not a proven diagnosis of NVIDIA's null call.

Always-on ID6, no ID0 warmup, compact scene allocation, full-size mono XR output, gaze-directed foveal camera/ray mapping, fixed-center mode, tracking-loss coordinate hold, and optional independent shading remain. Joey Build3 remains untouched. The OpenNR guard/instant-saccade/quantization controls remain. Quantization is now explicitly in foveal source pixels after any game upscaling, since there is no NGX input-scale observation.

## Verification

All eight local CPU executables pass with assertions enabled after exact backend/frontend patch application. New independent and pinned-production checks cover startup without a resolution, valid in-bounds source rectangles, both fovea indices and one-/zero-based indexing. Existing ray, frame, gaze and zero-settling-drift checks pass. Patch scripts compile; `git diff --check` passes. Generated production code contains no NGX service or tiny-view path, and backend CMake is unchanged from the pinned original. Local application excludes Windows shader embedding.

Windows CI passed52/52 tests:3 pinned production tests,8 independent CPU/GPU tests, and41 original Joey compatibility tests. Backend and matching frontend compiled, frontend ID6-only/legacy-profile migration passed, and final source verification passed. The binary guard confirmed removal of the NGX interception identifiers. Headset injection, actual gaze jitter and startup at5000x5000 remain hardware acceptance items.

## Verified Build35 package

[Download Build35](https://github.com/liviutrn/OpenNR/actions/runs/38612708276/artifacts/11919646385), artifact `Joey-DuoView-OpenNR-v27-35`, ID11919646385. Evidence artifact ID11919386481. Subsequent handoff-only commits do not change build source `d2a496086e05b34318263e33a6bf7ac945ef16ee`.

- Outer GitHub artifact SHA256: `018ce12629bed7a7746bd5acca3860949e15ff8819805021b1f778460c1d5ade`.
- Inner install ZIP SHA256: `28f656782923b6e682ede90f894adfa8d21691a2d819d8a5eb7fee8e97545065`.
- `UEVRBackend.dll`:16,312,832 bytes; SHA256 `1d0a51c8bea02f6ab9ca27a69f1de9abd81ad9f6f3b42b440e588fdefb1e3e1d`.

Downloaded both artifacts and verified their GitHub digests, ZIP CRCs, inner ZIP hash, and all14 package files against the CI hash manifest. Backend is AMD64 PE. Actual DLL retains the quantization/defaults controls and contains none of the removed NGX API, hook status or history-setting identifiers. Source hashes match the locally generated exact-production camera, state, config, layout and stabilization headers; Config has the intentional retire-reset transformation from the applier. Current README and matching injector are present. No SDK source/headers are packaged.

Restart STALKER2 and the injector. Extract the outer artifact ZIP, then its inner install ZIP into a fresh directory, preserving Joey Build3. Use STALKER2 DX12 and SteamVR OpenXR; ID6 is already active. Restore OpenNR r10 tracking defaults (stabilization ON, smoothing0, quantization8 source pixels). The NGX history-reset toggle is intentionally gone. Check injection first, then gaze stability and direct high-resolution startup/runtime restart. Build35 has passed software verification but has not been executed on the user's headset here.
