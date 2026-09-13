# Public NR-B580 fast-path CUDA probe — 2026-09-12

## Executive result

The new public NR-B580 material is directly relevant to OpenNR's white-box
speed problem. It provides a practical implementation blueprint for the
missing layer between recovered weights and a usable runtime: fuse the repeated
matrix/activation/layout operations, keep workspaces fixed, and replay the
fixed-shape graph instead of launching thousands of operations from Python.

Using the public project's fast-kernel snapshot and the exact local serialized
DLSS-NR resource recovered from our DLL, an isolated CUDA probe on the RTX 5070
Ti produced these results:

| Contract | Unfused public backend | Fused adapters, Python launches | Fused adapters + CUDA Graph replay | Fused drift vs unfused control |
| --- | ---: | ---: | ---: | ---: |
| 256x256 | 236.06 ms control | 43.95 ms | **7.65 ms** | 0.002938 MAE |
| 512x512 | 243.94 ms control | not run | **16.49 ms** | 0.003002 MAE |
| 864x480 | 328.66 ms control | not run | **23.98 ms steady** | 0.002662 MAE |
| 1920x1080 | 844.37 ms control | 116.18 ms | **110.43 ms** | 0.002182 MAE |

The controls are single-sample timing anchors from the same process, so they
should not be treated as a publication-quality variance study. The 864x480 run
had a 141.32 ms first replay while a newly compiled geometry settled; the two
steady samples were 23.98 and 23.96 ms. The 1080p run used two steady graph
replays at 111.34 and 109.52 ms.

The 256x256 graph replay was byte-identical to the same fused stack launched
normally from Python. This is important: CUDA Graph capture changed the launch
mechanism, not the model result. At 1080p, however, the graph only reduced the
fused-stack timing from `116.18 ms` to `110.43 ms` (about 5%). The very large
small-contract improvement therefore does not mean that graph replay alone can
make the full network fast; full-frame arithmetic, intermediate traffic, and
kernel geometry remain the main cost at 1080p.

## Follow-up: precision, front-end, and resolution levers

Three additional probe branches separate the remaining speed levers instead of
assuming that the word “FP8” or CUDA Graphs will solve them automatically.

First, replacing the six exact K8 projections with ordinary FP16 Tensor-Core
style Triton dots reduced the 1080p network from `116.18 ms` to `92.77 ms` in
ordinary launches. CUDA Graph replay then measured `87.14 ms`. The output stayed
finite, and drift versus the same unfused public control was `0.002252 MAE`
versus `0.002182 MAE` for the exact-K8 fused branch. This is a useful speed
trade for a research branch, but it is not native parity; it also does not
explain the remaining order-of-magnitude gap to the NVIDIA runtime.

Second, the public table-driven front kernel was ported to CUDA in the probe
copy. After one compile warm-up, it took `2.36 ms` at 1920x1080 with complete
synthetic Box-Muller lookup tables. The portable analytic front previously
took about `84–94 ms` because it performs large integer/transcendental tensor
operations. The table measurement proves that front generation can be cheap,
but the tables are synthetic because the public release does not ship the
authenticated native asset; it is therefore a timing result, not a front
output-parity result.

Third, a true FP8-dot experiment converted the dynamic half activations in the
Triton kernel and cached FP8 weights. It was negative: `97.45 ms` at 1080p
with `0.008494 MAE` drift, versus `92.77 ms` for the simpler FP16 K8 branch.
At 256x256 it measured `44.46 ms` and `0.007478 MAE`. This shows why NVIDIA's
FP8 result cannot be reproduced by changing tensor dtypes in isolation: its
benefit depends on fused unpacking, hardware-specific operand layouts, and
kernel scheduling.

The same question was then tested with PyTorch's cuBLASLt FP8 path instead of
the custom Triton FP8 dot. It was also negative in this workload: `99.62 ms`
at 1080p and `52.65 ms` at 256x256, versus approximately `87.14 ms` and
`43.79 ms` for the corresponding FP16-K8 branches. The cuBLASLt call requires
supported matrix dimensions and a column-major weight layout, but the probe
still had to convert each dynamic activation and perform the residual adds
outside the GEMM. That is precisely the overhead a vendor fused kernel hides.
This closes the dtype-only/stock-GEMM branch for the current executor.

The structural reduced-resolution experiment is more promising for an
OpenNR-owned fallback. It runs the recovered graph on a 512x512 aspect-
preserving canvas, composites the signed low-resolution residual onto the
1920x1080 source, and measures the whole serial sequence:

| Model canvas | Serial end-to-end | MAE vs full independent reference | PSNR vs full independent reference |
| ---: | ---: | ---: | ---: |
| 512x512 | **13.77 ms** | **0.015306** | **33.27 dB** |
| 256x256 | **7.40 ms** | 0.021019 | 30.24 dB |
| Raw 1920x1080 input | not applicable | 0.017920 | 31.07 dB |

The 512 result is a real speed/quality trade: it improves the chosen full-
resolution independent reference over raw input, while the 256 result is fast
enough to be interesting for a stereo budget but is worse than raw input on
this sample. Both are single-eye offline measurements and use the probe's
synthetic front tables when the dynamic mode is selected. They are not native
teacher comparisons, temporal tests, stereo tests, or VR acceptance.

As a separate sanity check, the same existing Skyrim frame's native teacher
image was resized with the same BOX filter into the 1920x1080 proxy contract.
This is not a native-resolution gate, but it prevents the independent
reference from being the only quality comparator:

| Candidate | MAE vs resized native teacher | PSNR vs resized native teacher |
| --- | ---: | ---: |
| Raw 1920x1080 input | 0.021881 | 29.64 dB |
| 512 residual wrapper | **0.020751** | **30.67 dB** |
| 256 residual wrapper | 0.024608 | 29.07 dB |

The result is consistent with the independent-reference comparison: 512 is a
quality-improving candidate, while 256 is currently a speed-only candidate
that loses quality on this frame. It is still only one frame and one eye;
faces, hair, foliage, interiors, stereo, motion, and temporal state remain to
be evaluated before any runtime decision.

## Follow-up: target-GPU launch tuning

The first fast-path timings used the snapshot's published launch choices. Those
choices were measured for other hardware, so the probe made the tile geometry
selectable in its external research copy and tested one variable family at a
time on the RTX 5070 Ti. The public source snapshot remains clean; these are
probe-only changes.

| Probe variant | 1080p CUDA Graph median | Drift vs same unfused control |
| --- | ---: | ---: |
| Published fast choices | 87.14 ms | 0.002252 MAE |
| C32 MLP BM16 | 81.08 ms | 0.002247 MAE |
| plus Swin BM64 | 76.90 ms | 0.002247 MAE |
| plus multi-head BM64 | 74.31 ms | 0.002247 MAE |
| plus branch pair warps8, projection BM32 | **69.19 ms** | **0.002247 MAE** |

The best five-sample run was `69.19 ms` median, `69.84 ms` p95, with finite
output and the same output drift as the less aggressively tuned branch. The
best launch choices were C32 BM16/warps4/stages1, Swin BM64/warps4/stages1,
multi-head BM64/warps4/stages1, batched branch pair warps8, and branch
projection BM32/BN64/warps4/stages1. Eight warps for the Swin or multi-head
window kernels was slower; the tested branch projection warp/stage variants
were neutral or worse. Changing branch pair BM32 to BM16 was also worse.

This is a useful result, but it is not the missing 3--8 ms native runtime. It
shows that the public schedule was not tuned for this GPU and that kernel
geometry matters, while the remaining roughly 69 ms still comes from the
aggregate arithmetic, intermediate traffic, and many distinct network stages.
CUDA Graphs remove much of the launch bookkeeping, so another dtype-only
change is unlikely to close that gap.

The follow-up dense-kernel specialization improved the same five-sample
1080p graph run further, from the `69.19 ms` launch-tuned branch to
`61.87 ms` median (`62.54 ms` p95). It uses a dedicated ordinary-FP16
Triton dense kernel with RTX-5070-Ti-specific BM64/BN64/BK32/warps8 tiles,
plus the tuned batched branch kernel. The drift remained `0.002247 MAE`,
output stayed finite, and the provider call counts were unchanged at the
logical level. A cuBLAS FP16 control was slower at about `63.83 ms`, and a
cuBLASLt FP8 control was slower still at about `99.62 ms`; neither library
call fuses the activation conversion, residual adds, and surrounding layout
work the way a vendor kernel does.

The public snapshot's alternate C32 lookup-table fusion was also tested. A
local LUT was generated with the same Triton cubic+FP8 kernel as the direct
path because the public authenticated table is not present. The full 1080p
LUT branch measured `72.54 ms` with the same `0.002247 MAE` drift. The lookup
read costs more than the inline cubic arithmetic on this GPU, so LUT-based C32
fusion is rejected for the speed branch. The direct C32 kernel remains the
control.

The older non-native-half attention choices were not a hidden win either.
Under the same tuned graph contract, replacing only the native-half window
math measured `65.50 ms`, replacing only normalization measured `65.01 ms`,
and replacing both measured `66.06 ms`; all retained the same measured drift.
The native-half QKV/window path is therefore still the best of the tested
public alternatives on this GPU.

The per-boundary event probe explains why there is no single pathological
kernel to delete. After warm-up, the pre stage's measured subcosts were about
`0.31 ms` front projection, `2.02 ms` C32 MLP, `2.91 ms` C32 attention,
`1.20 ms` output projection, and `0.85 ms` quantize/pool work. The post stage
was about `0.97 ms` expand/repeat, `1.15 ms` merge, `0.53 ms` pad, `2.05 ms`
C32 MLP, `2.93 ms` C32 attention, `1.20 ms` output projection, `0.57 ms`
K8 head, and `0.58 ms` RGB conversion. These are serialized diagnostic
segments, not a second end-to-end timing, but they point to cross-stage
fusion/workspace reuse rather than one bad arithmetic primitive.

Finally, a probe-only identity ablation tested the public report's structural
"skip blocks" idea:

| Ablation | 1080p CUDA Graph median | Drift vs full unfused control |
| --- | ---: | ---: |
| No skipped blocks | 61.87 ms | 0.002247 MAE |
| Skip half of ViT | 62.09 ms | 0.013030 MAE |
| Skip half of shape-preserving body blocks | 46.99 ms | 0.017720 MAE |
| Skip both sets | 44.63 ms | 0.020284 MAE |

The speed numbers show why block skipping is a real structural lever, but the
quality numbers reject naive skipping as a drop-in approximation. A trained
student could learn to compensate for removed blocks; this static ablation
cannot establish that it will.

The tuned reduced-resolution reruns measured the following numbers with five
replay samples after a compile warm-up:

| Candidate | Serial end-to-end | Network median | MAE vs full independent reference | MAE vs resized native teacher |
| --- | ---: | ---: | ---: | ---: |
| 512 residual | **11.63 ms** | 11.03 ms | 0.015306 | **0.020751** |
| 256 residual | **6.53 ms** | 5.78 ms | 0.021019 | 0.024608 |

The 256 network still showed one lazy-compilation outlier in the raw timing
list; its median is representative of the later steady samples, while the
reported p95 is not used as a quality claim. The residual-quality metrics
themselves are unchanged from the earlier single-frame comparison.

The best full-frame direct-kernel result is preserved at
`out/public_b580_cuda_fast_best_dense_batched_bm32bn64_1080p_20260912`, and
the LUT negative control is preserved at
`out/public_b580_cuda_fast_c32lut_best_1080p_20260912`. The attention and
structural ablations are preserved under their corresponding
`out/public_b580_cuda_fast_old_*` and
`out/public_b580_cuda_fast_skip_*` directories.

The reusable residual probe is
[`tools/benchmark_b580_residual_scale_probe.py`](../tools/benchmark_b580_residual_scale_probe.py).
Its outputs are preserved under
`out/public_b580_residual_scale_512_dynamic_graph_20260912` and
`out/public_b580_residual_scale_256_dynamic_graph_20260912`.

## What was verified locally

The resource reconstruction is now independently hash-verified:

- Local reconstructed resource: `out/dlssnr_resource_map_e16bcf15_20260912/weights.resource.bin`
- Size: `147,695,410` bytes
- Resource SHA-256: `836f445d06ecd2e59bb9f17b84b91c143396fd76ccda1c9dc7fe81d5edd548f4`
- The same length and hash were extracted directly from the local
  `nvngx_dlssnr.dll` resource section.
- It contains the same 153-record resource identity expected by the public
  B580 project.

The public snapshot was checked at local commit
`695ae22a32830c6d266c0636d9fd8fb3ffb46a3a` (2026-09-09). Its ordinary
`ResetNR` executor does not install the fast adapters automatically. The probe
therefore installed, in an external research copy only:

1. FP16 fused C32 MLP kernels.
2. Batched C64/C128/C256 branch MLP kernels.
3. Fused C32 projection and QKV/window packing.
4. Fused Swin window attention, including the snapshot's native-half-FMA
   variant.
5. Fused C512 split feed-forward and ViT projection kernels.
6. A fixed-shape CUDA Graph replay around the complete reset-frame body.

The CUDA copy widened XPU-only guards and converted an XPU chunk fence to a
CUDA fence outside capture. That synchronization is skipped only while CUDA
Graph capture is active because a graph already preserves in-stream ordering.
The public source tree itself remains clean and untouched.

The published fast branch expects a cubic FP8 lookup-table asset that the
public release deliberately does not include. For the batched-branch probe, an
in-memory table was generated with the local Triton cubic+FP8 kernel so that
the C32 LUT experiment and the direct C32 control share the same pointwise
arithmetic. It is a performance/portability control, not a claim that the
publisher's authenticated LUT file was recovered. The probe also contains one
CUDA portability rewrite of the public half-FMA helper after Triton rejected
its XPU shape-indexing form.

## Why this matters to OpenNR

This is the first local result that demonstrates the whole causal chain rather
than only a faster isolated C32 block:

```text
recovered weights
        |
        v
71-block portable executor       ~844 ms at 1080p
        |
        v
fused fixed-shape kernels         ~110 ms at 1080p
        |
        v
target-GPU dense specialization ~61.9 ms at 1080p
```

That supports the external reports that the multi-second PyTorch timing is not
the intended neural workload. It also explains why weight-only quantization
alone was never sufficient: changing the representation of a weight does not
remove the repeated intermediate tensors, layout conversions, kernel launches,
or synchronization boundaries.

It also puts the remaining problem in the right category. The published fast
snapshot was about `110 ms` and the best target-GPU tuned probe is about
`61.9 ms` for one eye in this independent CUDA path. The local native Feature 18
reference measured about `23.16 ms` for its full
stereo GPU pair at the tested Skyrim contract. Those are not identical scopes,
so this is not an apples-to-apples performance ratio; nevertheless, the
independent full-resolution path is plainly not within a VR frame budget yet.
At 256x256 the same style of backend can reach a single-digit replay time, so
the approach is technically viable at reduced contracts but not yet at the
full eye resolution required for promotion.

## First native CUDA executor probe

The WSL GPU environment is now able to compile CUDA 13.4 for the local
RTX 5070 Ti (`sm_120`). A small C++/CUDA probe was used to separate a
single-kernel implementation from the Python/Triton orchestration. It uses
the public C32 MLP shape (32 channels, 128 hidden channels) and deterministic
synthetic half weights. It is deliberately a runtime experiment, not a
quality or bit-exactness test against the recovered resource.

| Tokens | Contract analogue | cuBLAS + separate activation/residual | One fused WMMA CUDA kernel | Fused speedup |
| ---: | --- | ---: | ---: | ---: |
| 921,600 | 1280x720 | 1.588 ms graph | **0.805 ms graph** | **1.97x** |
| 2,211,840 | padded 1920x1080 front | 3.808 ms graph | **1.918 ms graph** | **1.99x** |

The fused kernel keeps the two WMMA GEMMs, cubic boundary, and residual write
inside one fixed shared-memory launch. CUDA Graph replay made essentially no
difference for this already-single-launch stage (`0.800` vs `0.805 ms` at
921,600 tokens and `1.912` vs `1.918 ms` at 2,211,840 tokens). This is a
useful positive result: the public fast path's remaining problem is not that
CUDA cannot execute the arithmetic quickly, but that the complete network still
has many different stage contracts that are not fused together. The probe's
synthetic values also mean it must not be read as evidence of recovered-model
parity.

The same fused kernel was then run with the decoded first C32 expansion,
contraction, and skip weights from the hash-verified local resource and a real
Skyrim-derived projected tensor. It still measured `1.916 ms` at 2,211,840
tokens, produced a finite output, and compared to a chunked FP32-accumulation
reference at `3.10e-5 MAE`, `1.03e-4 RMSE`, and `0.001953` maximum absolute
error. This validates the matrix orientation and the basic CUDA implementation
against real recovered data, but it is intentionally not a claim of exact
native FP8/WMMA parity.

## ViT attention and projection controls

The next probe used the same existing Skyrim RGB input and exported the first
recovered ViT block after the full encoder prefix. It reached a real
`640 x 1024` token boundary and exported the block's `1024 -> 4096` expansion,
`4096 -> 1024` contraction, final projection, and Q/K/V tensors. The weights
were read from the same hash-verified `147,695,410`-byte resource as the C32
probe; no new capture or training data was used.

A straightforward row-tiled CUDA WMMA projection was not a win. It reloads
input tiles for each output-column group, while cuBLAS already has a much more
mature large-matrix implementation:

| Real ViT boundary, 640 tokens | cuBLAS plus separate post-op | One custom WMMA launch | Custom / cuBLAS | Custom reference drift |
| --- | ---: | ---: | ---: | ---: |
| Expansion + cubic (`1024 -> 4096`) | 0.100 ms | 0.208 ms | 2.09x slower | 0.00884 MAE |
| Contraction + residual (`4096 -> 1024`) | 0.083 ms | 0.215 ms | 2.60x slower | 0.00144 MAE |
| Final projection + residual (`1024 -> 1024`) | 0.038 ms | 0.062 ms | 1.64x slower | 0.000876 MAE |

The custom outputs were finite. The drift column compares against the public
reconstructed reference exports, not against NVIDIA's opaque native output.
The expansion drift is especially high because this small probe uses an
approximate cubic and does not reproduce the full recovered FP8 boundary.
This closes the branch of replacing mature dense GEMMs with a naive WMMA
kernel; it does not close the larger question of fusing the whole ViT block.

Attention was more encouraging. On the same real Q/K/V tensors, the exact
reconstructed Triton attention measured `1.608 ms`. Replacing only its two
batched dot products with CUDA Tensor-Core `bmm`, while retaining the recovered
exponential transform, FP8 boundaries, and 64-key reduction, measured
`0.902 ms`—about `1.78x` faster—with `0.00431 MAE` versus the exact attention
export. Ordinary fused SDPA was much faster (`0.108 ms`, or `0.132 ms` after
the FP8 boundary), but its drift was `0.0670 MAE`; it is therefore a speed
control, not a drop-in recovered-look replacement.

The same BMM replacement was attempted inside the complete 1080p graph. It
did not produce a usable end-to-end result: the saved replay was approximately
`61.83 ms`, indistinguishable from the `61.87 ms` exact-stack control, and the
Python/Triton process ended with a native refcount failure after the CUDA-Graph
run. That branch is rejected until the graph integration is made stable and
its output difference is independently demonstrated. The microbenchmark still
matters: it shows that a fused attention implementation can remove roughly
half of one attention boundary, but the rest of the 71-block orchestration
currently hides that gain.

The combined real-block probe makes the opportunity and the limitation more
concrete. On the same `640 x 1024` Skyrim-derived boundary, the exact
reconstructed block took `13.191 ms`; a CUDA-native approximation using
cuBLAS-backed projections plus recovered BMM attention took `1.491 ms`, an
`8.85x` speedup on the RTX 5070 Ti:

| One real recovered ViT block | Exact reconstructed | CUDA-native approximation | Approx / exact | Approx output drift |
| --- | ---: | ---: | ---: | ---: |
| 640 tokens, `1024 -> 4096 -> 1024` | 13.191 ms | 1.491 ms | **8.85x faster** | 0.01623 MAE |

The approximate block remained finite, but its intermediate/output drift was
not small enough to call it a replacement: hidden `0.000510` MAE, MLP
`0.02429`, attended `0.00841`, and final output `0.01623` against the exact
reconstructed boundaries. The expansion path is still using an approximate
cubic/FP8 treatment, and the BMM attention is approximate as well. These
numbers are therefore a runtime-engineering signal, not evidence of parity
with NVIDIA or even exact parity with the recovered white-box graph. They do
show that the block's cost is not intrinsically multi-second once its Python
and fine-grained Triton orchestration is replaced by native dense/BMM calls.

The next safe implementation target is a separate multi-block CUDA executor
that keeps the exact exported boundary contract for comparison while swapping
in optimized kernels one block family at a time. A full-network claim should
wait until that executor reports both end-to-end two-eye timing and output
drift on the same frozen Skyrim captures.

The eight-block stage probe confirms that the single-block speed signal scales,
but also shows why it cannot yet be promoted as a recovered-look runtime. The
exact eight-block ViT stage measured `96.50 ms`; ordinary cuBLAS projections
plus the recovered BMM attention measured `10.90 ms` (`8.85x` faster), while
the K-partitioned/half-merge variant measured `12.87 ms` (`7.50x` faster).
Both approximate variants accumulated roughly `0.074 MAE` by block 8. Keeping
the exact recovered Triton attention while retaining approximate projections
raised the dense variant to `16.04 ms` and still ended at `0.074 MAE`; the
partitioned version was `16.88 ms` and `0.0724 MAE`. Therefore the accumulated
error is dominated by the dense/FP8 boundary approximation and repeated
nonlinear block state, not just the BMM attention replacement.

This is the important runtime conclusion: a native CUDA executor can remove a
large amount of Python/Triton overhead, but exact white-box parity requires
fused kernels that reproduce the recovered FP8 formats, accumulator order,
activation boundaries, and workspace layouts. Simply swapping in cuBLAS or
keeping exact attention does not provide both parity and NVIDIA-like speed.

The cached cuBLASLt FP8 control reinforces that point. Converting the already
FP8-bound activations and weights to FP8 and using `torch._scaled_mm` did not
improve this ViT stage: the dense eight-block variant measured `12.56 ms`
versus `10.90 ms` for the FP16 cuBLAS variant, and the K-partitioned variant
measured `22.43 ms` versus `12.87 ms`. The final drift remained effectively
the same (`0.0737` dense, `0.0732` partitioned). This is not a defect in the
FP8 weights; it shows that dtype conversion and a generic scaled GEMM do not
recreate the specialized fused Blackwell kernel schedule.

The CUDA-Graph replay control isolates the launch/scheduling contribution
without changing the approximate arithmetic. On the same `640 x 1024`
boundary, the dense cuBLAS/BMM stage measured `10.657 ms` when invoked through
the ordinary Python/Triton control, but `4.889 ms` when the complete eight-
block fast stage was captured once and replayed from a CUDA Graph. The graph
output was finite and had the same `0.07372 MAE` against the exact recovered
stage as the ordinary dense path.

| Eight-block ViT control | Median | Final drift vs exact stage |
| --- | ---: | ---: |
| Exact reconstructed reference | `96.915 ms` | `0` by definition |
| CUDA-native dense approximation, ordinary launches | `10.657 ms` | `0.07372 MAE` |
| CUDA-native dense approximation, graph replay | `4.889 ms` | `0.07372 MAE` |
| CUDA-native partitioned approximation, ordinary launches | `12.639 ms` | `0.07318 MAE` |

Graph replay therefore supplies an additional `2.18x` reduction over the
ordinary dense fast-stage control and is strong evidence that launch and
intermediate scheduling overhead—not only matrix arithmetic—is material in
the Python implementation. It does not fuse the whole 71-block network, fix
the accumulated approximation drift, or establish two-eye VR timing. The
next implementation target is consequently a persistent C++/CUDA executor
with preallocated workspaces and graph/static dispatch, followed by larger
stage-wide fusions; another generic FP8 conversion is not the next lever.

## Validated reduced-resolution control

The same best independent adapter configuration was also run at the public
fixed `864 x 480` contract, using the same existing 1080p Skyrim input as the
source for the offline resize. CUDA Graph replay measured `14.399 ms` median
and `15.268 ms` p95 for one eye. The output was finite and its image drift
against the same-path baseline was `0.002302 MAE` (`0.03320` maximum absolute
error). This is a useful speed/quality candidate, but it is not a final
1080p image: it still needs a separately validated residual/upscale composite
and two-eye/temporal measurements.

The result is nevertheless important for the runtime decision. Relative to
the 1080p independent graph path (`61.875 ms`), reducing the actual model
contract to `864 x 480` cuts the neural work to `14.399 ms`; the gain comes
from fewer tokens and smaller workspaces, not from changing the weight dtype.
It supports a reduced-resolution residual branch as a practical fallback, but
does not establish that the full recovered network can meet the native Skyrim
Feature-18 budget at full eye resolution.

## C++/CUDA fused C32 control

The existing lower-level CUDA harness was run inside WSL against the real
full-resolution Skyrim-derived C32 export: `2,211,840` tokens, decoded
recovered weights, and the same `32 -> 128 -> 32` C32 MLP contract used by the
earlier validation. The fused WMMA kernel measured `1.5352 ms` over five
iterations; capturing that single fused launch in a CUDA Graph measured
`1.53443 ms`. The output was finite and its SHA-256 was identical to the
previous validated C++ output (`E079C00A4980AD8115BA57C0E096E06DBB980F74EE00C4F0B7B75AEEF0B1248B`).

This is a useful executor proof, but it is deliberately narrower than a full
C32 block: it covers the MLP expansion, cubic boundary, contraction, and
residual write, not the attention, QKV packing, layout conversion, or complete
block schedule. The negligible graph gain is expected because the kernel is
already one physical launch. It tells us that a C++ port of one isolated MLP
will not close the full gap by itself; the next useful fusion unit is the
whole C32/decoder block plus its attention and layout boundaries.

The complete standard C32 block was then rerun at the retained full-eye
resolution using the existing raw frame and a newly reconstructed one-row
research manifest. The block covers the fused MLP, QKV projection, C32 cosine
normalization, 8x8 window attention, E4M3 value publication, output projection,
and residual. At `2,496 x 2,688` (`6,709,248` tokens and `104,832` windows),
the ordinary fused block measured `9.052 ms`; CUDA Graph replay measured
`8.947 ms`, only about `1.2%` faster. The internal split was `2.784 ms` for
the MLP and `6.561 ms` for attention/QKV/window/projection. The direct-FP8
eager control measured `256.378 ms`, so the fused block was `28.32x` faster;
its output drift against that direct control was `0.000245 MAE`, with finite
output and `0.003052` p99 sampled absolute error.

This is the stronger full-eye result: once the block has already been reduced
to two physical launches, graph replay is no longer the dominant lever. The
remaining C32 cost is the attention and layout path itself. The next kernel
experiment therefore merged QKV packing, normalization, window attention,
value publication, and output projection as one block-level executor. The
result below remains a recovered-graph control, not native NVIDIA parity or a
temporal/stereo/VR result.

## Standalone fused-attention control

To test that next boundary without changing the recovered model, the retained
512x512 crop and the retained full-eye frame were exported at the boundary
after the existing fused Triton C32 MLP. A standalone C++/CUDA kernel then
performed QKV projection, C32 cosine normalization, 8x8 window attention,
recovered exponential/weight publication, weighted V, output projection, and
the residual write in one physical launch per window. The probe uses scalar
dot products rather than WMMA/Tensor-Core matrix instructions, so it is an
independent fusion control and not a candidate runtime.

| Input | Direct kernel | CUDA Graph | Graph gain | MAE vs fused Triton | Finite |
| --- | ---: | ---: | ---: | ---: | --- |
| 512x512 crop | 1.9836 ms | 1.9806 ms | 1.0015x | 0.0000445 | yes |
| 2496x2688 full eye | 50.8329 ms | 50.8331 ms | 1.0000x | 0.0000775 | yes |

The full-eye attention control is about `7.75x` slower than the existing
fused-Triton attention/QKV/window/projection portion of the complete C32 block
(`6.561 ms`), despite having only one launch per window. Together with the
separately measured fused WMMA C32 MLP (`1.535 ms`), this shows why launch
fusion alone cannot reach the native budget: the attention matrix products must
also use an efficient Tensor-Core layout and scheduling strategy. CUDA Graph
replay is neutral here because the timed path is already a single launch.

The output agreement is only a boundary sanity check. The reference is the
existing fused Triton recovered-graph output, not native NVIDIA output; the
probe's scalar accumulation and approximate recovered exponential are not
bit-exact claims. No new Skyrim capture, training run, or live runtime change
was made.

This result makes the public reverse-engineering reports directly relevant but
also narrows their implication: the native 15-fatbin/PTX evidence explains the
missing hardware-specific matrix/layout work, while the public B580 milestone's
fusion advice is necessary but insufficient by itself. The next worthwhile
local kernel experiment was WMMA/CUTLASS-style QKV/QK/AV/projection tiling;
that test is now complete. The next candidate is batched multi-window
execution, not another weight-only quantization pass.

## WMMA/Tensor-Core fused-attention control

The follow-up WMMA implementation kept the same frozen inputs and the same
single-window fusion boundary, but replaced the four large matrix products with
16x16 WMMA tiles: QKV, QK, weighted V, and output projection. Normalization,
the recovered exponential, FP8 publication, and the residual remained scalar
post-ops inside the block. It used `61,504` bytes of dynamic shared memory per
window and half accumulators for QKV/AV/output projection.

| Input | Scalar fused | WMMA fused | WMMA speedup | WMMA MAE vs fused Triton | Finite |
| --- | ---: | ---: | ---: | ---: | --- |
| 512x512 crop | 1.9836 ms | 1.0310 ms | 1.93x | 0.0001058 | yes |
| 2496x2688 full eye | 50.8329 ms | 28.0992 ms | 1.81x | 0.0001716 | yes |

The full-eye WMMA control is a real improvement, but it is still about
`4.28x` slower than the existing fused-Triton C32 attention/QKV/window/
projection portion (`6.561 ms`). CUDA Graph replay was again neutral or
slightly slower (`28.1763 ms` versus `28.0992 ms`), so launch submission is not
the cause of the remaining gap. The larger error relative to the Triton
boundary is expected from half accumulation and the deliberately approximate
math; this is a performance-control result, not native-output validation.

This is the most relevant local confirmation of the public findings so far:
Tensor-Core use matters, but simply putting WMMA inside one block per 8x8
window is not enough. The remaining gap is consistent with the native/public
reports' deeper requirements—FP8 Tensor-Core paths, swizzled/shared layouts,
more efficient window batching or persistence, register/occupancy tuning, and
fusing the surrounding block boundaries. It does not justify a live runtime
replacement yet. The next speed work should focus on measuring a batched
multi-window WMMA/CUTLASS-style executor or using the existing Triton fused
kernel as the baseline to optimize, while keeping native Feature 18 and all
training/data lineages untouched.

## Window-packed global-load WMMA control

The previous WMMA probe still staged Q/K/V in a `55,360`-byte shared-memory
window. To separate that cost, the same exported Q/K/V tensors were provided
already window-packed, with K additionally transposed on disk. The next C++
control loaded Q, K-transpose, and V directly from global memory, kept only
the score/probability/attended scratch in `30,720` bytes of shared memory, and
placed the small bias/cosine records in constant memory. The projection matrix
was copied to a small shared tile because the CUDA WMMA API does not support
loading a WMMA operand directly from constant memory.

| Input | Direct kernel | CUDA Graph | Graph gain | MAE vs fused Triton | Finite |
| --- | ---: | ---: | ---: | ---: | --- |
| 512x512 crop | 0.6756 ms | 0.6726 ms | 1.0044x | 0.00000973 | yes |
| 2496x2688 full eye | 16.5419 ms | 16.6131 ms | 0.9957x | 0.0000147 | yes |

This removes another `1.90x` from the shared-staged WMMA control, but it is
still `2.52x` slower than the existing fused-Triton C32 attention boundary
(`6.561 ms`) even though Q/K/V projection was already done for it. In other
words, the hand-written C++ attention-only control is slower than the whole
Triton C32 block (`9.052 ms`) and therefore is not a useful runtime candidate.
The numerical boundary remains strong and the output is finite, but it is only
agreement with the recovered Triton path, not native NVIDIA output.

This closes the bounded C++ kernel study. The public evidence is relevant in a
very concrete way: it correctly predicted that fusion, Tensor-Core use, FP8
boundaries, and layout choices would matter. Our local measurements also show
why matching native DLSS5 speed is not a matter of simply extracting weights
or replacing PyTorch with a few CUDA launches. The remaining work is a real
kernel/runtime project—specialized FP8 MMA or QMMA instructions, producer and
consumer layout fusion, persistent/batched window scheduling, and end-to-end
workspace reuse. We should use the already-working Triton fused path as the
optimization baseline rather than promote these exploratory C++ kernels.

The synchronized stage profile of the full public 1080p fast path gives the
next fusion map:

| Stage | Diagnostic elapsed |
| --- | ---: |
| pre | 7.20 ms |
| encoder C32 | 7.40 ms |
| encoder C64/C128/C256/C512 | 18.0 ms combined |
| ViT | 13.15 ms |
| decoder C512/C256/C128/C64/C32 | 26.2 ms combined |
| RGB | 9.82 ms |

The diagnostic segments sum to `81.69 ms`, while the steady CUDA-Graph run was
`62.75 ms`. The difference is expected because the diagnostic path forces a
device synchronization at every boundary and changes clock/overlap behavior;
the table is a prioritization map, not an additive timing model. It points to
stage-wide workspace/layout fusion—especially ViT, RGB, and the repeated C32
attention/MLP boundaries—rather than another isolated weight quantization
flag. For this branch, further work is justified only if we can implement a
batched FP8/QMMA or equivalent compiler-generated path and benchmark it against
the validated Triton control; the hand-written WMMA controls have reached a
clear negative go/no-go for runtime use.

## Relationship to the public reports

The new results agree with the most useful parts of the public evidence:

- [`neural-upstream` findings](https://github.com/matiasLombo/neural-upstream/blob/main/FINDINGS.md)
  report 15 fatbins containing PTX, reconstruction of the Ada kernel path, and
  about 3.27 ms for the neural network at 1280x720 on an RTX 4070 Ti. Its
  measurements are evidence for specialized low-level kernel engineering, not
  evidence that a Python/PyTorch graph will have the same cost.
- [`dlss5nr-b580` README](https://github.com/gggz114514-oss/dlss5nr-b580)
  documents the independent 71-block backend and separates its exact path from
  its fast FP16/INT8 path. It reports approximately 22.14 ms on B580 and 3.57
  ms on an RTX 4060 for its 256x256 fast experiment, while explicitly stating
  that the fast path had not yet matched the 4060 reference.
- [`dlss5nr-b580` milestone](https://github.com/gggz114514-oss/dlss5nr-b580/blob/main/docs/05-milestone.md)
  identifies larger fusion, fewer intermediate write-backs, and improved
  matrix execution as the remaining speed levers. Our CUDA Graph result
  independently confirms the launch/write-back side of that diagnosis.
- [`MLX-DLSS accuracy and speed`](https://github.com/iamwavecut/MLX-DLSS#accuracy-and-speed)
  remains useful as a fidelity/weight-recovery reference, but its documented
  portable video throughput is not a runtime target for SkyrimVR.

- [`neural-upstream`](https://github.com/matiasLombo/neural-upstream) is
  relevant for a different reason: it places the native NR evaluation before
  the game's own upscaler at render resolution and reports a roughly `3.27 ms`
  network cost at 1280x720 on an RTX 4070 Ti. That supports the reduced-input
  direction, but it still uses the native/rebuilt runtime and does not provide
  an OpenNR-owned independent kernel implementation or a drop-in Feature 18
  replacement.

- The current [`neural-upstream v0.3.0` release](https://github.com/matiasLombo/neural-upstream/releases/tag/v0.3.0)
  adds a useful warning for our design: its project-level measurement puts the
  network at about `4.8 ms` of an `8.9 ms` rendered frame, and reports that
  `DLSSNR.ScalingRatio` is inert. Real speed reduction requires actual
  downscaling or a second queue; validated private Color/Depth/MVec copies for
  that route cost about `0.07 ms`. This is consistent with our `864 x 480`
  result: changing the model input contract is meaningful, while a nominal
  scale setting is not. Its descriptor-ring and evaluate-cadence fixes matter
  to later temporal/frame-generation validation, but not to the current static
  speed number.

- A fresh search also found informal RTX 2070 extraction reports claiming
  `176` CUBINs and `174` launches from a live native run, plus paired FP8 and
  non-FP8 kernel variants. Those reports are useful hypotheses about the
  vendor dispatch surface, but no downloadable PTX/CUBIN/SASS payload was
  found in the associated public material. The checked-out
  [`neural-upstream` source](https://github.com/matiasLombo/neural-upstream)
  still provides the extractor/rebuilder and measurements, not a drop-in
  independent kernel package. We therefore did not install or execute any
  closed or unverified binary in OpenNR.

- [`DLSS5-NeuralScreen`](https://github.com/perseval-BLR/DLSS5-NeuralScreen)
  is relevant as an architecture and pipeline reference, not as an
  independent OpenNR runtime. Its current technical notes give a much more
  useful resolution-sensitive measurement on an RTX 5070 Ti: an isolated
  native NGX evaluation is about `2.90 ms` at 1280x720, `4.60 ms` at
  1920x1080, and `7.10 ms` at 2560x1440. At a 4K desktop, however, the
  legacy/upscale mode still evaluates the full-resolution feature at about
  `16.6 ms`; changing its work-scale slider does not help in that mode. Its
  `nr_small` path really lowers the network input and uses the residual
  composition `native + (nr_out - nr_in) * strength`, reporting about `7.25 ms`
  at the 2560x1440 reduced work size versus `16.05 ms` full-screen, with an
  end-to-end improvement from about 47.9 to 71.9 FPS. This is strong evidence
  for testing an OpenNR reduced-resolution residual branch, but it remains a
  native-NGX/desktop result: the release still requires NVIDIA's
  `nvngx_dlssnr.dll` and does not provide a reusable PTX/CUBIN launch contract
  for our recovered model.

- [`DLSS5VKLayer pipeline notes`](https://github.com/bmitch87/DLSS5VKLayer/blob/main/extracted_pipeline_notes.md)
  are useful for the exact Feature-18 resource/parameter contract and for
  confirming that the public binary notes are still centered on NGX and
  opaque driver interfaces. The checked public repositories exposed source,
  disassembly notes, or release binaries that still depend on the native
  runtime; they did not expose a verified standalone PTX/CUBIN/SASS package
  plus the launch descriptors needed to execute it as an OpenNR-owned graph.

The public PTX work is relevant as a blueprint, but it does not remove the
need for an OpenNR-owned runtime. Rebuilding NVIDIA-oriented kernels for Ada is
a different route from running the recovered logical graph, and public kernel
payloads/driver contracts are not being installed into the known-good OpenNR
path here.

## Decision

### Speed branch: continue, but only as a bounded runtime experiment

This route is worth one more bounded engineering phase because it produced a
real full-frame improvement and demonstrates that the recovered resource is
usable without new training data. Target-GPU dense specialization moved the
isolated 1080p probe from about `110 ms` to about `61.9 ms`, so this is not a
dead end. It is still far from the native budget and the remaining gain
requires larger fusion/workspace/layout work, not just another quantization
flag. Naive block skipping is not an acceptable shortcut at the measured
quality drift.

### OpenNR promotion: no

The result is not a live runtime, not a temporal/stereo validation, and not a
VR frame-budget pass. The current 1080p independent path is still far too slow
for the target. `promotion=false` remains in force.

### Data collection and training: no new data for this speed question

More Skyrim captures, LoRAs, or student retraining cannot remove the measured
launch and workspace costs. Existing captures are sufficient for the next
speed experiments. New captures become useful only after an owned runtime can
run the correct full-eye/temporal contract and we need to evaluate quality or
temporal failure modes.

## Recommended next experiment

1. Keep the public adapter stack in an external research copy and add a proper
   per-stage CUDA-event breakdown at 33%, 50%, and 100% eye resolutions. The
   current best launch choices should be the starting control.
2. Replace the Python/Triton orchestration with a small C++/CUDA or persistent
   CUDA-graph executor using preallocated workspaces, static weight pointers,
   and explicit stereo sequencing. The first concrete port should be the
   validated C32 WMMA shape, followed by the ViT and RGB boundaries that are
   largest in the stage profile.
3. Measure actual two-eye serial and overlapped timings, including input copies,
   output resolve, synchronization, and temporal-state ownership.
4. Compare the result to the existing native Feature 18 timing with the same
   eye dimensions and accounting boundary.
5. In parallel, treat the 512 residual wrapper as the quality candidate and
   the 256 wrapper as the speed candidate. Run both against existing native
   teacher images, with manually reviewed faces, hair, armor, foliage, dark
   interiors, and bright exteriors before considering any student/runtime
   work.
6. Stop the independent full-resolution route if the fused executor still
   cannot approach the native budget after the major workspace/layout fusions;
   use the smaller student or a reduced-resolution residual route for an
   OpenNR-owned “DLSS5 look” instead.

The current best practical interpretation is therefore: **the recovered white
box is useful as a teacher and as a source for a fused reduced-resolution
runtime, but it is not yet a viable full-resolution replacement for NVIDIA's
native DLSS5/NR path.**

## Public Safetensors provenance

The public `sekkit/open-dlss5-nr` Hugging Face mirror was downloaded into an
isolated research directory and inspected as data only. It contains a
`147,943,434`-byte Safetensors file with `793` structured tensors. Its embedded
manifest declares the same source DLL hash
`e16bcf15e16e13f527491cdf7845b2fe6521a738d8f7c9c721866a8496e1fc8e`, the same
extracted-resource hash
`836f445d06ecd2e59bb9f17b84b91c143396fd76ccda1c9dc7fe81d5edd548f4`, and the
same `153` source records as the local resource. The public file explicitly
marks raw records as excluded; its 153 per-record manifest hashes all match
the local pinned records (`0` mismatches).

This is useful as a portable, inspectable weight interchange format and as
additional evidence that our local resource is the same recovered weight set.
It does not provide NVIDIA's PTX/CUBIN runtime, a new model, or a speed
shortcut. The checked public GitHub projects expose reconstructed source,
disassembly notes, or AMD HIP kernels; no drop-in standalone NVIDIA PTX/SASS
payload was found in those source trees. The public AMD runtime remains
valuable as a kernel-fusion reference, but it still needs the user's own
`nvngx_dlssnr.dll` weights and reports performance as work in progress.

The latest public release checks do not change that inventory. The current
`neural-upstream` release is an add-on asset that still calls the NVIDIA/NGX
path; it is not a standalone PTX drop. The current AMD `v0.2.18` release is
also distributed as a setup executable, while its tagged source tree contains
no CUDA or HIP kernel sources. Those binaries remain outside this project and
were not downloaded or executed here.

## Artifacts

- `tools/benchmark_b580_cuda_fast_probe.py`
- `out/public_b580_cuda_fast_pairs_256_20260912/result.json`
- `out/public_b580_cuda_fast_batched_256_20260912/result.json`
- `out/public_b580_cuda_fast_batched_graph_256_20260912/result.json`
- `out/public_b580_cuda_fast_batched_graph_512_20260912/result.json`
- `out/public_b580_cuda_fast_batched_graph_864x480_20260912/result.json`
- `out/public_b580_cuda_fast_batched_graph_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_batched_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_batched_k8fp16_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_dynamicfront_k8fp16_graph_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_c32bm16_k8fp16_graph_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_c32bm16_swinbm64_k8fp16_graph_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_c32bm16_swinbm64_headbm64_k8fp16_graph_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_best_tuned_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_best_dense_tuned_defaulttile_warm_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_best_dense_bm32bn64_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_best_dense_bm64bn64w8_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_best_dense_batched_bm32bn64_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_c32lut_best_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_old_swin_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_old_normalize_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_old_all_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_skip_vit_half_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_skip_body_half_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_skip_half_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_best_tuned_512_20260912/result.json`
- `out/public_b580_cuda_fast_batched_fp8_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_batched_cublasfp8_1080p_20260912/result.json`
- `out/public_b580_cuda_fast_batched_cublasfp8_256_20260912/result.json`
- `out/public_b580_residual_scale_512_dynamic_graph_20260912/result.json`
- `out/public_b580_residual_scale_256_dynamic_graph_20260912/result.json`
- `out/public_b580_residual_scale_512_dynamic_graph_teacher_20260912/result.json`
- `out/public_b580_residual_scale_256_dynamic_graph_teacher_20260912/result.json`
- `out/public_b580_residual_scale_512_tuned_dynamic_graph_teacher_20260912/result.json`
- `out/public_b580_residual_scale_256_tuned_warm_graph_teacher_20260912/result.json`
- `tools/benchmark_b580_residual_scale_probe.py`
- `tools/probe_triton_fp8_dot.py`
- `tools/cuda_executor_smoke_20260912.cu`
- `tools/cuda_c32_mlp_executor_probe_20260912.cu`
- `tools/cuda_c32_attention_executor_probe_20260912.cu`
- `tools/cuda_c32_attention_wmma_executor_probe_20260912.cu`
- `tools/cuda_c32_attention_wmma_packed_executor_probe_20260912.cu`
- `tools/cuda_c32_attention_wmma_global_executor_probe_20260912.cu`
- `tools/export_c32_attention_cuda_inputs.py`
- `tools/probe_native_style_c32_block_cuda.py`
- `tools/export_c32_cuda_probe_inputs.py`
- `tools/validate_c32_cuda_probe_output.py`
- `tools/export_vit_cuda_probe_inputs.py`
- `tools/cuda_vit_projection_executor_probe_20260912.cu`
- `tools/validate_vit_cuda_probe_output.py`
- `tools/benchmark_vit_attention_cuda_probe.py`
- `tools/benchmark_vit_block_cuda_fast_probe.py`
- `tools/benchmark_vit_stage_cuda_fast_probe.py`
- `tools/verify_public_safetensors_provenance.py`
- `out/cuda_executor_smoke_20260912`
- `out/cuda_c32_mlp_executor_probe_20260912`
- `out/cuda_c32_real_inputs_20260912/manifest.json`
- `out/cuda_c32_real_validation_20260912/result.json`
- `out/cuda_c32_real_output_20260912.bin`
- `out/cuda_c32_real_output_cpp_graph_20260912.bin`
- `out/c32_attention_inputs_crop512_20260912/manifest.json`
- `out/c32_attention_inputs_full_20260912/manifest.json`
- `out/cuda_c32_attention_cpp_crop512_20260912.bin`
- `out/cuda_c32_attention_cpp_full_20260912.bin`
- `out/cuda_c32_attention_wmma_crop512_20260912.bin`
- `out/cuda_c32_attention_wmma_full_20260912.bin`
- `out/cuda_c32_attention_wmma_packed_crop512_20260912.bin`
- `out/cuda_c32_attention_wmma_packed_full_20260912.bin`
- `out/cuda_c32_attention_wmma_global_crop512_20260912.bin`
- `out/cuda_c32_attention_wmma_global_full_20260912.bin`
- `out/c32_block_full_eye_manifest_20260912/rows.json`
- `out/native_style_c32_block_probe_full_graph_20260912/result.json`
- `out/cuda_vit_real_inputs_20260912/manifest.json`
- `out/cuda_vit_projection_real_run_20260912/`
- `out/cuda_vit_projection_real_validation_20260912/result.json`
- `out/cuda_vit_attention_probe_20260912/result.json`
- `out/cuda_vit_block_fast_probe_20260912/result.json`
- `out/cuda_vit_stage_fast_probe_20260912/result.json`
- `out/cuda_vit_stage_fast_attention_control_20260912/result.json`
- `out/cuda_vit_stage_fp8_probe_20260912/result.json`
- `out/cuda_vit_stage_graph_probe_20260912_result.json`
- `out/public_b580_cuda_fast_best_dense_batched_bm32bn64_864x480_20260912/artifact/result.json`
- `out/public_safetensors_provenance_20260912/result.json`
- `out/public_b580_cuda_fast_profile_1080p_20260912/result.json`
- `out/dlssnr_resource_map_e16bcf15_20260912/manifest.json`
