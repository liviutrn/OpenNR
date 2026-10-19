# DuoView candidate review — 19 October 2026

## Verdict

Builds 161–164 and 167 passed their Windows CI gates. Builds 165 and 166 failed test compilation/fixture validation and are superseded by 167. These are source and software GPU checks, not headset performance measurements. No doubling of performance has been demonstrated.

| Candidate | Change | Review |
|---|---|---|
| 161 | Direct sampling of compatible Native Fix sources | Avoids source gather copies on the compatible route; retains validated format fallback. Actual gain unmeasured. |
| 162 | One double-wide XR raster draw | Trades two output copies for twice the blend shader work. Can regress depending on GPU and scene. Now opt-in, OFF by default. |
| 163 | Output-route and physical source diagnostics | Useful for confirming the route actually exercised. Corrected to report successful submission rather than recording/completion. |
| 164 | Per-slot SRV/RTV cache | Reduces descriptor creation calls for stable resource identities/formats. Fence ownership retained. |
| 167 | Cached descriptor handles/increment | Removes repeated CPU descriptor lookups. No established GPU-time gain. Includes corrected WARP fixtures from 165/166. |

## Fixes from this audit

- Validate Native and gather XR destinations before source transitions, copies or raster commands. Invalid targets must leave `recorded_commands()` false.
- Publish route and source diagnostics only after a successful copy submission. Submission does not assert GPU completion.
- Clear stale timing on disabled timing or output-route changes. Label the measured scope accurately: DuoView raster/output, excluding Unreal scene rendering and source gather copies.
- Require both pipelines and fallback atlas before accepting a prewarm cache hit; reset the timestamp frequency on reconstruction.
- Retire command slots, then release cached compositor/XR references before `xrDestroySwapchain`. Retain swapchains and reject recreation when retirement cannot be established. Check poison before the inherited wait can reconstruct a failed context.
- Order members so contexts destruct before compositors as a defensive lifetime measure.
- Keep the direct XR route behind a persisted experimental A/B toggle. Both routes still sample compatible Native sources directly.

An independent Luna audit confirmed the teardown issue and reviewed the retirement gate and timestamp ordering.

## Verification

Historical Windows runs independently checked: 39170640235 (161), 39173102383 (162), 39173479597 (163), 39173892102 (164), 39174596341 (167). All five completed successfully with backend/frontend compilation, three pinned production tests, six independent DuoView tests, and 41 original compatibility tests.

Local portable geometry, gaze, frame, configuration and state suites passed AddressSanitizer and UndefinedBehaviorSanitizer. LeakSanitizer is unavailable in this execution environment; leak detection was disabled. Python compilation and whitespace validation passed.

New Windows WARP coverage checks invalid destination rejection, same-format direct versus forced-copy gradient equivalence, descriptor reuse, route-change timing reset and disabled-timing reset. The exact-anchor verifier checks teardown ordering. The follow-up CI build is the authoritative compilation and WARP result for these fixes.

## Performance limits and headset test

Unreal scene target dimensions, secondary capture dimensions, depth/G-buffer/velocity allocation, renderer setup, Lumen, Nanite and shadow work are unchanged. Those require engine allocation/dispatch evidence before changing their contracts.

Both output and atlas fallback textures remain preallocated: nominal BGRA8 storage is `12 × eye width × eye height` bytes per slot, excluding alignment and other resources. At 3144×2500 this is approximately 89.95 MiB per slot. Direct output currently avoids copy traffic, not these allocations.

Use a separate test directory. In an identical scene with fixed headset resolution, graphics settings and gaze configuration, compare **Direct XR output OFF** with **ON**. Confirm the last submitted route actually changes; typed-format mismatch deliberately retains copy output. Allow command slots to cycle after each switch, then compare sustained frame time and the scoped GPU timing. Also inspect both eye images, peripheral lighting, crop edges, gaze loss/reacquisition, mode switching, resolution changes and restart. Keep the known-good build available. Utilization percentages and software WARP duration cannot establish real headset GPU gains or visual stability.
