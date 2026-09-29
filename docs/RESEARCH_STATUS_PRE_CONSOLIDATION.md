# OpenNR-VR

OpenNR-VR is a research project for learning an open-weight VR neural-rendering model from synchronized Skyrim VR frames. The initial teacher is the working Open Shaders DLSSNR integration, using the private Open Shaders 0.4.5 MGO developer package as the pinned baseline.

## Current status

September 9 active continuation: ordinary 1× MAE <= 0.007 and convincing visual, color and temporal match remain unmet. The current authoritative [crop-temporal continuation report](CROP_TEMPORAL_CONTINUATION_20260909.md) records the completed 18-sequence collection, strict audits, materialized cache, paired training probes, held-out replay, and promotion decision. The active best remains the protected semantic joint-parent checkpoint at ordinary renderer-pilot MAE 0.013283715; neither the 15% nor 5% new-data arm passed the no-regression gate. The 18 sequences are structurally temporal-ready, but crop-only capture still does not establish full-frame teacher/color match, stereo, live-headset, runtime, or VR-budget acceptance. The [full-eye pilot report](FULL_EYE_PILOT_TRAINING_20260909.md), [current sparse full-eye-anchor capture profile](SPARSE_FULL_EYE_ANCHOR_CAPTURE_20260909.md), [superseded every-frame state-probe record](FULL_EYE_STATE_PROBE_CAPTURE_20260909.md), and [storage triage](STORAGE_TRIAGE_20260909.md) contain the current capture, audit and capacity boundaries. Runpod remains unused and no source capture, accepted cache, checkpoint, or provenance tree was deleted.

The separate [OpenNR-GEN final report](OPENNR_GEN_FINAL_REPORT_20260910.md) records the completed offline probes. The key correction is that the pleasing SDXL face was teacher-conditioned and therefore invalid for deployment; the corrected vanilla/raw-input `.08` probe did not reproduce the realism gain, while `.60` became visibly unstable. The immutable 20-scene/40-eye source tranche is preserved, no target route passed the complete acceptance gate, and student training remains blocked. The proof-of-concept summary is [OPENNR_GEN_POC.md](OPENNR_GEN_POC.md), and the older detailed probe log is explicitly marked historical. This path does not alter the Feature18 runtime.

The following reports preserve earlier quality and native-runtime milestones; they do not supersede the current ordinary-cohort results above.

The [dense-feature encoder review](DENSE_FEATURE_ENCODER_REVIEW_20260908.md) records verified upstream DINOv3 options and their limits as a possible later experiment.

The [completed quality-model continuation](QUALITY_CONTROL_RESULT_20260905.md)
adds candidates with improved full-eye teacher error and separately evaluated LPIPS.
The [ongoing teacher-appearance phase](QUALITY_PHASE_20260905.md) records the
matched context-attention experiment. These quality candidates do not replace the
previously benchmarked fast runtime, and teacher-equivalent appearance remains open.

The [September 5 longer-training and native-runtime result](LONG_TRAINING_AND_NATIVE_RUNTIME_20260905.md)
is the latest acceptance report. A 30,000-step continuation improves validation MAE
to 0.023735. Its FP16 student completes an actual D3D12/CUDA/TensorRT/D3D12 stereo
pipeline in about 8.04 ms versus 24.16–24.42 ms for authentic NVIDIA Feature 18
across four offline native-resolution static-pair replays. This establishes scoped
speed feasibility, not teacher-equivalent quality or live Skyrim/headset acceptance.
Selected weights and engine are under `out/student_long_20260905`; the implementation
and reproducible evidence are linked in the report. NVFP4 is not implemented.

Live captures and exploratory spatial student training have now been performed.
The September 4 full-resolution master dataset has been audited and a new guided
spatial student has been trained. See [the trained model, metrics, timings and next steps](STUDENT_V1_RESULT_20260904.md)
and [the full-resolution audit and training preparation report](FULLRES_DATASET_AUDIT_20260904.md).
The selected checkpoint improves native full-frame held-out teacher MAE by 26.70%,
but eager PyTorch takes 58.66 ms per sequential stereo pair and is not VR-ready.
The subsequent [v2 reconstruction and TensorRT experiment](STUDENT_V2_RESULT_20260904.md)
adds lossless input packing, unrestricted residual reconstruction, perceptual-loss
comparisons, and compiled FP16 GPU engines. See that report for current validation
quality and measured engine timings; the older PyTorch timing is not the optimized
runtime limit. Teacher-equivalent appearance and live headset acceptance remain open.
The v2 fast FP16 engine measured 7.65 ms for a native validation stereo pair; this
excludes the renderer, guide preparation, interop and compositor.
Historical bring-up instructions below describe earlier implementation stages;
they are not the current acceptance report. Offline dataset integrity and teacher
agreement do not establish a usable real-time VR replacement.

The authoritative project brief is [PHASE0_OPENNR_SKYRIMVR_CODEX_GUIDE.md](../PHASE0_OPENNR_SKYRIMVR_CODEX_GUIDE.md). The reconstruction findings are in [docs/PHASE0_RECON.md](PHASE0_RECON.md), and the exact teacher baseline is recorded in [docs/BASELINE_OPEN_SHADERS_0.4.5.md](BASELINE_OPEN_SHADERS_0.4.5.md) and [BASELINE_OPEN_SHADERS_0.4.5.json](../BASELINE_OPEN_SHADERS_0.4.5.json).

The dated research watches [DLSS5_RECONSTRUCTION_UPDATE_20260904.md](DLSS5_RECONSTRUCTION_UPDATE_20260904.md) and [DLSS5_RECONSTRUCTION_UPDATE_20260905.md](DLSS5_RECONSTRUCTION_UPDATE_20260905.md) record public numerical reconstruction, AMD execution, and source-available teacher-harness developments. They inform future architecture and auxiliary-data tracks, but do not change the Phase 0 acceptance gates or the current compact-student baseline.

The [September 8 MLX-DLSS performance assessment](MLX_DLSS_PERFORMANCE_RELEVANCE_20260908.md) records the verified September 7 upstream commit, its limited immediate impact on cached-target training, and the native-teacher parity checks required before offline dataset use. It also links the newer joint one-pass/two-pass training records; earlier capture-pilot snapshots are historical.

The [September 8 temporal-SR and teacher-reliability assessment](MLX_DLSS_TEMPORAL_SR_TEACHER_RELIABILITY_20260908.md) records the newly recovered recurrent DLSS-SR architecture and the attached real-detail-versus-invention result. The SR path is retained as an architecture reference only; native Feature 18 remains authoritative, and any reference-aware supervision is deferred behind an independently aligned Skyrim reference micro-cohort.

The current native capture build is validated and ready for an isolated temporal pass; see [CAPTURE_BUILD_VALIDATION_20260905.md](CAPTURE_BUILD_VALIDATION_20260905.md). The 0.5.5 renderer-conditioning probe is additionally installed in the active MGO profile only for the bounded capture pilot; its rollback DLL and pre-edit settings are retained on G:, and this remains a capture/configuration state until live Feature 18 evidence is collected.

## Baseline boundary

OpenNR-VR references the existing teacher checkout instead of copying it into this repository:

`D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d`

The checkout already contained user-owned changes; they were preserved, and the new capture feature is implemented there as a worktree-local integration rather than copied into this repository. The baseline package contains NVIDIA-signed runtime components, including `nvngx_dlssnr.dll`; those binaries are local/private inputs and are not vendored, redistributed, or committed here. The source checkout is also dirty, so the exact commit plus dirty-state flag are part of the baseline identity.

The optional PixRestore reference implementation is tracked as the
`_external/PixRestore` submodule and remains owned by its upstream authors. Clone
with `--recurse-submodules` (or run `git submodule update --init --recursive`) when
you need the offline model test code; review the upstream repository's license and
terms separately from OpenNR-VR.

## Capture implementation

The implementation lives in the teacher checkout at
`D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d`:

- `src/Features/OpenNRCapture.h/.cpp` provides `[` start/stop, `]` single, and `\` burst,
  sampled capture rate, 1–4 configurable GPU crops per stage/eye, periodic full per-eye
  validation frames or an explicit full-resolution master-sequence mode, bounded
  queue/backpressure behavior, staging readback, RGB PNG/raw output, raw depth/motion
  tensors, and JSONL.
- `src/Features/Upscaling/NeuralRendering/Renderer.cpp` taps isolated per-eye input
  textures before Feature 18 and teacher/resolved textures after it, including the
  reduced-resolution raw teacher path.
- `src/Features/Upscaling/FoveatedRender` supports an aspect-corrected oval
  feather/dither composite mask with a rectangular fallback, plus a `Nasal
  Convergence 60%` stereo preset. The Feature 18 input remains the rectangular
  bounding subrect; the oval changes only the visible composite seam.
- `features/OpenNRCapture/Shaders/Features/OpenNRCapture.ini` installs the feature as a
  beta, opt-in utility without changing the normal screenshot feature.

The portable dataset contract and offline checker are documented in
[docs/OPENNR_CAPTURE_FORMAT.md](OPENNR_CAPTURE_FORMAT.md) and implemented by
[tools/validate_capture.py](../tools/validate_capture.py).
The example settings can be checked before launch with
[tools/validate_capture_config.py](../tools/validate_capture_config.py).
After capture, [tools/preview_capture.py](../tools/preview_capture.py) creates a
dependency-free HTML contact sheet for visual inspection.

For the bounded renderer-conditioning pilot, use
[config/opennr_capture_renderer_conditioning_pilot.example.json](./config/opennr_capture_renderer_conditioning_pilot.example.json)
with the matching probe build. It requests raw deferred G-buffer stages (albedo,
normal/roughness, engine masks, specular, and reflectance) while keeping the pilot to
eight frames and one 512×512 crop; illumination-only, semantic-ID, and exact teacher-
history tensors remain explicitly unavailable until the renderer exposes a verified
contract for them.

## Test handoff

The 0.5.2 variants are produced with `BuildRelease.bat Dev-Fast` plus the explicit
CMake flags below, then normalized by
`D:\.CODEX_Projects\DLSS_5_SKYRIM\scripts\Package-OpenShadersDLSSNRPair.ps1`.
The build directory is intentionally left in the non-local
(`BUILD_OPENNR_CAPTURE=OFF`) state after packaging; the active local MO2 mod is
refreshed separately from the OpenNR-enabled source.
The naming contract is exact and applies to the MO2 mod name and the archive
base name:

- `Open Shaders DLSSNR VR x.x.x` = public-label internal LAN build.
- `Open Shaders DLSSNR VR x.x.x OpenNR` = local build with OpenNR.

Use this exact contract for every future version. Do not append `MGO Dev`,
`private-dev`, dates, fix descriptions, or any other suffix. “Public” is only
the label for the non-local variant; these are authorized internal-LAN test
packages, not public releases.

There are two same-version 0.5.2 outputs:

- `Open Shaders DLSSNR VR 0.5.2 OpenNR.7z` is the local-only
  build. It was compiled with `BUILD_OPENNR_CAPTURE=ON`, includes the complete
  DLL/runtime set, and contains `Shaders\Features\OpenNRCapture.ini`.
- `Open Shaders DLSSNR VR 0.5.2.7z` is the public-label internal LAN build.
  It was compiled with `BUILD_OPENNR_CAPTURE=OFF`, includes the complete
  DLL/runtime set for one-click MO2 installation, and omits the OpenNR
  implementation and registration. It is not a public redistribution package.

The two archives are kept separate so OpenNR capture remains local to this computer.
For a reproducible build switch, configure with both `BUILD_OPENNR_CAPTURE` and
`AIO_INCLUDE_OPENNR_CAPTURE` set to `ON` for the local variant, or both set to `OFF`
for the public-label LAN variant. Run the pair packager after both AIO trees have been built:

    powershell -File D:\.CODEX_Projects\DLSS_5_SKYRIM\scripts\Package-OpenShadersDLSSNRPair.ps1 -Version 0.5.2 -Force

The complete MO2/FOMOD and runtime-inclusion contract is maintained in
[DLSS_5_SKYRIM/docs/DISTRIBUTION.md](../DLSS_5_SKYRIM/docs/DISTRIBUTION.md).
That document is the packaging authority for future versions; the upstream
timestamped `CommunityShaders_AIO-*.7z` files are build inputs, not the
canonical installable package names.

On a fresh install, the first-run foveated crop is now
`Nasal Convergence 60%` with the oval edge mask; `Center 75%`, `Nasal Convergence 50%`,
and `Full Eye` remain available. Use the isolated MO2/test profile for live validation;
Skyrim has not been launched by this packaging pass.

The local capture build requests a Feature 18 temporal-history reset whenever a new
sequence starts. Therefore the direct burst hotkey from an idle capture state is the
preferred one-key strict-temporal workflow; the first record should report
`history_reset: [true, true]` without opening or closing the settings menu.

After enabling OpenNR Capture, use `]` for one sample, `[` to start/stop a sequence, or
`\` for the configured burst. Validate the resulting directory with:

```powershell
python D:\.CODEX_Projects\OpenNR-VR\tools\validate_capture_config.py D:\.CODEX_Projects\OpenNR-VR\config\opennr_capture.example.json
python D:\.CODEX_Projects\OpenNR-VR\tools\validate_capture.py D:\OpenNR_Captures --json
python D:\.CODEX_Projects\OpenNR-VR\tools\preview_capture.py D:\OpenNR_Captures --limit 20
```

For the next data-collection pass, use
`config/opennr_capture_master_sequence.example.json`. It keeps the four training crops
but also records complete stereo color and native Feature 18 guide resources for every
sampled frame. The example is deliberately disabled and capped at 120 samples because
full-resolution stereo raw data grows quickly; copy it into the isolated test profile,
review the output path, then enable capture in-game.

## Phase boundary

The feature remains passive when disabled, preserves the known-good rendering path, uses
asynchronous GPU readback, and writes explicit frame/eye/resource metadata. No training,
model replacement, runtime bridge, or renderer redesign belongs in Phase 0.
