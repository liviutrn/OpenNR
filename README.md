# OpenNR 2.20.1 — R9 combined rebuild

This branch rebuilds expanded SR/compressed neural feathering and the CSX
shader-detail mask on retained R7 behavior. Windows package validation is
in progress; headset behavior and GPU savings remain unverified.

Changes:

- One shared quantized planner for the core, expanded SR and mask protection.
- Root-qualified shader includes matching the production loader.
- Separate packing and residual-resolve variants; zero strength still resolves.
- Validated mappings/resource extents and specific failure diagnostics.
- NR failure withdraws expanded SR until manual Reset Neural Rendering.
- CSX controls directly on Upscaling, with active/bypass/skip-area status.
- Coherent hair material/tint/normal setup; mask only expensive self-shadow.
- Extracted-package tests use the actual production include loader and D3D11
  debug validation, including resolve, stereo guards and atlas splits.

The mask skips selected detail work, not every shader operation. Expanded
SR protects more of the image, leaving less area to skip. No measured GPU
speedup is asserted. One-atlas NR, gaze policy, controller stages and
near-black protection are retained. No new smoothing or deadzone is added.

[Technical handoff and validation](docs/versions/2.20.1-v06/r9-rebuild/README.md).
