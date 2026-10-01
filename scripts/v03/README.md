# OpenNR 2.20.1-v03 transforms

v03 starts from the user-tested v02 checkpoint `067376ac5a57b997b053ef44503880c62c7e0535`.

## Non-regression contract

- Keep the validated v00/v01/v02 transformation order intact.
- Layer v03 changes only after the v02 transformations.
- Do not restore the removed NR-specific sharpening settings.
- Preserve the fixed-resource-envelope / reduced-P2 architecture.
- Preserve crop-motion compensation and do not recreate Feature18 merely because a crop origin moves.
- Eye tracking owns crop center/origin; adaptive logic may change size only.
- Adaptive crop must never exceed the user's configured crop size.
- Every v03 transform must assert the source shape it expects and fail closed on mismatch.

## v03 scope

1. Extend the existing shared DLSS RCAS sharpness control from 0..1 to 0..3 while preserving the exact old 0..1 response and making 3.0 approximately three times the old maximum sharpening delta without driving the RCAS kernel into its unstable >1 lobe range.
2. Fix gaze fixation stability by preserving ordinary crop-origin history compensation instead of forcing a Feature18 history reset for every tiny valid origin move.
3. Replace the old adaptive behavior with a robust frametime controller that can choose 2 sequential NR passes, 1 pass, or 0 passes; shrink crop size relative to the user's chosen crop; and optionally use model-resolution tiers without being blocked by an eye-tracked crop.
4. Keep restoration deliberately slower than degradation and account explicitly for the configured approximate per-pass Feature18 cost.
