# OpenNR 2.14.1

## Menu-safe DLSS-NR continuity

- Ordinary pause, map, stats, and guarded in-game menus no longer suppress
  DLSS-NR while the menu is open.
- Static menu backdrops use the existing camera-derived motion-vector fallback;
  live VR menu backdrops use engine motion vectors only when the world rendered
  that frame.
- Loading screens and the console remain fail-closed and reset temporal state.
- Menu entry/exit invalidates neural and foveated history once, preventing
  stale reprojection without requiring manual NR toggling.
- The optional pre-upscale NR experiment remains disabled in menus because it
  runs before menu motion guides are finalized; post-upscale NR remains active.
- DLSS RCAS sharpening is disabled by default (`sharpnessEnabledDLSS=false`,
  `sharpnessDLSS=0.0`); users can opt in explicitly from the upscaling controls.

The canonical archive is `OpenNR 2.14.1.7z`. This is a source/build/package
fix release; live Skyrim VR headset, two-eye, temporal, image-quality, and
frame-budget acceptance still require a fresh controlled test.
