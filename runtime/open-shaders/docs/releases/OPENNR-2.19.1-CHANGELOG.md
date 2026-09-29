# OpenNR 2.19.1

- Places Advanced NR Tuning directly below NR Cost and groups adaptive,
  experimental, temporal, shaping, stabilization, and eye-tracking controls
  into collapsible sections. The Neural Rendering page opens with the primary
  visual and cost controls in view.
- Removes the unused Strong preset from the Neural Rendering menu and remote
  preset command. Existing saved Strong values are retained as Custom settings.
- Caps hover-tooltip width against the active UI viewport so menu text wraps
  into readable lines in the desktop mirror and VR panel.
- Keeps the optional NR result shaping and per-eye result stabilizer from
  2.19.0. Both remain disabled by default; Motion stabilization retains motion,
  depth, and color rejection checks.

The local build and shader compilation checks do not establish in-game Skyrim
VR, temporal-quality, or headset performance acceptance.
