# Low-bit runtime investigation for v7 — 2026-09-06

The v7 candidate remains the FP32/FP16-quality reference. Low-bit artifacts are
kept outside the active OpenNR installation until both numerical parity and live
runtime gates pass.

## FP8

The grouped-guide calibration path was repaired in `tools/quantize_fp8.py`. The
tool now reads the documented per-resolution guide groups and calibrates only rows
matching the fixed ONNX input shape. This matters because the merged cache contains
both 2496x2688 full-frame rows and 512x512 crop rows, while a TensorRT ONNX export
is fixed-shape.

For v7, 32 training-only full-resolution rows produced an explicit FP8 Q/DQ graph:

- Full Conv+MatMul FP8: built an engine, but failed parity with mean errors
  `0.003837` (left) and `0.003595` (right); measured sequential stereo time was
  about `29.75 ms`.
- MatMul-only FP8: calibration is supported as the conservative control, but the
  engine build was left isolated and stopped when the live game capture started.

Neither FP8 artifact is installed or promoted. The exact FP16 student export and
the v5 FP16 runtime remain the fallback line.

## FP6 and NVFP4

The installed TensorRT Python API is 10.13.3.9. Its exposed data types and builder
flags include FP4 and FP8, but no FP6. There is therefore no local FP6 deployment
path to validate for this graph without a separate custom kernel/backend.

TensorRT exposes FP4, but NVFP4 is a structured quantization scheme rather than a
single precision switch: it requires per-block scales (block size 16 for NVFP4) and
dynamic activation quantization. The current Model Optimizer environment exposes
FP8, INT8, and INT4 ONNX quantizers but no NVFP4 quantizer. Our student is also a
convolution-heavy graph with concatenation, elementwise style paths, and layer
normalization; the rejected FP8 graph already shows type/tactic failures around
those boundaries. A useful NVFP4 attempt would therefore require an explicit
strongly typed graph/Q-DQ or a model-aware QAT path, followed by image-error and
stereo parity checks. It is not safe to substitute for the current FP16 candidate.

The next engineering priority is the fresh strict temporal capture. Once the first
records prove `history_reset: [true, true]` with no drops or backpressure, temporal
fine-tuning can be evaluated before spending more time on low-bit graph surgery.
