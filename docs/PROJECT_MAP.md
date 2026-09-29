# OpenNR project map — 2.15.0

| Work | Canonical location | Boundary |
|---|---|---|
| Native runtime, adaptive NR/crop, VR/UI | `runtime/open-shaders/src` | Main development runtime; live acceptance remains separate |
| Runtime shaders | `runtime/open-shaders/features`, `runtime/open-shaders/package/Shaders` | Preserve CommunityShaders resource identity |
| Capture | `runtime/open-shaders/src/Features/OpenNRCapture.*` | Native stereo guides, resets and provenance |
| Native replay and texture bridge | `native/teacher_bench`, `native/teacher_sequence_bench` | Explicit Feature18GuideContract; current-runtime harnesses |
| Python models, cache, training and evaluation | `tools` | Research modules retain compatible import layout |
| Maintained model workflow | `train_student.py`, `train_fast_student.py`, `build_student_cache.py`, `build_raw_crop_cache.py`, `infer_student.py`, `export_fast_student_runtime.py` under `tools` | External output guards; no model promoted |
| Dataset validators | `tools/validate_capture.py`, `tools/validate_temporal_capture.py`, `tools/validate_capture_config.py` | Validate available data without changing frozen lineage |
| Configuration | `config` | Examples tracked; local machine values ignored |
| Tests | `tests`, `tools/test_*.py`, `runtime/open-shaders/tests` | Fixtures plus native/controller tests |
| Build and package | `tools/Build-OpenNR.ps1` and runtime CMake targets | E: output; no auto-deployment |
| Historical research and sibling source | `experiments`, dated `docs` | Evidence and reproduction status, not automatic promotion |
| External dependencies | `C:/OpenNR/Dependencies/runtime-2.15.0` | Verified snapshot manifest; private inputs outside Git |
| Recovery and machine inventory | `C:/OpenNR/ConsolidationBackups/20260913` | SHA-256 copies, bundles, patches, SQLite inventory and logs |

Runtime history is imported through a two-parent merge, not flattened into an unrelated copy. The pre-consolidation research history remains an ancestor. `refs/archive/legacy/*` preserves reconciled sibling histories. Historical source checkouts remain available for recovery; maintained commands do not require their paths.

The older benchmark reports used a previous positional runtime API. Current harnesses use explicit color/depth/motion/output extents and the current runtime's low-resolution guide policy. Re-running an old experiment with the new harness is a new runtime lineage, not an exact historical replay.
