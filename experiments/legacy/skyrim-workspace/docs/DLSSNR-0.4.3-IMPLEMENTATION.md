# DLSSNR MGO VR 0.4.3 implementation

This release keeps the 0.4.1-compatible normal path and the optional 0.4.2
experiments, then adds a deliberately guarded two-pass Feature 18 cascade. It
is a screenshot/benchmark feature, not a VR performance optimization.

## Included

- Optional **2x sequential NR** in the Neural Rendering settings.
- Separate per-eye intermediate resources and separate Feature 18 handles/history
  for each cascade stage. A normal frame performs one evaluation per eye; 2x
  performs two sequential evaluations per eye, for four evaluations across a
  stereo frame.
- The second evaluation consumes the first evaluation's output and writes the
  final output. D3D12 resource transitions cover each stage independently so the
  cascade does not reuse a resource simultaneously as an input and output.
- The existing failure latch and fallback behavior remain in force. A failed
  cascade does not present a partial result as a successful frame.

## Defaults and gates

- 2x sequential NR: **off**.
- The setting is only honored by the full-eye post-upscale route.
- It is automatically disabled at runtime for cropped/foveated VR and whenever
  experimental pre-upscale NR is active. This prevents hidden multiplication of
  work and avoids combining two unverified stage contracts.
- Enabling it does not imply a performance gain. It roughly doubles Feature 18
  execution, increases tensor/VRAM pressure, and may amplify temporal smearing
  or instability. It is intended for still screenshots, repeatable captures,
  and curiosity/benchmark runs.

## Why this is technically feasible

The cascade follows the resource model used by multi-pass community feeders:
each evaluation receives an explicit input and output resource, and each stage
owns its own temporal Feature 18 state. Reusing the same history or binding one
resource as both input and output would not be a valid sequential evaluation.
The implementation therefore adds four runtime slots (two eyes x two stages)
while retaining the original two slots for the default path.

This is intentionally limited to 2x. Additional passes would need more
intermediate textures, Feature 18 state slots, reset/error bookkeeping, and a
clear capture use case. They are not justified for the target VR frame budgets.

## Suggested A/B test

Use a copied MO2 profile, the same scene, the same headset resolution, and the
same head motion:

1. Full Eye, 100% model resolution, 2x off.
2. Full Eye, 75% model resolution, 2x off.
3. Full Eye, 75% model resolution, 2x on.

Record actual Feature 18 success markers, per-frame GPU time, evaluations/frame,
left/right image stability, fine texture, halos, exposure transitions, and
reprojection. A package hash, copied setting, or resource log proves packaging
only; it does not prove live two-eye delivery or headset acceptance.

The expected result is a materially higher GPU time in case 3. Keep 2x off for
normal 90/120 Hz VR unless a measured capture shows an acceptable frame-time
budget.

## Validation

- Release Ninja build of `CommunityShaders.dll`: passed after the 2x cascade
  changes.
- Default setting remains false in fresh configuration.
- The package manifest records the 0.4.3 version and the 2x safety gates.
- Runtime acceptance still requires a live Skyrim VR test with Feature 18
  markers and actual headset output.
