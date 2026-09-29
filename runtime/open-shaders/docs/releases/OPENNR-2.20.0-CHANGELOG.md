# OpenNR 2.20.0

Performance and correctness release for Skyrim VR. Neural Rendering stays at
full 100% model resolution on every NR pixel.

## New

- **NR Coverage** (Neural Rendering > NR Cost). Runs Feature 18 only on the
  centered 95–70% of each eye, at full model resolution, and blends its edge
  into the full-eye DLSS image using your Edge Blend settings (Hard Copy is
  upgraded to Feather). DLSS and the periphery stay at full quality; the old
  foveated crop instead stretched a render-resolution periphery. NR cost
  scales with the NR area: 85% ≈ 72% of the NR work, 80% ≈ 64%. Default is
  Full eye (no change). Requires the Full Eye foveation preset.
- **Stagger eyes** (Temporal Stability, "Every 2nd frame" only). Alternates
  which eye gets full Feature 18 each frame while the other reuses its
  previous-frame residual, so per-frame NR cost stays flat instead of
  alternating heavy and light frames. Off by default.

## Removed / locked

- Performance Overlay is removed from this build (no overlay window, no
  per-draw timing, no VR overlay pass). Profiling remains in the menu.
- Reduced NR model resolution, Adaptive NR tiers (and the adaptive crop that
  depends on them) and pre-upscale NR are disabled: all of them evaluate NR
  below the display-eye resolution and weaken the neural effect. Saved values
  are normalized to 100% on load.

## Fixes

- VR pre-upscale NR passed UV-unit motion vectors to Feature 18 without the
  guide-pixel scale, so the model saw almost no motion. (The route is locked
  off in this build; the fix keeps it correct for research.)
- Temporal residual reuse and the Motion result stabilizer applied only
  ~59% of the real motion in the post-upscale VR route (guide pixels used as
  display pixels), which caused lagging history on head turns.
- The result stabilizer mixed shaped and unshaped NR deltas, so it could
  re-inject NR effect that result shaping had turned down. Stabilization now
  runs on the raw NR result and shaping is applied afterwards.

## Optimizations

- Stabilizer history ping-pongs between two textures instead of copying a
  full-eye history per eye per frame.
- Per-eye depth guides are copied directly instead of through a conversion
  dispatch when the source is already 32-bit float (the VR route).
- The NGX signed-runtime path proxy is installed only when a feature is
  created, not twice per eye per frame.
- The DLL is built with link-time code generation (/GL + /LTCG) like upstream
  shipping builds.

Source, build and unit tests do not establish in-headset frame time or
visual acceptance; compare NR Coverage 100% against 85% and 80% in the same
scene.
