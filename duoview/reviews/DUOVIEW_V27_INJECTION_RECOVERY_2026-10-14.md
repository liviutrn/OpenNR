# DuoView v27 — injection recovery without NGX hooks

Current branch: `experiments/duoview-v25-gaze-camera-always-on`. Windows replacement build pending. User has fully authorized publication and building and explicitly permits removal of the NGX hook.

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

Windows CI must rerun pinned production, independent WARP, the complete Joey compatibility suite, backend/frontend builds, final source checks and package hashing. A packaging guard rejects a backend containing the removed NGX hook/export identifiers or history-control identifier. Verified run, source and artifact hashes will be recorded below after completion. Headset injection, actual gaze jitter and startup at5000x5000 remain hardware acceptance items.
