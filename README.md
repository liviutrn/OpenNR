# OpenNR-VR

OpenNR-VR is a research project for learning an open-weight VR neural-rendering model from synchronized Skyrim VR frames. The initial teacher is the working Open Shaders DLSSNR integration, using the private Open Shaders 0.4.5 MGO developer package as the pinned baseline.

## Current status

Phase 0 color capture plus the first Phase 1 guide-capture extension are prepared for a
build/test pass. The teacher checkout now contains an opt-in `OpenNRCaptureFeature`
wired around the actual Feature 18 renderer boundary, including raw per-eye depth and
motion-vector resources with scale/reset metadata. A live Skyrim VR/headset run has not
been performed yet, so runtime delivery, tensor interpretation, visual quality, and
sustained queue behavior remain acceptance gates.

The authoritative project brief is [PHASE0_OPENNR_SKYRIMVR_CODEX_GUIDE.md](./PHASE0_OPENNR_SKYRIMVR_CODEX_GUIDE.md). The reconstruction findings are in [docs/PHASE0_RECON.md](./docs/PHASE0_RECON.md), and the exact teacher baseline is recorded in [docs/BASELINE_OPEN_SHADERS_0.4.5.md](./docs/BASELINE_OPEN_SHADERS_0.4.5.md) and [BASELINE_OPEN_SHADERS_0.4.5.json](./BASELINE_OPEN_SHADERS_0.4.5.json).

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

- `src/Features/OpenNRCapture.h/.cpp` provides F9 start/stop, F10 single, F11 burst,
  sampled capture rate, 1–4 configurable GPU crops per stage/eye, periodic full per-eye
  validation frames, bounded queue/drop behavior, staging readback, RGB PNG/raw output,
  raw depth/motion tensors, and JSONL.
- `src/Features/Upscaling/NeuralRendering/Renderer.cpp` taps isolated per-eye input
  textures before Feature 18 and teacher/resolved textures after it, including the
  reduced-resolution raw teacher path.
- `features/OpenNRCapture/Shaders/Features/OpenNRCapture.ini` installs the feature as a
  beta, opt-in utility without changing the normal screenshot feature.

The portable dataset contract and offline checker are documented in
[docs/OPENNR_CAPTURE_FORMAT.md](./docs/OPENNR_CAPTURE_FORMAT.md) and implemented by
[tools/validate_capture.py](./tools/validate_capture.py).
The example settings can be checked before launch with
[tools/validate_capture_config.py](./tools/validate_capture_config.py).
After capture, [tools/preview_capture.py](./tools/preview_capture.py) creates a
dependency-free HTML contact sheet for visual inspection.

## Test handoff

The final local build was produced with `BuildRelease.bat Dev-Fast`; the DLL is in
`D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d\build\Dev-Fast\CommunityShaders.dll`.
`Package-AIO-Manual` also completed and staged the feature INI at
`build\Dev-Fast\aio\Shaders\Features\OpenNRCapture.ini`. Use that AIO output in an
isolated MO2/test profile; it has not been copied into the active game installation.

After enabling OpenNR Capture, use F10 for one sample, F9 to start/stop a sequence, or
F11 for the configured burst. Validate the resulting directory with:

```powershell
python D:\.CODEX_Projects\OpenNR-VR\tools\validate_capture_config.py D:\.CODEX_Projects\OpenNR-VR\config\opennr_capture.example.json
python D:\.CODEX_Projects\OpenNR-VR\tools\validate_capture.py D:\OpenNR_Captures --json
python D:\.CODEX_Projects\OpenNR-VR\tools\preview_capture.py D:\OpenNR_Captures --limit 20
```

## Phase boundary

The feature remains passive when disabled, preserves the known-good rendering path, uses
asynchronous GPU readback, and writes explicit frame/eye/resource metadata. No training,
model replacement, runtime bridge, or renderer redesign belongs in Phase 0.
