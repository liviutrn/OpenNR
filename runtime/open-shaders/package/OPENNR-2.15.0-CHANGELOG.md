# OpenNR 2.15.0

Adaptive NR and adaptive Crop are now part of the main development runtime.
This release preserves the fixed 2.14.8 baseline and correction 20260913-B,
including the VR/UI, input, map, timing, guide and transition changes.

- Adaptive decisions use fresh SteamVR GPU and active-submit workload samples.
  Missing or repeated timing holds quality.
- Crop handoffs render current-frame pixels over the union of the two tiers.
- NR handoffs use elapsed-time fades and reject invalid or outlying history.
- NR and crop restoration coordinate through headroom and dwell requirements.
- A rejected native crop resource envelope holds crop changes until restart.
  NR may continue adapting; this fallback is not proof of native cache safety.
- Current enable defaults and existing saved settings are preserved.
- Source, capture, research and build entry points are consolidated in OpenNR-VR.
  Large data, dependencies and builds use external storage.

The DLL remains CommunityShaders.dll for SKSE and asset compatibility.
Source/build/package checks and live headset acceptance are separate gates.
Live stereo, temporal quality, transitions and sustained frame timing remain
unverified by this consolidation. This is a local package, not a public release.
