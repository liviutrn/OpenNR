# DLSSNR MGO Skyrim VR 0.2.2-mgo-vr.1

Status: experimental MO2/FOMOD preview ready for isolated testing.

## Deliverable

Package: `dist/DLSSNR-MGO-VR-Preview-0.2.2-mgo-vr.1-MO2.zip`

- Archive size: 15.85 MiB
- Archive SHA-256: `D9E6E23361180711F533BE2159FDA9677F60A11211EBD44971A3C821DCF6B2A7`
- Extracted files: 436
- Core payload files recorded in the manifest: 425
- Public ZIP DLLs: `00 - DLSSNR Core/SKSE/Plugins/CommunityShaders.dll`
- Packaged DLL SHA-256: `CC8575907AAA5618AFBA55E9D57A186172639F6826DAC397876E342DDC0A1620`

The package contains the rebuilt Open Shaders payload, FOMOD metadata, the
runtime-staging helpers, manifest hashes, a changelog, and rollback guidance.
It does not contain Feeder, RenoDX, ReShade wrappers, the old bridge, or
proprietary NVIDIA/Streamline runtime DLLs. The ZIP's helper scripts stage
those user-owned/authorized runtime files into this one MO2 mod and back up an
existing staged runtime before replacement.

## Implemented update

The source was fast-forwarded to Open Shaders VR branch commit
`05e037cad2add33a434c09d7b1260d09d331b6a4`.

That upstream change runs the flat SDR neural pass against `kFRAMEBUFFER`
before UI composition and explicitly excludes the VR route. The existing local
VR/MGO changes, including the VR motion/depth handoff and batching/fence work,
were preserved and rebuilt into the DLL. This is primarily a correctness and
temporal-input improvement; it is not a measured FPS guarantee.

The build preset was made compatible with the installed CMake 3.31 toolchain,
and the build used the VS2022 x64 shipping configuration. A fresh configure
was used so stale vcpkg paths could not select the wrong triplet. Shader tests
were disabled for this packaging build because the repository's shader-test
subproject currently requires CMake 4.2; this does not disable runtime shader
features in the packaged plugin.

The source worktree is intentionally dirty because it contains preserved local
MGO/VR work. The package manifest records `SourceWorktreeDirty: true`.

## MO2/MGO test procedure

1. Keep the normal `Mad God Overhaul - NSFW` profile disabled for this test.
2. Install the ZIP in MO2 as a new mod. Use a copied or isolated profile; the
   existing `DLSS5 SkyrimVR Open Shaders DLSSNR` profile is the intended model.
3. Enable this package and disable conflicting entries in that test profile:
   `Community Shaders Expanded (CSX)`, its CSX VR shader cache, the old
   `DLSS5 SkyrimVR Experimental` mod, any DLSS5/DX11 bridge, RenoDX Feeder, and
   ReShade DLSS wrappers.
4. Extract/open the installed mod's `TOOLS` folder and run the runtime helper.
   Select this package's mod folder, the existing MGO/CSX mod folder that holds
   the signed Streamline runtime, and the authorized neural runtime suitable
   for the GPU. The helper records the hashes and creates a backup under the
   mod's `TOOLS` directory.
5. Launch Skyrim VR through MO2/SKSEVR. Do not use frame generation for the
   first run. Open Open Shaders, select the DLSS neural-rendering path under
   Upscaling/Foveated DLSS, and capture the status/log evidence.
6. For acceptance, record headset refresh, application frame time, GPU frame
   time, reprojection/ dropped-frame state, and neural evaluation/frame-delivery
   counters with the feature ON and OFF at the same save/location. A desktop
   mirror FPS number alone is not VR acceptance evidence.

## Rollback

Disable this single MO2 mod and return to the original MGO profile. The build
and package steps did not modify the physical Skyrim VR folder, the normal MGO
profile, saves, or the active game installation.

## Current verdict

The implementation is viable for a controlled Skyrim VR/MGO test. It is an
in-process Open Shaders D3D11 route, not a Feeder route. The new build should
improve placement of the flat neural pass and retain the VR synchronization
work, but a performance improvement is unproven until the paired headset A/B
measurement above succeeds. If the neural evaluation counter stays at zero or
only one eye updates, revert immediately and keep the result classified as a
loader/integration failure rather than an FPS result.
