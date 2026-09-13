# OpenNR 2.15.0 final validation

Validated source commit: `caadbe82`. Later documentation and the local main merge preserve this source tree.

The Release runtime and capture-enabled AIO package built successfully from the canonical runtime and declared C: dependencies. Automatic deployment was disabled. DLL version is 2.15.0.0. The archive at `E:/OpenNR_Builds/2.15.0/dist/OpenNR 2.15.0.7z` is 228,054,772 bytes and contains 490 files (440,813,081 uncompressed bytes). 7-Zip integrity testing passes; every extracted file matches the validated package stage by path, length and SHA-256.

- Archive SHA-256: `D5374E8DD84609E201065593984E30496083AB936D00058AE9BE73BBC45F9A51`
- CommunityShaders.dll SHA-256: `19DD7C92349CF33846DC5D9584D368C6C224AD870844539B5D700865DFB440D0`

## Clean source and supported workflows

A Git source export at `C:/OpenNR/Validation/CleanCheckout-2.15.0` configured independently into `E:/OpenNR_Builds/2.15.0-clean` with capture both ON and OFF. The OFF generated project excludes OpenNRCapture.cpp and its compile definition. Generated CMake/project files contain no legacy Skyrim workspace or X: source references. External dependencies remain explicitly declared. No original workspace was renamed or made unavailable system-wide; isolation was established through the exported source and inspection of generated dependency paths.

Source-contract validation, native dimension/output-path contracts, temporal fixture tests and the synthetic CPU train/save/resume/evaluate/ONNX workflow passed using the exported source. Resumed optimizer updates match exactly and ONNX checker passes. The export emits nonfatal constant-folding warnings. This is workflow evidence, not model quality or inference-speed acceptance.

A second complete DLL and a capture-disabled DLL were not built. Capture-disabled evidence is configuration and source-selection validation only. The shipped local package is capture-enabled. Main-source validation also passed 171 C++ cases / 2,357 assertions, eight Python regression suites, five storage tests and three FXC shader compilations. Both teacher harnesses and the texture bridge build; native teacher inference was not executed.

## Final inventory and reconciliation

The additional content discovery sweep scanned 181,257 eligible text/source files outside the named project roots: 972 hits and 24 read errors. Triage classified 954 generated Triton cache records, 16 installed game/mod configuration files, one downloaded discussion and one separate AI_UPSCALING user request; none required another owned source import. The machine inventory and error records remain external.

A fresh physical D: scan covered 199,500 files with zero errors and no matching OpenNR training payloads. It does not imply that every binary on every volume was semantically inspected. Verified relocations total 79,182,413,035 bytes across 106,856 files and 20 source locations. All nine reconciled legacy runtime repositories have empty full Git status, including submodules. Their unique source commits and original snapshots remain recoverable.

## Acceptance and rollback

Adaptive NR and Crop are main development features; both retain their existing disabled defaults. Saved settings are preserved. Headset stereo output, motion/disocclusion, transition appearance, menu/map/VR input, resource stability, restoration and sustained frame timing still require live acceptance. H: capture storage remains unavailable. No model was promoted, no remote was pushed and no active game installation was changed.

Recovery root: `C:/OpenNR/ConsolidationBackups/20260913`. The original research main is `b71f8313250b70af5bf4513d91596dbebae0bff8`; adaptive baseline is `a39a25b5edb2bc8f139c06b8fb9efbd95fcdb5f5`, stable correction snapshot `44bae628`, and original-source recovery commit `c6fc308f`. Inspect these through a separate external checkout for comparison or recovery. To undo the promotion on main, first preserve any later work, then revert the final merge with its mainline parent; do not reset away subsequent work. Use per-file migration manifests to copy and verify any storage rollback before replacing a junction. Keep the C: Git object store with all repository backups.

Detailed logs, package file hashes, dependency hashes and legacy reconciliation records are under the recovery root. See [the full audit](PROJECT_CONSOLIDATION_AUDIT.md) and [the compact manifest](CONSOLIDATION_MANIFEST.json).

## Drive alias cleanup follow-up

The final handoff initially left V:, W: and X: SUBST mappings present. They have now been removed: V: mapped Visual Studio vcpkg, W: the September 12 adaptive study, and X: the fixed September 13 adaptive tree. Mapping text is preserved in the recovery root as removed-drive-aliases.txt. No referencing running process, scheduled task, or matching Run/DOS Devices registry persistence was found during cleanup. Removing these aliases does not delete their target folders.

Tests no longer assume that an arbitrary X: drive belongs to OpenNR. The optional Python alias check discovers existing mappings that actually resolve to D: and explicitly skips when none exist. The native direct-D check remains. Earlier actual alias rejection evidence remains valid; no persistent drive is needed for routine testing. Intentional C:/E: storage junctions are retained because they keep generated data physically off D:.

Post-removal checks: CMake configuration passes with physical C:/E: paths; Python storage checks pass (four executed, optional existing-alias case explicitly skipped); the native contract executable rebuilds and passes without V:/W:/X:.
`CommunityShaders` and `cpp_tests` subsequently rebuilt successfully with no SUBST mappings. The C++ suite again passed 171 cases / 2,357 assertions. Build log: `C:/OpenNR/ConsolidationBackups/20260913/build-without-aliases.log`. The existing packaged archive remains the previously verified 2.15.0 artifact; this cleanup changes tests and audit documentation only.
