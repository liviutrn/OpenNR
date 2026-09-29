# OpenNR 2.19.0

- Adds optional post-NR result shaping for brightness, tonal range, colour,
  hue, detail scale, and halo suppression. It is disabled by default and
  leaves the Neural Rendering output unchanged until enabled.
- Adds optional per-eye result stabilization with Off, Static, and Motion
  modes. Motion mode uses the game's motion vectors; depth and colour checks
  reject mismatched history, and invalid histories are reset before reuse.
- Keeps detail stabilization off by default and suppresses stabilization when
  temporal residual reuse is active, avoiding stacked temporal filters.
- Adds a prominent Neural Rendering status control with clear ON, OFF, and
  unavailable/error states, and shortens the menu's initial explanation.
- Adds a DevBench status query for the new result-shaping and stabilization
  settings so manual runtime checks can inspect their configuration.

The new controls are opt-in. This local package build does not establish
Skyrim VR, stereo, temporal-quality, or headset performance acceptance.
