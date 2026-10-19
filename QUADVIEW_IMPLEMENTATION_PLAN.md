# Stereo Quad Views from Build182

## Baseline and scope

Start from the preserved Build182 overlay, originally OpenNR commit
`67c6e1ec5b931d2922e0ef5d253b8e9bef7a1a80`. The initial verification
passed for all 84 files in `BASELINE_SOURCE_SHA256SUMS`.

Develop on `quadview/stereo-182`. Preserve the tested `v182` release and
the ID6 DuoView implementation. ID7 is a separate experimental stereo mode.
The initial supported target is STALKER 2 (UE5.5), DX12, OpenXR.

## Implementation sequence

1. Add explicit zero-based four-view indexing and an opt-in ID7 selector.
   Keep every ID6, stock Native, and Mono branch unchanged when ID7 is off.
2. Request one engine view family with four views: left context, right
   context, left focus, right focus. Use actual left/right eye poses for
   both views belonging to each eye. Begin with fixed-center focus.
3. Pack four nonoverlapping viewports into the existing `2W x H` scene
   allocation. Lower context resolution and crop focus projections using
   the full asymmetric per-eye projection. Validate every rectangle.
4. Observe the actual main family, constructor state references, and
   renderer/RHI ownership. Report distinct views and histories separately
   from hook-call counts. Do not synthesize or alias engine view states.
5. Bind source resource, target/scene identity, generation, geometry,
   two runtime eye poses, and execution evidence into one immutable frame
   packet. Never accept a frame based on a sampled clock-distance gate.
6. Add a dedicated D3D12 compositor that combines each eye's context and
   focus into its own full-FOV image. Submit standard two-eye OpenXR
   output. Retain resource/packet ownership through command-slot retirement.
7. Test geometry, off-axis projection crops, eye mapping, frame ownership,
   invalid/duplicate histories, transitions, and source generation changes.
   Run real Windows shader compilation and GPU compositor checks in CI.
8. Review the final code and package a clearly labeled experimental build.
   Record CI evidence and precise runtime limitations.

## Required invariants

- ID7 never enters the Mono eye-pose overwrite or ID6 two-source capture path.
- Quad view indices cannot modify legacy one-based-eye inference state.
- No LocalPlayer PostInitProperties replay to manufacture extra histories.
- Four views must belong to the same observed main family and source target.
- Focus projection and compositor crop use the same frozen geometry.
- Per-eye output stays stereo; a shared mono image is not Quad Views.
- Mode/configuration changes invalidate older source packets.
- No shader compilation, blocking GPU waits, or resource creation in the
  OpenXR copy callback.
- Missing proof produces a diagnostic waiting/unsupported state, without
  repeated automatic transitions between Quad Views and Mono.

## Handoff assessment

The Muse handoff is a useful source map, not validation. Its supplied patch
aliases zero-based view indices 0 and 1, leaves other legacy index inference
active, and scales only projection diagonals. Those changes are not reused.
Four hook callbacks do not establish four completed rasterized views.
Single-family rendering is the initial approach; universal impossibility
of other approaches has not been established.

Khronos documents promotion of XR_VARJO_quad_views functionality to OpenXR
1.1. This does not establish that the user's runtime exposes the required
view configuration. This implementation composites four engine views to
ordinary stereo and does not require runtime quad-view support.

## Validation boundary

The development environment cannot run STALKER 2 with the user's headset.
A successful CI build is not headset acceptance. The user must confirm four
rendered views, stereo alignment, temporal quality, and at least ten minutes
without crashes on their PC. Native secondary-pass shading and upscaler
behavior with four histories remain runtime risks. The initial scene
allocation remains full-size; no GPU speedup is claimed before measurement.
