# FastStudent-v1 runtime candidate

FastStudent-v1 is an isolated runtime candidate. It does not replace the
joint-1200 semantic checkpoint, change the active MGO profile, change the
capture contract, or modify any existing training output.

## Architecture

- RGB and the five native Feature-18 guide channels enter a learned 1/4 grid.
- A compact U-Net encoder/decoder handles local reconstruction.
- The recurrent state is a ConvGRU-style hidden tensor at 1/8 of the RGB/model
  input (`[1,64,ceil(H/8),ceil(W/8)]` with the default config), matching the
  existing Skyrim TensorRT bridge contract.
- The whole-eye eight-channel context tensor supplies a pooled bottleneck
  affine condition.
- A three-channel low-grid residual is upsampled and passed through one shallow
  native-resolution 6-to-3 convolution. The residual heads are zero-initialized,
  so a fresh checkpoint is exactly RGB at step zero.
- The five guide channels remain depth, motion-vector X/Y, depth-valid, and
  motion-valid. They are resized to the learned grids; they are not replaced by
  inferred optical flow.

The implementation is in [fast_student_v1.py](../tools/fast_student_v1.py).

## Validation already run

Using the pinned local ML environment (`E:\OpenNR-VR-Poc-Venv\Scripts\python.exe`):

- `tools/test_fast_student_v1.py` passed exact identity, odd-size state-shape,
  recurrent-step, finite-gradient, and finite-output checks.
- ONNX export passed at an odd test shape, and ONNX Runtime matched PyTorch with
  a maximum absolute error of `4.77e-7`.
- TensorRT 10.13.3 successfully built an FP16-I/O engine for the current test
  shape (`887x824` RGB, `672x624` guides, `96x96` context). The isolated build
  took about 129 seconds and produced a 3.32 MB engine. This is build health,
  not Skyrim live acceptance.

An untrained identity-initialized model was also timed in CUDA FP16 inference
mode on the RTX 5070 Ti:

| Shape | Reset median / p95 | Steady median / p95 | Peak allocation |
| --- | ---: | ---: | ---: |
| 512x512 RGB, 128x128 guides | 2.77 / 3.06 ms | 2.73 / 3.06 ms | 0.014 GiB |
| 887x824 RGB, 672x624 guides | 4.09 / 4.60 ms | 4.10 / 4.74 ms | 0.046 GiB |

These are PyTorch CUDA timings, not TensorRT and not in-game timings. They are
useful as an architectural ceiling check; TensorRT engine timing and Skyrim
integration still need to be measured after a trained checkpoint exists.

## Commands

Run the contract test:

```powershell
& 'E:\OpenNR-VR-Poc-Venv\Scripts\python.exe' tools\test_fast_student_v1.py
```

Benchmark the architecture before training:

```powershell
& 'E:\OpenNR-VR-Poc-Venv\Scripts\python.exe' tools\benchmark_fast_student.py `
  --height 512 --width 512 --guide-height 128 --guide-width 128

& 'E:\OpenNR-VR-Poc-Venv\Scripts\python.exe' tools\benchmark_fast_student.py `
  --height 887 --width 824 --guide-height 672 --guide-width 624
```

Train into a new output directory using a strict reset-qualified temporal
cache. Replace both placeholders explicitly; do not point `--output` at an
existing joint-model run:

```powershell
& 'E:\OpenNR-VR-Poc-Venv\Scripts\python.exe' tools\train_fast_student.py `
  --cache '<STRICT_TEMPORAL_CACHE>' `
  --output '<ISOLATED_FAST_STUDENT_OUTPUT>' `
  --steps 4000 --window 8 --burn-in 1 --batch 2
```

Export a trained checkpoint to fixed-shape ONNX and FP16 TensorRT for the
current 33% Skyrim test surface:

```powershell
& 'E:\OpenNR-VR-Poc-Venv\Scripts\python.exe' tools\export_fast_student_runtime.py `
  --checkpoint '<ISOLATED_FAST_STUDENT_OUTPUT>\best_mae.pt' `
  --output '<ISOLATED_FAST_STUDENT_OUTPUT>\trt_33pct' `
  --height 887 --width 824 `
  --guide-height 672 --guide-width 624 `
  --context-height 96 --context-width 96 `
  --fp16-io --builder-optimization-level 3
```

The exporter writes `onnx_manifest.json`, `engine_manifest.json`, and an engine
layer report. It does not copy or install anything into MGO. Packaging this
engine into a separate Skyrim test profile is a later, explicitly isolated
step after trained-output and TensorRT numerical checks.

FP8 and NVFP4 are deliberately not enabled in this first candidate. FP16 is
the reference path; lower precision should only be added after the trained
FP16 engine passes visual, temporal, and numerical equivalence checks.
