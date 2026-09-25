# OpenNR 2.17.0 local performance candidate

Date: 2026-09-24. This candidate follows the committed 2.16.0 upstream
refresh and adds fresh VR rendering-cost defaults plus Open Shaders PR #756's
camera reprojection fix. Its build, package, and installation evidence will
be recorded below only after each action succeeds.

## Source

- 2.16.0 upstream refresh commit: `93011a3b`.
- Focused upstream fix: [Open Shaders PR #756](https://github.com/alandtse/open-shaders/pull/756)
  at `7f4672b9e1e4b2b86a0dda50ac611480d27583a7`.
- Community NR review: [DLSS NR community review](DLSS_NR_COMMUNITY_REVIEW_20260924.md).
- Experimental defaults: VR AO 2 slices / 4 steps; incremental Skylighting
  and two-frame update intervals; hardware-gated VR VRS enabled.

## Validation

- MSVC/VS2022 `CommunityShaders` build passed; DLL file version is
  `2.17.0.0` and SHA-256 is
  `3D4E34C947D7996FEAD70E541E613ACC92E2D59D28B0AD3FB09D2F6252F2894F`.
- Native Catch2 tests passed: 230 cases and 9,601 assertions. CTest passed
  `CppUtilTests` 1/1.
- Release source contract and AIO validation passed. `7z t` verified 521
  files and 105 folders; extraction contains only
  `OPENNR-2.17.0-CHANGELOG.md` and its DLL matches the built hash.
- Archive: `E:/OpenNR_Builds/2.17.0/dist/OpenNR 2.17.0.7z`, 228,748,066
  bytes, SHA-256
  `56A6DCFAA2263651D4D675AF5DF64A5C82A2B219037B7166E2DF33F6E1BB6D81`.
- Python suite passed: 150 tests in 177.481 seconds, 7 skipped. The native
  test harness was made compatible with the external build's generated-header
  and vcpkg paths; `OPENNR_GENERATED_DIR` and `OPENNR_TEST_VCPKG_ROOT` were
  supplied for this run, along with MSVC's `INCLUDE` path.

## Local installation and rollback

- Copied the verified extraction into
  `E:/MGO-RC3-fresh/mods/OpenNR 2.17.0`; installed DLL hash matches above.
- Cloned `MGO NSFW - 4.0 BETA` as
  `MGO NSFW - OpenNR 2.17.0 Performance Test`. The clone disables
  `OpenNR 2.15.1` and enables `OpenNR 2.17.0`; it is selected in MO2.
- The shared overwrite `SettingsUser.json` was backed up, then changed only
  in five performance fields: AO `NumSlices` 3 to 2, `NumSteps` 6 to 4;
  Skylighting incremental and reduced-frequency updates false to true;
  VRS enable 0 to 1. NR and DLSS settings were preserved byte-for-byte.
- Backups of the original shared settings, `ModOrganizer.ini`, and the base
  profile modlist are in
  `E:/MGO-RC3-fresh/_OpenNR_Pilot_Backups/2.17.0-local-test-20260924`.
  To roll back completely with MO2 closed, restore `SettingsUser.json` to
  `overwrite/SKSE/Plugins/CommunityShaders/SettingsUser.json` and
  `ModOrganizer.ini` to the MGO root from that backup. The prior mod and
  profiles were not removed.

## Acceptance

No source or package check establishes delivered SkyrimVR Feature 18 frames,
both-eye temporal stability, HMD appearance, frame pacing, or a performance
gain. The user must compare the new profile against the preserved fallback.

## Later VR test and corrected local build

The first local launch exposed an old 2.15.1 DLL and shader in MO2's shared
`overwrite` folder. Both were backed up and removed from that override path;
the partial shader cache was also backed up before recompilation. A second
launch exposed missing VR Address Library ID 100979 in the legacy shadow
viewport adapter. Commit `e200f6f4` skips that adapter on VR. The rebuilt
2.17.0 DLL SHA-256 was
`D2443B646C23AC5B7BB8FE127C6C8DDD96B89B5E7287E4CC4EAC50DCA29D585B`;
the corrected archive SHA-256 was
`8DDBB8716687C619DA2C3612BB319D5D63F31A4BFA765423B36C14EF550CF66A`.
These supersede the initial candidate hashes above for the installed test.

The user subsequently played for roughly 40 minutes, reported better
performance, and saw no visible problems. The OpenNR log showed successful
DLSS NR creation for both eyes, no feature-load or shader-compile failures,
and a normal launcher exit. Settings changed during the session, so the
perceived improvement is not a controlled benchmark. See the 2.18.0 release
note for the promotion decision and remaining compatibility warnings.
