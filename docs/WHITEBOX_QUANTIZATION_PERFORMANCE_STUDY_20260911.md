# Recovered white-box DLSS5 NR: performance and quantization study

Date: 2026-09-11  
Status: offline research only; `promotion=false`  
Live runtime changed: no

## Decision summary

The recovered model is numerically close enough for the stated experiment: the direct activation-E4M3 branch stayed around `0.00134` mean absolute error from the unquantized recovered reference on the six-eye probe. That is within the currently accepted `0.0013–0.0015` drift band.

It is not currently a usable VR runtime. The best measured eager PyTorch branch took about `2,465 ms` per eye on the RTX 5070 Ti, or about `4,929 ms` for two eyes executed sequentially. A separate warmed single-eye benchmark measured `2,378 ms` median. These are model-only timings; preprocessing and postprocessing would add more time.

The important conclusion is that the seconds-versus-milliseconds gap is not being caused by the accepted numerical drift. It is primarily an execution/backend problem, combined with the cost of the recovered full-frame graph:

- The source executes a 71-block network over the full `2496x2688` eye extent using eager Python/PyTorch operations.
- Many tensor transformations are separate kernels: copies, conversions, reshapes, window partition/reversal, concatenations, residual arithmetic, and matrix multiplies.
- The current `fast` path still uses a slow bit-level E4M3 emulation when its values are FP16. Direct CUDA FP8 casts remove part of that overhead, but do not fuse the rest of the graph.
- The weight-only FP8 and INT8 experiments dequantize back to ordinary FP16 before the matmuls. They demonstrate storage/numerical feasibility, not a production quantized-kernel speed-up.
- `torch.compile` did not reach a steady-state full-frame result during the smoke run; compilation continued for more than ten minutes and spawned a worker using several gigabytes of host memory. The current graph is not a practical compile-first path.

This means the recovered weights should be treated as a useful reference for a kernel/backend port, not as a drop-in model that becomes native-speed merely by casting its weights.

## Measured branches

The probe used three held-out Skyrim sequences, one frame from each sequence, both eyes (`6` eye rows total), with the same complete-frame proxy cache and fixed controls. The comparison reference is the current recovered graph in reference precision. Timing is model-only and sequential; it is not a live Skyrim or headset measurement.

| Branch | Mean model time / eye | Sequential stereo estimate | Mean drift vs recovered reference | Peak CUDA allocation | Interpretation |
|---|---:|---:|---:|---:|---|
| Recovered reference | 3,469.80 ms | 6,939.59 ms | reference | 5.35 GiB | Numerical reference, not optimized |
| Existing fast FP16 | 5,615.28 ms | 11,230.56 ms | 0.001342 | 3.48 GiB | Lower memory, but slower because the FP16 path still performs expensive emulated E4M3 boundaries |
| Activation FP8 + fast graph | 2,464.74 ms | 4,929.47 ms | 0.001342 | 3.47 GiB | Best current numerical/runtime control; still seconds per eye |
| Weight FP8, dequantized to FP16 | 5,494.47 ms | 10,988.94 ms | 0.005133 | 3.48 GiB | About 45.88% estimated dense weight-storage reduction; no true quantized compute |
| Weight INT8, dequantized to FP16 | 5,528.14 ms | 11,056.27 ms | 0.005467 | 3.48 GiB | About 45.66% estimated dense weight-storage reduction; no true quantized compute |

The weight-only branches are therefore not contradictory: they save checkpoint bytes, but the current evaluator converts those bytes back into FP32/FP16 tensors before computation. The GPU still runs ordinary FP16 matmul and all of the same surrounding graph. A quantized file is not the same thing as a quantized execution kernel.

The complete probe result is preserved at:

`D:\.CODEX_Projects\OpenNR-VR\out\whitebox_quant_probe_test6_20260911\whitebox_quantization_study.json`

## Chunk-size control

The recovered source defaults to `MLXDLSS_TORCH_CHUNK_TOKENS=262144`. Increasing it reduces the number of Python-side chunks and some intermediate concatenations, but it did not materially change the warmed full-eye execution time:

| Activation-FP8 benchmark | Chunk size | Median / eye | P95 / eye | Peak CUDA allocation |
|---|---:|---:|---:|---:|
| Default | 262,144 | 2,378.36 ms | 2,423.43 ms | 3.42 GiB |
| Larger | 524,288 | 2,389.62 ms | 2,435.31 ms | 3.42 GiB |
| Larger | 1,048,576 | 2,361.43 ms | 2,365.45 ms | 4.15 GiB |

The small variation is normal run-to-run noise. The 1M setting costs more memory and does not produce the orders-of-magnitude improvement required for VR. Chunking is a safety mechanism for intermediate memory, not the missing native implementation.

## What the profiler says

The one-eye reference operator profile shows that the execution is dominated by memory traffic and many small/medium operations, not one large efficient tensor-core workload. The profile includes instrumentation overhead, so its total wall time must not be used as the runtime number; the counts and relative CUDA costs are the useful evidence.

Top CUDA-side entries in `operator_table_cuda_total.txt`:

| Operation family | Calls | CUDA time attributed |
|---|---:|---:|
| `aten::copy_` | 78,797 | 962.9 ms |
| `aten::to` / conversion path | 81,278 | 887.0 ms total attribution |
| Matrix multiply (`aten::mm`) | 6,956 | 338.7 ms |
| `aten::add` | 20,675 | 279.4 ms |
| `aten::mul` | 15,795 | 261.7 ms |
| `aten::clamp` | 3,452 | 171.8 ms |
| `aten::cat` | 2,720 | 130.3 ms |

The copy and conversion rows are not independent costs that can simply be added without accounting for profiler nesting, but they clearly show the shape of the problem: the eager graph launches and moves data tens of thousands of times. The activation-FP8 profile lowers some of the conversion burden and lowers matrix-multiply attribution, yet still leaves the same un-fused window/attention, concatenation, and elementwise structure. That is why it improves the branch from roughly `5.6 s` to roughly `2.5 s` without approaching milliseconds.

Profiles:

- `D:\.CODEX_Projects\OpenNR-VR\out\whitebox_runtime_profile_reference2_20260911\operator_table_cuda_total.txt`
- `D:\.CODEX_Projects\OpenNR-VR\out\whitebox_runtime_profile_activation_fp8_20260911\operator_table_cuda_total.txt`
- `D:\.CODEX_Projects\OpenNR-VR\out\whitebox_runtime_profile_activation_fp8_chunk524k_20260911\operator_table_cuda_total.txt`

## Why native DLSS NR is different

The native NVIDIA path is not “the same Python model with the same weights.” It is a shipping GPU implementation with compiled/fused kernels, fixed tensor layouts, specialized attention and matrix-multiply paths, persistent workspace management, and no Python interpreter between graph stages. It can combine operations that are separate in this reconstruction—for example, conversion plus projection, window movement plus attention preparation, and residual arithmetic plus publication.

The recovered source is valuable because it exposes the logical operations and recovered tensors. It does not automatically provide the kernel schedule, memory layout, fusion boundaries, CUDA graph, TensorRT engine, or custom RTX implementation that makes the native path fast. White-box weights answer “what values should the operations use?” They do not answer “how should thousands of GPU operations be scheduled and fused to meet a VR frame budget?”

There is also a graph-size question. This is a full-eye graph at `2496x2688`, with full-resolution work at the input and output ends, many multi-scale blocks, window-attention blocks, split-window blocks, and global blocks `31–38`. Even a perfect backend port must first establish that the recovered topology has a feasible operation count at this extent. If the graph is intrinsically too large, weight quantization can only reduce arithmetic/memory cost; it cannot remove the 71-block schedule.

## What this changes about the plan

No additional Skyrim captures are required to answer the current speed question. More captures could improve a student or validate visual behavior, but they will not make the present eager white-box graph faster.

The next worthwhile engineering experiment is a small, isolated backend prototype using one exact full-eye input and the same output contract:

1. Keep the recovered reference output as the numerical oracle.
2. Replace direct Python tensor composition with a static execution plan and fixed layouts.
3. Implement or export the high-cost regions in fused CUDA/TensorRT/custom kernels, starting with E4M3 conversion boundaries, projection-plus-conversion paths, window partition/attention/reversal, and residual/concatenation chains.
4. Use real FP8/INT8 GEMM kernels where supported, with explicit scales and accumulation rules. Do not dequantize before the matmul.
5. Measure one eye, then two eyes, using CUDA events and the same complete-frame contract. Validate drift before measuring any live integration.
6. Only after a genuine compiled backend shows a large speed reduction should we spend time on CUDA graphs, stereo overlap, VR frame-budget tests, or a runtime wrapper.

This is a backend implementation project, not another distillation-data project. The current result still has research value as a recovered visual reference and a target for a faster implementation, but it is not eligible for live-runtime promotion.

## Reproducibility and code

The offline evaluator and warmed benchmark are isolated here:

- `D:\.CODEX_Projects\OpenNR-VR\tools\evaluate_whitebox_quantization.py`
- `D:\.CODEX_Projects\OpenNR-VR\tools\profile_whitebox_runtime.py`
- `D:\.CODEX_Projects\OpenNR-VR\tools\benchmark_whitebox_runtime.py`

The quantization study is explicitly marked `runtime_changed=false`, `training_started=false`, and `promotion=false`. No live Skyrim profile, DLL, native bridge, or OpenNR runtime assets were modified.
