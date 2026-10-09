# OpenNR R8 + CSX shader detail mask

Based on R8 `8fbfc13929ec6251cf05d4fed2bad667138b6bfa`.

## Changes

- Adds CSX-style peripheral work skipping for LLF contact-shadow rays,
  hair self-shadow rays, extra direct wetness lighting and water parallax.
- Reuses the active OpenNR crop and per-eye gaze centres. The mask encloses
  the entire SR rectangle, including its corners. R8 expanded SR is
  protected when neural feather is enabled.
- Feathered falloff is the default. Fully exterior pixels bypass the
  expensive effect; water parallax also reduces its sample count during
  the transition. Base scene lighting and geometry continue to render.
- Adds **CSX lighting detail mask**, **CSX water parallax mask**, and
  **Hard cutoff for CSX detail mask** under
  **VR → Foveation-Following Effects**. The first two default on; hard
  cutoff defaults off. Existing saved SSR choices remain respected.
- SSR foveation defaults on for settings files without an explicit choice.
  Its existing independent toggle remains available.
- Full-eye and near-full crops bypass masking. Flat rendering and
  reflection/menu passes retain full shader detail.
- Reuses three padding floats in SharedData. Existing buffer size and
  subsequent wind/feature offsets stay unchanged.
- Retains R8's atlas, raw gaze, crop-motion compensation, adaptive stages
  and inside-NR near-black protection. Neural feather stays off by default.

## Scope and acceptance

CSX does **not** eliminate all shader work outside its mask. This port
reduces the selected effects above. It does not reduce DLSS5 NR inference,
shadow-map generation, geometry processing, draw-call overhead or every
post-processing pass. No measured GPU speedup is claimed.

The build verifies CPU mask coverage, software-D3D11 mask execution,
SharedData reflection offsets, representative optimized Lighting/Water
permutations for VR and SE, inherited R8 tests and packaged file hashes.
Headset stability and GPU timing require testing in Skyrim VR.

For A/B testing, keep the scene, resolution, crop, gaze position and
adaptive stage fixed, then toggle both new mask controls. SSR has its own
control. Compare GPU frametime and inspect the transition in daylight,
rain, interiors with clustered lights, water and rapid gaze movement.

Implementation and source attribution:
[CSX_FOV_MASK_PORT.md](../../../CSX_FOV_MASK_PORT.md).
