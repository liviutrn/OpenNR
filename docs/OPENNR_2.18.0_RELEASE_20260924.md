# OpenNR 2.18.0 local promotion

Date: 2026-09-24. This release promotes the tested 2.17.0 VR performance
candidate to `main` with the Skyrim VR address-library startup fix.

## Source and branch selection

- `main` fast-forwarded from `25d0b7a0` through the 2.16.0 upstream refresh,
  2.17.0 performance candidate, and VR startup fix `e200f6f4`.
- Older experimental branches were reviewed separately. Mixed-scale temporal
  reuse and learned-residual-student experiments were not promoted into the
  runtime because this local HMD test did not validate those paths.
- Uncommitted research and training files in the checkout were preserved and
  are outside the 2.18.0 package.

## Local VR evidence from 2.17.0

- The user completed roughly 40 minutes in Skyrim VR, reported better
  performance, and saw no visible problems. The last launcher exit code was 0.
- `CommunityShaders.log` reported 46 feature INI files loaded, no feature-load
  or shader-compile failures, and successful DLSS NR feature creation for both
  eyes. SKSE reported `CommunityShaders.dll` loaded correctly.
- The session used multiple settings and 14 manual capture bursts. All 833
  captured frames reported complete, with no dropped frames; capture
  backpressure occurred. A later 70% per-eye resource extent and different
  scenes prevent attributing the perceived speedup to the new defaults alone.
- The log still records a safely skipped VR shadow viewport adapter, a
  FullScreenBlur adapter preflight mismatch, and missing optional Effects11
  `enbeffect.fx` preset. A burst of shadow-light safety warnings needs a
  focused future review if it recurs or produces visible defects.

## Build and package verification

- A separate MSVC/VS2022 Release build completed in
  `E:/OpenNR_Builds/2.18.0`; the DLL file version is `2.18.0.0` and its
  SHA-256 is
  `6E14C6BA194C4ACBF7C7D676FFE0A14DFD4BEF77A2F994CE63DAA5D8DEEC5A5E`.
- The native suite passed 230 cases and 9,601 assertions. The release source
  contract and AIO manifest validation passed.
- `7z t` verified 521 files and 105 folders in
  `E:/OpenNR_Builds/2.18.0/dist/OpenNR 2.18.0.7z`. The archive is
  228,748,655 bytes; SHA-256 is
  `F538F1390C4BC161AA8A5E09E99B9F8E7F032E02539B97A9F608E362C9C27F74`.
  Its only versioned package changelog is `OPENNR-2.18.0-CHANGELOG.md`.
- The extracted archive and installed mod match on all 521 paths and SHA-256
  hashes. Five build-stage extras, including RenderDoc and the PDB, were kept
  out of the installed release.

## Local installation and rollback

- Installed at `E:/MGO-RC3-fresh/mods/OpenNR 2.18.0` as a separate mod.
- Cloned the tested profile to `MGO NSFW - OpenNR 2.18.0`, enabled 2.18.0,
  disabled 2.17.0 in that clone, and selected it in `ModOrganizer.ini`.
  Exactly one enabled mod provides `CommunityShaders.dll` in the new profile.
- The shared `SettingsUser.json` hash is unchanged by installation. The
  2.17.0 mod and profile remain installed and selected only when explicitly
  restored.
- Original `ModOrganizer.ini`, the 2.17.0 profile modlist, and shared user
  settings were copied to
  `E:/MGO-RC3-fresh/_OpenNR_Pilot_Backups/2.18.0-promotion-20260924`.
  Its `ROLLBACK.txt` gives the exact profile-selection recovery step.

## Acceptance limits

The user accepted the observed performance and appearance for promotion. The
screenshots and runtime log do not quantify a controlled speedup, establish
both-eye temporal quality in every scene, or measure sustained headset frame
timing. No new learned model is promoted.
