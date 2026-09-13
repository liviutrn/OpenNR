# OpenNR package contract

## Current package

The current release has one user-facing archive and one MO2 payload:

- `OpenNR 2.14.1.7z`
- MO2 display name: `OpenNR 2.14.1`
- Repository identity: [github.com/olekspa/OpenNR](https://github.com/olekspa/OpenNR)

OpenNR Capture is integrated into this package. It is compiled and registered
so one installation has the complete feature set, but the capture master gate
is **disabled by default**. Installing the package does not enable hotkey
polling, capture resources, GPU readbacks, previews, or `frames.jsonl` output.

The package retains `CommunityShaders.dll` and the upstream
`SKSE\Plugins\CommunityShaders.dll` compatibility layout intentionally. The
human-facing fork, menu, README, package, and branding are OpenNR; the runtime
compatibility identity is not renamed in a way that would break existing SKSE
loaders or settings.

## Contents and exclusions

The single archive contains the audited native Skyrim VR DLSS/DLSSNR/Reflex/PCL
runtime set, stock signed RTX 50 `nvngx_dlssnr.dll`, Microsoft x64 runtime DLLs,
the OpenNR shader/UI payload, ImGuiVRHelper v1.7.0, TerrainHelper, FOMOD
metadata, and third-party notices.

The lean native Feature 18 package intentionally omits optional or unrelated
payload that caused previous size growth:

- RenderDoc tooling and registration;
- OpenXR/eye-tracking payload;
- textures, meshes, and particle-light asset trees;
- StreamlineDX12 and FidelityFX runtime trees;
- `CommunityShaders.pdb`; and
- personal `SettingsUser.json` overrides.

The package audit records every included file, the largest files, excluded
source bytes, runtime hashes, and the capture default-off markers. Do not hand
rename a raw upstream AIO archive or add a second OpenNR Capture archive.

## Installation and first test

1. Back up the MGO/MO2 profile and test from a copied profile.
2. Install exactly `OpenNR 2.14.1.7z` as one MO2 mod. Do not combine it with an
   older OpenNR pair, a separate capture archive, or a second runtime copy.
3. Disable conflicting CSX/VR shader-cache, old DX11 bridge, ReShade wrapper,
   and Frame Generation components for the first controlled run.
4. Launch Skyrim VR through the normal MO2/SKSE/SteamVR or OpenComposite route.
5. Open the **Neural Rendering** page. The page formerly labelled `DLSS 5 NR`
   now uses the new visible name; internal `DLSSNR` IDs and saved settings are
   retained for compatibility.
6. Leave OpenNR Capture disabled for ordinary play. If collecting data, read
   the in-game **OpenNR Capture: purpose and safety** explanation first, use a
   dedicated output directory, and enable only the stages needed for the
   experiment.

Capture is expensive and can consume substantial disk space. Keep both eyes
enabled for stereo validation, preserve every sequence, and audit the JSONL and
native guides before training. Capture files do not prove live VR quality,
temporal stability, or frame-budget acceptance.

## Runtime and licensing boundary

The archive supplies the OpenNR component and its audited runtime companions.
The target PC still needs Skyrim VR, SKSE, Address Library, the selected
SteamVR/OpenComposite path, a supported NVIDIA driver/GPU, and the normal mod
stack. This package is an authorized internal test artifact, not a public
redistribution of proprietary NVIDIA runtime files. Check the included
third-party notices and preserve upstream Open Shaders, Community Shaders,
Streamline, and helper attributions when redistributing source or building a
private package.

## Acceptance boundary

Package/build/hash validation is reported separately from live acceptance.
Before promoting a future release, measure native Feature 18 resource binding,
two-eye headset output, gaze/foveation behavior, temporal stability, image
quality, and repeatable VR frame time on the target profile. Alpha and beta
branches are research lanes, not implicit stable-package content.
