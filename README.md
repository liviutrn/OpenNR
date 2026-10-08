# OpenNR 2.20.1-v06-r7 — one adaptive controller

Windows build, tests and package audit **passed** on October 8, 2026.

[Download r7](https://github.com/liviutrn/OpenNR/actions/runs/37738693746/artifacts/11533527314) · [Build and test results](https://github.com/liviutrn/OpenNR/actions/runs/37738693746)

In-game headset quality and hardware GPU timing remain unmeasured.

## Changes from r6

- Stereo atlas is permanent: one stereo NR pass, Natural visual style and Matched Residual resolve. Removed their selection menus and the old controller.
- Adaptive Performance uses six stages. Crop sizes are relative to your selected crop, per axis. Choose a 20, 15 or 10 percentage-point crop drop.

| Stage | Crop with 20-point drop | Crop with 15-point drop | Crop with 10-point drop | NR resolution per axis |
|---|---:|---:|---:|---:|
| 1 | 100% | 100% | 100% | 100% |
| 2 | 80% | 85% | 90% | 100% |
| 3 | 60% | 70% | 80% | 100% |
| 4 | 60% | 70% | 80% | 85% |
| 5 | 60% | 70% | 80% | 70% |
| 6 | 100% | 100% | 100% | NR off |

- **Controller mode: Auto / Force stage 1–6** holds a selected stage for FPS comparisons. Forced stages ignore automatic thresholds and retain the normal crop/history handoffs. Close the menu after choosing a stage so the crop transition can finish, then wait for the **Settling** message to disappear before measuring. Returning to Auto keeps the current stage and clears decision holds.
- **Disable NR above** only acts in stage 5; **Re-enable NR below** only acts in stage 6. Earlier stages move one step at a time. Thresholds must be ordered. GPU budget, recovery headroom, smoothing, holds, cooldown and NR transition smoothing remain configurable.
- Stage 6 restores the selected crop size with NR bypassed. Resuming waits for the requested crop geometry to commit, clears stale NR history once, then fades its residual in using the existing output pass. Invalid geometry and menu holds prevent premature restoration.
- Changing crop drop while running retains the stereo handoff instead of committing a newly clamped crop immediately.
- Removed outside seam/tone correction completely, including its six shaders and GPU dispatches. Near-black protection inside NR remains, with its existing settings and raw-history behavior.
- Removed built-in Settings Benchmark, its menu, commands, packaged definitions and dedicated code/tests. Manual forced stages provide FPS comparison.
- Removed native tuning presets; retained Intensity, Local Tone, Local Structure, Skin Structure, Automatic Mask and UI Correction.
- Removed manual NR coverage/resolution, sequential NR, temporal residual reuse and optional result stabilization controls. The underlying gaze alignment and adaptive residual transition bridge remain.
- Removed result darkening multiplier, hue shift, shadows, midtones and halo suppression. Remaining output-shaping controls, including change limits, stay available.
- Eye tracking keeps the original smoothing slider, pixel quantization, freeze comparison and diagnostics. The native gaze provider is automatic when available; zero smoothing adds no filtering.
- VR DLSS mode is Default; stretch is Point. Periphery smoothing, crop presets/editor and region visualization remain. Inner edge uses Dither, width 128, falloff 0.5 and noise 1.0; rectangle/oval remains selectable.
- Shared SR controls are on the Upscaling page. Retired saved values cannot re-enable removed rendering modes; remaining settings are retained.

## Verification

The successful Windows build used commit `3a005b981acb178e624c782c571c422f6daeeddd`. The actual ladder policy and crop actuator passed 198 forced-stage/live-step paths, endpoint gates, stale-frame, hold and geometry-loss checks. Software D3D11 executed 128 actual near-black/resume-blend HLSL cases, including shaped/unshaped output, raw history, alpha and dispatch bounds. The 16 protected gaze/motion/grid files match r6; all six CPU/HLSL buffer-layout checks passed.

The archive audit verified CRC, the x64 plugin and runtime controls, and shader/source identity. r7 has 633 archive entries versus r6's 640: seven intended removals, no additions, and only the plugin and ResultShaping shader changed. Every other r6 payload is identical. The NR carrier remains excluded. [Package audit report](https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r7/docs/versions/2.20.1-v06/r7/package-audit.json).

These checks cannot establish headset visual quality or hardware GPU cost. This revision adds no NR evaluation or outside correction dispatch; the resume fade uses the existing output shader.
