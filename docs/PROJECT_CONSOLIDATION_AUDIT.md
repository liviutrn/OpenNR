# OpenNR 2.15.0 consolidation and forensic audit

## Outcome and authority

The canonical source is `D:/.CODEX_Projects/OpenNR-VR`. The separate leading-space workspace `D:/ .CODEX_Projects/OpenNR-VR` was investigated and is historical.

The fixed adaptive NR/crop branch at `a39a25b5` plus correction 20260913-B was independently snapshotted (1,209 files, 101,281,363 bytes), hash-checked for concurrent changes, committed as `44bae628`, and imported with both parents at `987a9284`. The research snapshot `d0974a67` preserves 553 previously modified/untracked files and their evidence. The active source/package version is now 2.15.0; historical versioned reports and changelogs are retained.

The imported build includes its adaptive controllers, shaders, GPU/active-submit timing, guide dimensions, VR/UI/map/input and HDR changes. Existing adaptive enable defaults remain false; saved settings were not edited. Capture's fresh output default is now C:/OpenNR/Captures, with configured paths checked before recording.

The current-phase validation record is `CONSOLIDATION_MANIFEST.json`. Final source integration is local only. No remote push, public release, game launch or active-install deployment occurred. No learned model or recovered teacher was promoted.

## Discovery coverage

- Enumerated C:, D:, E:, G:: **2,085,758 file records**, **253,544 directories**, **283 reparse points**.
- Recorded **419 exclusion/access-error records**. System directories, recycle bins and Git object internals were excluded from the filesystem walk; Git history was inspected separately. Aliases V:, W:, X: were not counted as separate physical volumes.
- Verified **66,853 source/recovery file copies** including additional logo/address-library inputs, with SHA-256 manifests. Inspected 75 discovered repository records across owned source, SDKs and research clones.
- Found **6,334 exact duplicate source groups**, comprising **57,984 extra copies**. Most are repeated SDK/runtime source in historical workspaces. These are identified candidates, not a claim that every duplicate was deleted.
- Imported 172 sibling/top-level research files, plus the leading-space evaluator, into indexed historical directories. Two zero-byte leading-space files are placeholders, not authoritative implementations. The evaluator differences are equivalent formatting and a consistently renamed gallery key; the canonical implementation was retained.
- All Python source in the inspected canonical tools passed AST parsing. Absolute references were inventoried in 54 source/config files; maintained runtime/build/teacher entry points were repaired. Historical experiment paths remain explicitly historical.

This is a live filesystem inventory, not a simultaneous disk image. Metadata enumeration and hash classification do not imply line-by-line semantic proof of every external SDK or personal file. Detailed source records, reference lists and exclusions are in the external audit database and JSON reports.

## Canonical source and history decisions

| Source | Decision |
|---|---|
| OpenNR-VR research main | Preserve history and uncommitted research evidence; retain compatible tools layout |
| Fixed 2.14.8 adaptive branch + correction B | Main runtime authority; promote complete build to 2.15.0 |
| Older vendor runtime and 2.14.x/adaptive/eye-tracking worktrees | Compare and preserve recovery commits; keep histories under refs/archive/legacy/* |
| Unversioned Skyrim parent scripts/docs/reports | Import as historical references; new maintained build wrapper replaces old absolute-path packaging entry |
| DLSS5_Video source | Preserve relevant source as reference; do not absorb the unrelated application/runtime install |
| C:/OpenNR top-level study scripts | Preserve in dated experiments with data and research lineage external |
| Report applications | Relocate externally with verified compatibility junctions |
| Private native carrier, model weights, captures, caches | External inputs; no source commits or redistribution |

Nine legacy runtime source trees were committed as recovery states and checked with full `git status --porcelain`. Their source changes are clean. The historical September 12 adaptive tree had three invalid submodule Git pointers. Original pointers were backed up; independent metadata clones were created externally, their original pinned HEAD/index restored, and pointers repaired in place. No SDK source checkout or content replacement was performed. All nine now report clean status, including submodules.

The runtime history is shallow at its inherited boundary. A bundle passed the basic verifier but failed an isolated clone due to the shallow parent traversal. An independent local clone preserving the shallow boundary passed connectivity verification and was used for import. The original history was not rewritten or silently fabricated.

## Storage migration

**106,856 files / 79,182,413,035 bytes (73.74 GiB) were verified and removed physically from D:** across 20 completed directory relocations. Every move used copy, source/destination SHA-256 comparison, file count/size checks, a compatibility junction, and deletion of only the verified redundant copy. Original source project directories remain.

The live relocation ledger, rather than pre-copy estimates, determines totals. Two unsuccessful whole-.git relocation attempts are excluded. The Git object store was successfully relocated separately; the refs/index directory remains in place.

| Previous path | Physical destination | Bytes |
|---|---|---:|
| `D:/.CODEX_Projects/OpenNR-VR/.git/objects` | `C:/OpenNR/Repositories/OpenNR-VR.git/objects` | 1,924,449,703 |
| `D:/.CODEX_Projects/OpenNR-VR/_dlss5_amd_hip_linux_report_app_20260913` | `C:/OpenNR/Reports/LegacyApps/_dlss5_amd_hip_linux_report_app_20260913` | 4,808,450 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/dist` | `E:/OpenNR_Builds/Legacy-20260913/dist` | 288,574,503 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/work/open-nr-eye-tracking-experiment-20260912/build` | `E:/OpenNR_Builds/Legacy-20260913/work/open-nr-eye-tracking-experiment-20260912/build` | 490,095,026 |
| `D:/.CODEX_Projects/OpenNR/out` | `C:/OpenNR/Relocated/OpenNR-legacy-output-20260913` | 49,771,165 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/vendor/open-shaders-dlssnr-vr-091bfb4d/dist` | `E:/OpenNR_Builds/Legacy-20260913/vendor/open-shaders-dlssnr-vr-091bfb4d/dist` | 740,676,595 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/work/open-nr-adaptive-handoff-2.14.8-fixed-20260913/build` | `E:/OpenNR_Builds/Legacy-20260913/work/open-nr-adaptive-handoff-2.14.8-fixed-20260913/build` | 14,580,621,763 |
| `D:/.CODEX_Projects/OpenNR-VR/_opennr_gen_final_report_app2` | `C:/OpenNR/Reports/LegacyApps/_opennr_gen_final_report_app2` | 12,329,195 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/work/open-nr-2.14.5-all-features-20260912/dist` | `E:/OpenNR_Builds/Legacy-20260913/work/open-nr-2.14.5-all-features-20260912/dist` | 228,102,246 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/work/open-nr-eye-tracking-experiment-20260912/dist` | `E:/OpenNR_Builds/Legacy-20260913/work/open-nr-eye-tracking-experiment-20260912/dist` | 227,933,879 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/work/open-nr-adaptive-handoff-2.14.8-fixed-20260913/dist` | `E:/OpenNR_Builds/Legacy-20260913/work/open-nr-adaptive-handoff-2.14.8-fixed-20260913/dist` | 518,577,570 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/work/open-shaders-adaptive-nr-handoff-study-opennr-20260913/build` | `E:/OpenNR_Builds/Legacy-20260913/work/open-shaders-adaptive-nr-handoff-study-opennr-20260913/build` | 7,596,698,380 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/work/open-shaders-2.12.0-open-nr/build` | `E:/OpenNR_Builds/Legacy-20260913/work/open-shaders-2.12.0-open-nr/build` | 13,043,129,285 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/work/open-shaders-2.12.0-open-nr/dist` | `E:/OpenNR_Builds/Legacy-20260913/work/open-shaders-2.12.0-open-nr/dist` | 142,469,023 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/vendor/open-shaders-dlssnr-vr-091bfb4d/build` | `E:/OpenNR_Builds/Legacy-20260913/vendor/open-shaders-dlssnr-vr-091bfb4d/build` | 16,576,950,253 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/staging` | `E:/OpenNR_Builds/Legacy-20260913/staging` | 3,252,452,837 |
| `D:/.CODEX_Projects/OpenNR-VR/_opennr_gen_final_report_app` | `C:/OpenNR/Reports/LegacyApps/_opennr_gen_final_report_app` | 1,875,304 |
| `D:/OpenNR_TrainingInputs` | `C:/OpenNR/TrainingInputs/Migrated-D-20260913` | 8,943,283,631 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/work/open-nr-2.14.5-all-features-20260912/build` | `E:/OpenNR_Builds/Legacy-20260913/work/open-nr-2.14.5-all-features-20260912/build` | 5,443,937,640 |
| `D:/.CODEX_Projects/DLSS_5_SKYRIM/open-shaders-dlssnr-public-pr/build` | `E:/OpenNR_Builds/Legacy-20260913/open-shaders-dlssnr-public-pr/build` | 5,115,676,587 |

Existing out/artifacts junctions to C: were retained. Reinspection found no remaining discovered OpenNR .npy/.npz/.pt/.pth/.onnx/.engine/.safetensors training payloads physically on D:. Remaining large legacy SDK binaries, documents, game assets and source-adjacent carrier copies are inventoried separately; they were not mistaken for training datasets or deleted as junk.

H: is not mounted. The FullRes pilot junction pointing to H: remains unresolved. That is unavailable data, not evidence of deletion during this task. Old WSL reparse/staging remnants and recovery quarantine are preserved.

## Dependencies and build changes

Runtime dependencies are now explicit under C:/OpenNR/Dependencies/runtime-2.15.0, with per-directory file counts, byte totals and content-tree hashes. The build uses external vcpkg libraries and recorded SDK/helper sources. MSVC 19.44 rejects the optional CommonLib prebuilt compiled by 19.51, so the matching source was compiled successfully. No toolset incompatibility was bypassed.

Build outputs, package staging and archive verification are on E:. Automatic deployment is OFF. The private carrier is passed explicitly and remains hash-identical to the validated NVIDIA-signed input. The VR helper is another explicit external package input. Source/package gates continue checking their presence.

Source version, CMake source-contract version, active package notes and package preset descriptions are 2.15.0. The older changelog and experimental package marker were moved into historical documentation so the new archive contains exactly one version-matched changelog.

The native teacher harnesses previously used a 16-argument Execute call and could not compile against the main runtime. Both now construct the exact Feature18GuideContract, using the current renderer's guide policy. Their current results must not be labeled exact reproductions of older-runtime benchmarks.

Python maintained writers reject physical D: output. Native capture and benchmark output resolves the existing ancestor through GetFinalPathNameByHandleW; a native alias test caught and corrected an initial weakly_canonical-only implementation that did not resolve X: reliably.

## Validation

- Release CommunityShaders.dll build: version 2.15.0.0; source contract checks pass.
- C++ suite: 171 cases, 2,357 assertions passed, including adaptive NR/crop cases.
- Three adaptive/crop compute shaders compile with FXC cs_5_0.
- Eight Python suites passed: student identity/gradients, recurrent model, raw cache, temporal capture, native guide alignment, optimizer resume, master dataset and master audit.
- Five Python storage tests pass, including D: rejection, alias/junction resolution and precedence.
- Native contract test passes for dimensions/scales, invalid dimensions and D:/X: output rejection.
- Small CPU train/save/resume/evaluate/ONNX workflow passes; exact resumed optimizer update matches; ONNX checker passes. Synthetic fixture only, no model promotion.
- Both native teacher executables and the CUDA texture bridge build. No-input CLI calls produce the expected usage error without running inference.
- AIO manifest and exact manual-package-stage validation pass. Archive extraction is compared file-for-file and hash-for-hash with the validated stage.
- Canonical Git connectivity and diff whitespace checks pass. No credentials or large model payloads were found in the reviewed staged source.

Clean-checkout and capture-disabled configuration evidence is recorded in the [final validation supplement](CONSOLIDATION_VALIDATION_2.15.0.md). Capture-enabled 2.15.0 is the built/package artifact. Configuration-only evidence is not a second capture-disabled DLL build.

## Remaining acceptance boundaries and recovery

Live HMD/stereo output, transitions during rapid motion/disocclusion, restoration under sustained headroom, temporal appearance, native resource/cache stability and delivered frame timing remain unverified. The resource-envelope rejection fallback is retained: crop tier changes hold until restart; NR can continue adapting. This task does not prove native feature caching or imperceptible handoffs.

Historical scripts with missing raw sources or obsolete absolute paths remain research records, not certified maintained workflows. External upstream research code retains separate licenses and status. No model quality claim changes because its source was organized or committed.

Recovery is at C:/OpenNR/ConsolidationBackups/20260913: verified source copies, original staged/unstaged patches, bundles, shallow-aware clone, initial repository records, submodule pointer backups, per-file migration manifests, dependency hashes and build/test logs. Runtime historical refs are available from the canonical repository. Keep the external Git object store with the repository backup. Do not delete original project folders or external recovery stores solely because the canonical worktree is clean.
