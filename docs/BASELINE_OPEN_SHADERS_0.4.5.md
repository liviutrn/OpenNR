# Open Shaders 0.4.5 teacher baseline

## Identity

OpenNR-VR is based on the private Open Shaders DLSSNR VR 0.4.5 MGO developer package, not on an assumed public tag. The package manifest identifies it as:

- display name: `Open Shaders DLSSNR VR 0.4.5 (MGO Dev)`
- package version: `0.4.5-mgo-vr.1-private-dev`
- variant: `single-mo2-fomod-private-dev-vr`
- generated: `2026-09-03T01:21:18.7209874Z`
- archive SHA-256: `384B9EE1DE55A128BD842F8FFBE279B115F1451C6648873985036AE924D437CB`

The package points to this local source checkout:

`D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d`

Its source identity is:

- branch: `feature/dlssnr-vr`
- commit: `3bd930002a96135cff5b092a7e55e11cf28bc912`
- FidelityFX submodule: `c6eb2b7f665ca4f4ddd95d45011af506baec3ec5`
- source checkout: dirty (`SourceDirty: true` in the package manifest)

The dirty-state flag matters: this is a reproducible pointer to the exact local teacher state, but it is not evidence of a clean upstream release. The source CMake project still identifies the Open Shaders plugin as version `2.10.1`; `0.4.5-mgo-vr.1-private-dev` is the private package/runtime profile version.

## Runtime contents relevant to this project

The package contains the Open Shaders `CommunityShaders.dll` plus the DLSSNR runtime. The manifest records:

- `CommunityShaders.dll`, version `2.10.1.0`, SHA-256 `8DDBE76180F69F432114F7C933688AB462C629C9418D604E834191A6B837FFC6`
- `nvngx_dlssnr.dll`, version `310,8,0,0`, SHA-256 `E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E`
- DLSSNR Feature ID `18`
- Release/Ninja build, with the package's `dlssnr-only-vr` runtime profile

The NVIDIA runtime is a private, proprietary input. It is deliberately not copied into OpenNR-VR, committed, or redistributed.

## Baseline handling

OpenNR-VR is a research overlay around the teacher rather than a fork of the teacher checkout. The existing dirty worktree is preserved; the M0.2 capture hook is a small, opt-in source-side integration in that worktree, while dataset tooling and analysis remain in OpenNR-VR. The hook preserves a clean fallback when capture is disabled.

The package documentation describes the default teacher route as NR enabled, Full (100%) model resolution, post-upscale NR, and no pre-upscale NR. The renderer also contains optional pre-upscale and reduced-resolution routes, so each capture record labels the active route and model resolution instead of inferring them from the package name.

## Re-verification commands

Run these against the local baseline before a runtime experiment:

```powershell
Get-FileHash -Algorithm SHA256 `
  'D:\.CODEX_Projects\DLSS_5_SKYRIM\dist\Open-Shaders-DLSSNR-VR-0.4.5-MGO-Dev-PRIVATE-DLSSNR-ONLY-MO2.zip'

git -C 'D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d' rev-parse HEAD
git -C 'D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d' status --short
```
