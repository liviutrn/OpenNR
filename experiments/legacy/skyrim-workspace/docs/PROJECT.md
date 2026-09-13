# DLSS 5 Skyrim VR prototype

This is an isolated experiment for MGO Skyrim VR. The authoritative project
folder is `D:\.CODEX_Projects\DLSS_5_SKYRIM`.

## Current Open Shaders package labels

The current installable pair follows one exact naming contract:

- `Open Shaders DLSSNR VR x.x.x` = public-label internal-LAN build.
- `Open Shaders DLSSNR VR x.x.x OpenNR` = local build with OpenNR.

Both variants are complete one-click MO2 packages with their DLL/runtime set;
the public label does not mean public release or public redistribution. The
`OpenNR` suffix is reserved for the local capture build. Do not add dates,
`MGO Dev`, `private-dev`, fix descriptions, or other suffixes. The build and
FOMOD rules are maintained in [`DISTRIBUTION.md`](DISTRIBUTION.md). Older
prototype names below are historical records, not current package names.

## Safety boundary

- Active MGO install: `E:\MGO-RC3-clean`
- Active profile at staging time: `Mad God Overhaul - NSFW`
- Prototype profile: `DLSS5 SkyrimVR Prototype`
- Prototype mod: `DLSS5 SkyrimVR Experimental`
- Derived VR profile: `DLSS5 SkyrimVR Open Shaders DLSSNR`
- Derived VR mod: `DLSS5 SkyrimVR Open Shaders DLSSNR`
- Baseline backup: `backups\active-profile-baseline-20260829`

The active profile was copied before staging. Its 293 files matched the
baseline backup by path and SHA-256. The prototype mod is enabled only in the
prototype profile. Do not edit the active profile or the Steam game folder by
hand; RootBuilder should materialize the prototype root files only while the
prototype profile is selected.

The game-root manifest guard in `backups\game-root-baseline-20260829` records
the pre-test root files and hashes so any RootBuilder cleanup failure is
visible.

## Staged artifacts

| Artifact | Evidence |
| --- | --- |
| `renodx-dlss5_new.addon64` | supplied local artifact; x64 PE; SHA-256 `25DD0642BEC96FC929456815651824356583DA33678EE2448D70FF3D4D934305` |
| `streamline.zip` | supplied local package; archive listing succeeds; contains `nvngx_dlssnr.dll` and Streamline binaries |
| ReShade | official ReShade 6.8.0 full add-on package; extracted without running the installer |
| D3D11 bridge | Locally rebuilt v1.0.19 x64 add-on with array-aware D3D11/D3D12 mirrors, current RenoDX INI diagnostics, and an isolated feature-input-size probe; staged prototype SHA-256 `3641348B1F92EE486F621736A0309ABFA0A7B4CA4F813C77079E5518C9E99659` |
| `nvngx_dlssnr.dll` | Streamline package version `310.8.0.0`; 165,840,496 bytes |

The v1.0.19 source builds locally with the installed MSVC/Windows SDK; see
[`BUILD.md`](BUILD.md) and `scripts\Build-DLSS5Bridge.ps1`. The original staged
release binary is preserved under `backups\prototype-bridge-before-array-20260829`.

The supplied Streamline package contains Streamline `2.13.0.0` and DLSS
`310.8.0.0`; those newer copies are now staged in the derived DLSSNR mod while
the primary MGO profile remains untouched.

The prototype-only CSX override is currently set to `upscaleMethod=3`,
`qualityMode=0` (DLAA/native AA), and `streamlineLogLevel=2`. Its bridge probe
currently sets `feature_input=1`, which aligns D3D12 feature creation with the
DLSS render-subrect size when Skyrim allocates a padded input texture. Its ReShade
configuration uses `NeuralUplift=1` and `EnableHooks=2`. After correcting the
MO2 priority so this override wins, a saved-game run created and evaluated
DLSS5 feature 18 successfully at `2496x2688 -> 2496x2688` for 60 native
frames. A genuine quality-mode run then produced
`1468x1580 -> 2496x2688`, but feature 18 returned `0xBAD00005` and safely
latched to native output. Super-resolution therefore still needs a resource-
contract fix; the quality-mode sample reached about 99% GPU utilization but
is not a DLSS5 performance result because it ran on the fallback path.

The captured evidence is in `logs\run-corrected-priority-dlaa-20260829.log`,
`logs\run-corrected-priority-quality4-gameplay-20260829.log`, and their
bridge-log companions.

## Open Shaders DLSSNR implementation

As a separate, reversible branch of the experiment, the local
`feature/dlssnr-vr` fork of Open Shaders was built from commit
`091bfb4d39ce00d9b89d7b2ece4af47b6800c163` (2026-08-30). The resulting
`CommunityShaders.dll` is version `2.10.1.0`, SHA-256
`A1DD51F7A987540A45E851DBF32270791F33E26E580A715705712EE9F61DBC`, and is
staged only in the derived profile. The derived mod also contains the
verified `nvngx_dlssnr.dll` 310.8.0.0 and Streamline runtime files under
`Shaders\Upscaling\Streamline`; it does not stage the older bridge, RenoDX
add-on, or root-level ReShade wrapper.

The first controlled VR route test enabled the fork's neural toggle and a
temporary 0.75 per-eye crop because the fork's VR neural path is gated behind
an active non-full-eye foveated route. Skyrim VR created an OpenComposite
session and the RT bridge reported 2496x1344 motion/depth guides. The process
loaded the new Community Shaders and Streamline `sl.dlss.dll`, but never loaded
`nvngx_dlssnr.dll` and produced no neural evaluation evidence. The visible
window remained on the Skyrim loading logo; `Interactive_Water_VR` exhausted
60 startup attempts. The test was stopped after this controlled startup
failure, with no claim of neural output, stereo success, or performance gain.

The temporary settings were restored byte-for-byte to the pre-test generated
configuration. The cropped test state is retained at
`backups\dlssnr-settings-after-cropped-test-20260830-1245.json`.

### HRTF repair and second controlled VR run (2026-08-30)

The first save-load crash was diagnosed from CrashLogger as an
`X3DAudio1_7.dll` exception: `No mhr files found in hrtf directory`. Before
changing the isolated run, the profile and physical replacement DLL were
backed up under `backups\audio-fix-before-rootbuilder-20260830-133827`.
The HRTF payload was then rebuilt through MO2 RootBuilder. The physical
SkyrimVR root now contains the replacement `x3daudio1_7.dll` and all 14 MHR
datasets, including 24, 44.1, 48, and 96 kHz files; the primary MGO profile
was not edited.

The repaired `DLSS5 SkyrimVR Open Shaders DLSSNR` profile launched at
13:40:56, reached the Meta Quest 3 OpenXR path, and loaded the saved game.
`Interactive_Water_VR.log` records `kPostLoadGame` at 13:44:35 and
successful player/3D initialization at 13:44:37. The process remained
responsive in-world through at least 13:49, with no new CrashLogger file.
The live process loaded the isolated fork's `CommunityShaders.dll`,
`sl.dlss.dll`, and `nvngx_dlssnr.dll`; the latter is a loader milestone, not
proof that successful neural evaluations reached the displayed frame. The
settings remain `neuralRenderingEnabled=true`, foveated crop `0.75x0.75`,
and frame generation disabled. A diagnostic snapshot is saved as
`logs\diagnostics-20260830-134853.txt`.

The desktop mirror showed a valid loaded scene at approximately 36-38 FPS.
Headset two-eye quality, neural evaluation count, and matched performance
remain open acceptance gates.

## Acceptance states

1. Static: all staged files exist, versions and hashes match, and the original
   profile still matches its baseline.
2. Loader: ReShade 6.8 loads both add-ons in SkyrimVR and produces fresh logs.
3. Contract: the CSX DLSS/DLAA producer is captured by the DLSS5 add-on and
   feature-18 evaluations succeed; the separate D3D11 bridge call path remains
   diagnostic-only for this Streamline-backed title.
4. Neural: the RenoDX log reports repeated successful native feature-18
   evaluations, not merely a loaded add-on.
5. VR: the headset shows a stable image in both eyes through the selected
   OpenXR path, with no persistent stereo, depth, motion-vector, or compositor
   failure.
6. Performance: repeatable A/B captures report CPU frame time, GPU frame time,
   headset/compositor timing, VRAM, bridge timing, and the scene/resolution.

Static or desktop-mirror success is not sufficient for the VR or performance
acceptance states.
