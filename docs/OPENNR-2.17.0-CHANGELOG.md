# OpenNR 2.17.0 local VR performance candidate

- Carries the 2.16.0 Open Shaders upstream refresh, dependency updates, and
  native Feature 18 VR bridge.
- Ports Open Shaders PR #756's per-eye Streamline camera reprojection fix with
  its focused matrix test. This affects temporal input correctness for DLSS.
- Changes fresh VR Screen Space GI AO defaults from 3 slices / 6 steps to
  2 slices / 4 steps. GI remains disabled by default in VR; AO stays at half
  resolution with its temporal denoiser and blur enabled.
- Enables Skylighting incremental probe updates and two-frame probe and
  occlusion update intervals by default on fresh VR settings.
- Enables the existing NVAPI VR variable-rate shading default ring on fresh
  settings where supported. The runtime checks hardware support and suspends
  VRS during incompatible passes.
- Preserves user-saved settings and keeps NR quality, DLSS quality, render
  scale, native depth, motion vectors, per-eye state, and history guards.

These are experimental performance defaults for local A/B testing. The
package does not claim a measured speedup or HMD acceptance. Lower-cost AO,
less frequent Skylighting updates, and peripheral shading may have visible
temporal or stereo tradeoffs. Restore the prior mod/profile to roll back.
