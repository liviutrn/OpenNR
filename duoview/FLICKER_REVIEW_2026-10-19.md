# DuoView submission continuity correction

User observation: Build 168 has better peripheral shading than v24 but intermittent flicker, black frames and stutter alongside alternating status messages. Performance and the isolated crash are secondary to submission stability.

## Confirmed source problems

A missing or rejected DuoView pair cleared the Mono copy token, so OpenXR selected an empty pipeline state and omitted the scene projection. The result can be a black interval even though DuoView remains selected. The Native Fix producer attached an immutable view configuration, but its submission pose remained in a mutable six-entry runtime ring until consumption. Renderer callbacks and subsequent pose assignments could change that ring between production and submission.

A separate renderer invocation containing only auxiliary targets could also run main-pair validation and erase a valid packet with "no exact main-family eye pair was proven". DuoView now forwards these unrelated invocations without changing its main packet. Invocations that contain the viewport target still undergo the original strict validation. Retained packets must match the current main target as well as capture identity. This addresses a source of avoidable pair loss; its frequency in the affected game needs runtime evidence.

Draw identity was also derived from the XR pose token. Distinct viewport draws sharing a pose token reused the same State slot, retaining prior completeness flags and potentially invalidating the next draw when its camera changed. Draws now use an independent 64-bit serial while their explicit Mono pose token remains unchanged. A production contract test completes two transactions with different cameras sharing the same XR pose token.

The independent Luna audit found no automatic Mono/DuoView mode retry loop: compositor faults remain quarantined until explicit mode reselection. Transient waiting/active status messages can therefore resemble mode switching while scene layers are being dropped. This does not dismiss the visible flicker.

## Changes

- Stamp the DuoView PipelineState token when its located views and Mono pose metadata are published. Previously this token was stamped later by renderer callbacks, allowing fresh views to carry an old ring-slot token.
- Freeze the exact validated source PipelineState before either Native Fix renderer callback, and attach its views and pose metadata to the completed source packet.
- Consume that immutable pose after a successful scene-image copy instead of requiring the mutable runtime slot to still match.
- Use the current XR display time while retaining the original rendered scene pose.
- Permit up to 100 ms of continuity from the last successfully submitted scene image during a source gap. Repeated holds do not renew the deadline. Startup has no history.
- Invalidate continuity before any double-wide scene-image acquisition, during swapchain teardown, on mode generation or swapchain-handle mismatch, and after a failed scene submission. A failed replacement cannot pair new image contents with the old pose.
- Record history only after xrEndFrame succeeds with a real scene projection layer. Held submissions preserve the original source pose.
- Acknowledge successfully copied Native packets, preserving the Native Fix Active state. Record the retained packet, diagnostic ticket and actual source/destination identities for the added consume site; extend the diagnostic fixture count from three to four D3D12 paths while retaining all per-site checks.
- Expose copied, held and empty/failed submission counters with a reset button for steady-state delivery checks. Repeated frames are visible in telemetry and are not counted as proof of fluid rendering.
- Add distinct DuoView active/holding status and rate-limited producer-pose/pair rejection diagnostics.

The source renderer, Native Stereo Fix shading policy, foveal/peripheral sampling, GPU composition and existing performance options are preserved. No extra full-resolution history texture, GPU copy, GPU wait or scene rendering pass is added.

OpenXR explicitly permits xrEndFrame without another xrReleaseSwapchainImage since the previous frame; it uses the most recently released image. This correction only references that released image while no replacement scene acquisition has occurred. Reference: https://github.com/KhronosGroup/OpenXR-Docs/blob/main/specification/sources/chapters/rendering.adoc

## Verification and limits

Portable production contracts and frame state tests pass AddressSanitizer/UndefinedBehaviorSanitizer with leak detection disabled for this host. The continuity contract covers absent startup history, short gaps, expiry, non-renewal, generation changes, swapchain replacement, explicit invalidation and recovery. Applied-source checks require snapshot capture before the renderer split and history invalidation before image acquisition. Windows CI must compile and run the complete pinned/WARP/compatibility tests and backend/frontend builds.

This fixes demonstrated empty-submission and mutable-pose handoff paths. Without the affected game log and headset execution, it cannot establish that every cause of the reported flicker has been eliminated. Sustained missing pairs beyond 100 ms still expire rather than freezing an old scene indefinitely. New diagnostic lines identify remaining source-pose or pair failures if present during headset testing.
