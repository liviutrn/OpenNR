# v45 projective gaze motion diagnostic and single-owner cache

Base v43 reviewed production commit: `ebee6feae18e4dec437ca173b74a67f5fec8f9d5`.
Branch: `experiments/duoview-world-locked-temporal-v45`.

**Status:** software candidate only. NOT a verified repair of Unreal's consumed velocities.

## Motion distinction
For a stationary head and world ray at fixed full-image UV `s`, current local foveal coordinate is `c=H_current(s)`, previous is `p=H_previous(s)`. The real current-to-previous **source-local** motion is `(p-c)*(foveal width,height)`. The output screen point `s` does not move. v43's linear origin-delta audit was incorrect for its gaze-steered perspective camera; v45 derives this displacement from the actual current/previous homographies. No finished RGB pixels receive a previous-frame displacement.

## Actual runtime change
The PSVR2 CAPI Reader owns its valid last-sample expiry (50 ms), including blink invalidation and physical sample identity. CropStability formerly held a missing Reader sample for **another** 50 ms, which compounded staleness to roughly 100 ms. v45 removes that second hold. Large valid gaze shifts remain instant, and the one-output-pixel noise guard is retained. No SDK, backend pin, source selector, compositor mode, or original Joey mode is rewritten.

## Crucial boundary
These computed vectors are **diagnostics**. Unreal's velocity buffer, TSR state and previous-view transforms remain owned by the game. The user specifically wants those repaired, but the pinned SDK does not expose verified setters to that temporal consumer. It would be unsafe to fabricate a working motion-vector patch by shifting finished color or blindly writing private engine addresses. Do not claim the user's image shaking has been fixed without connecting to the actual UE history consumer and headset validation. Do not confuse synthetic pixels with runtime acceptance.

## Tests and failure modes
Check v45 temporal crosswalk with stationary world/full-UV, moving gaze; head turn implies a different full-UV and requires prior/current pose/depth to calculate a complete velocity vector. Reject generation gaps, skipped frames, source-selector changes and dimension changes. Verify blink immediate invalidation, one cache owner, repeated CAPI packet identity, mode 0/5 safety and Windows/WARP tests. Gaze-only output screen motion must remain zero by definition even while foveal source-local motion is nonzero.
