# OpenNR 2.20.1 local release

Date: 2026-09-27. Native Feature 18 line. V5/Turbo and research stay on their own branches.

## Changes

See `runtime/open-shaders/package/OPENNR-2.20.1-CHANGELOG.md`. Reasoning and measured pass costs are in `docs/OPENNR_SHADER_SETTINGS_ANALYSIS_20260927.md`.

- **In-headset Settings Benchmark.**
  - Code: `SettingsBenchmark.{h,cpp}` plus the pure `BenchmarkPolicy.h`.
  - Tick: `Deferred::StartDeferred`. Settings switches run as SKSE main-thread tasks through `Util::Settings::ApplyPatch` with the scene-layer guard.
  - Timing: SteamVR compositor frame timing.
  - UI on the Neural Rendering page; DevBench `startSettingsBenchmark` / `cancelSettingsBenchmark` / `settingsBenchmarkStatus`.
  - Editable `SKSE/Plugins/CommunityShaders/OpenNR-SettingsBenchmark.json` (17 variants; 15 enabled by default).
- **DLSS presets E and F (CNN)**: indices 5 and 6, mapped in `Streamline.cpp`. E is excluded from Foveated "Faster" mode.

## Verification

| Check | Result |
|---|---|
| Build | `E:/OpenNR_Builds/2.20.1`, MSVC 19.44, LTCG on, same dependency snapshot and private `devbench-api` copy as 2.20.0; no compiler warnings |
| DLL | 2.20.0.0 → **2.20.1.0**, SHA-256 `B88AD1E1A55A16E195D5085A6AF494AD82D0E0A4C82D693A0715A3B62DD208A0` |
| Native tests | 244 cases / 9,724 assertions passed, including 6 new `[benchmark]` cases (schedule, drift-balanced repeats, percentiles, bracketed deltas, interrupted blocks) |
| Source contracts / AIO manifest | Passed; the manifest now requires the benchmark JSON |
| Archive | `E:/OpenNR_Builds/2.20.1/dist/OpenNR 2.20.1.7z`, 228,834,730 bytes, SHA-256 `417700C9016F49526C68746291B520F9CBA3350C8E2D2A585FA53E71A50FF8F2`; `7z t` OK, 523 files |

## Install

- Mod `E:/MGO-RC3-fresh/mods/OpenNR 2.20.1`, from the verified archive.
- Profile `MGO NSFW - OpenNR 2.20.1`, cloned from 2.20.0 with 2.20.1 enabled and 2.20.0 disabled. It is the only enabled `CommunityShaders.dll` provider.
- The selected MO2 profile and the shared `SettingsUser.json` were not changed by this release.

## Not established

- No headset run yet, so the benchmark's in-game behaviour is untested. In particular: compositor timing through Virtual Desktop, and hitch-free live switching for every variant.
- Whether DLSS 310.9 honours preset E/F is unknown; the benchmark will show it.
