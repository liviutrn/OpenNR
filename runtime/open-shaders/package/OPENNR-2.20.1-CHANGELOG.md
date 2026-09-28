# OpenNR 2.20.1

Measurement-first performance release. Neural Rendering stays at full 100%
model resolution; nothing changes your settings unless you apply it.

## New

- **Settings Benchmark** (Neural Rendering page, VR). Stand still, close the
  menu, and it measures what each candidate change really saves on your scene:
  each variant is applied live, settled, timed with the SteamVR compositor's
  per-frame application GPU/CPU time, and bracketed by runs of your own
  settings, so drift is measured instead of blamed on a setting. Your settings
  are restored afterwards and nothing is saved. Results show per change
  (GPU ms delta, drift, CPU delta) with an **Apply** button for a live look
  test; Save Settings keeps it. A JSON report is written to
  `My Games/Skyrim VR/SKSE/OpenNR-SettingsBenchmark/`.
  - Built-in candidates: NR off (reference), NR Coverage 85/80%, DLSS preset
    J and E, point-light shadow budget (Formula; 8 redraws / 2 ms), SSGI AO
    lite / off, volumetric lighting quality 1, parallax self-shadows / parallax
    off, hair specular off, terrain blending off, grass mesh LOD, plus
    optional screen-space shadows and wetness.
  - Edit `SKSE/Plugins/CommunityShaders/OpenNR-SettingsBenchmark.json` to add
    your own variants (partial settings patches), then Reload.
  - DevBench: `startSettingsBenchmark`, `cancelSettingsBenchmark`,
    `settingsBenchmarkStatus`.
- **DLSS presets E and F (CNN)**, marked deprecated by NVIDIA but still in the
  310.x SDK and much cheaper than the transformer models. E is kept out of
  Foveated "Faster" mode. If the runtime ignores them the benchmark shows
  ~0 ms.

## Notes

- Changes that need a restart (DLSS quality mode, VR Stereo Reprojection,
  SSR on/off, SSGI resource profile, disable-at-boot features) cannot be
  benchmarked live; compare them across sessions.
- Settings-based variants measure the cost removed by the feature's own
  switch; disabling a feature at boot can save slightly more.

The local build and unit tests do not establish in-headset performance or
visual acceptance.
