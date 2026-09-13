# White-box native-style CUDA fusion probes

Date: 2026-09-12  
Status: offline backend research only; `promotion=false`  
Live Skyrim/MGO runtime changed: no  
Training started: no  
New Skyrim capture started: no

## Executive result

The newest public DLSS5-NR findings are directly relevant, and the first local
CUDA experiment now demonstrates the same mechanism on our recovered weights:
the seconds-versus-milliseconds gap is substantially reduced when a sequence
of small graph operations is replaced by one fixed-shape tensor-core kernel.

The local probe used the real logical weights from the recovered
`dlssnr-weights-logical.safetensors` file and a real full-eye Skyrim feature
tensor at `2496x2688`. It fused the feed-forward portion of
`block0.layer0`:

```text
C32 -> C128 projection -> quadratic gate -> E4M3 publication
   -> C128 -> C32 projection -> cosine residual
```

It did not run attention, window partition/reversal, the other 70 blocks,
temporal state, stereo coupling, or the native NVIDIA DLL.

That limitation applies to the initial C32 feed-forward measurement. The
follow-up probes documented below add the C32 attention path, complete C64,
C128, C256, C512, and C1024 global blocks, but still do not constitute one
full-model runtime.

## Local measurement

The primary run is
[`out/native_style_c32_probe_20260912/result.json`](../out/native_style_c32_probe_20260912/result.json).

| Quantity | Result |
| --- | ---: |
| Real feature tensor | `2496x2688x16` |
| C32 rows | `6,709,248` |
| Fused launch (`BM=32`) | `5.477 ms` median |
| Eager direct-FP8 control (`32,768`-row chunks) | `127.633 ms` median |
| Measured reduction | `23.30x` |
| Fused-vs-control MAE | `0.0000523471` |
| Fused-vs-control p99/p999 sample | `0.00048828125` |
| Fused-vs-control maximum | `0.001953125` |
| Values differing by more than `0.001` | `0.01098%` |
| Peak CUDA allocation | `4.09 GiB` |

The launch-shape sweep used the same input, weights, and code:

| `BM` | Fused median | Eager control median | Ratio in that run |
| ---: | ---: | ---: | ---: |
| 16 | `2.825 ms` | `110.316 ms` | `39.05x` |
| 32 | `5.477 ms` | `127.633 ms` | `23.30x` |
| 64 | `3.360 ms` | `499.062 ms` | `148.51x` |

The `BM=64` eager result is visibly allocation/fragmentation-sensitive, so it
is not used as a universal speed claim. The stable conclusion is narrower:
one fused C32 feed-forward region is already in the low-single-digit
millisecond range, while the current eager/chunked implementation is in the
hundreds of milliseconds for that same region. The E4M3 and residual math are
close enough to the direct-FP8 control that this is not a quality-versus-speed
trade made by simply deleting the activation.

The reusable probe source is
[`tools/probe_native_style_c32_cuda.py`](../tools/probe_native_style_c32_cuda.py).
The CUDA environment used PyTorch `2.7.1+cu128`, Triton-Windows `3.3.1`, and
the local RTX 5070 Ti. Triton was installed only in the research venv; no game
or packaged runtime files were modified.

## Attention follow-up

The second probe used the same recovered weights and the same real Skyrim eye,
and added the attention half of `block0.layer0`:

```text
C32 input -> Q/K/V projection -> C32 cosine normalization -> E4M3
   -> 8x8 window attention -> E4M3 value publication
   -> C32 output projection -> cosine residual
```

The primary full-eye result is
[`out/native_style_c32_attention_probe_full_20260912/result.json`](../out/native_style_c32_attention_probe_full_20260912/result.json).
It uses `2496x2688` (`6,709,248` tokens and `104,832` windows), not a
synthetic small tensor.

| Quantity | Result |
| --- | ---: |
| Fused QKV + attention + projection (`M=16`) | `7.394 ms` median |
| Eager direct-FP8 attention control | `231.418 ms` median |
| Measured reduction | `31.30x` |
| Fused-vs-control MAE | `0.0000446396` |
| Fused-vs-control p99/p999 sample | `0.00048828125` / `0.0068092346` |
| Fused-vs-control maximum | `0.43359375` |
| Values differing by more than `0.001` | `0.710998%` |
| Peak CUDA allocation | `5.42 GiB` |

The maximum error is caused by the intentionally approximate compact
exponential/softmax helper and occurs in a small tail of values; the mean is
still close to the control. This is a backend timing proof, not a claim of
native NVIDIA bit identity. The outlier distribution must be revisited before
this kernel could be used as a quality-preserving replacement.

The attention tile sweep was small but informative:

| Attention tile `M` | Fused median | Eager control median | Ratio in that run |
| ---: | ---: | ---: | ---: |
| 16 | `7.394 ms` | `231.418 ms` | `31.30x` |
| 32 | `7.511 ms` | `211.917 ms` | `28.21x` |
| 64 | `6.444 ms` | `209.516 ms` | `32.51x` |

`M=64` was the fastest of these three configurations on this GPU, but the
differences are small enough that a larger sweep with stable repetitions is
needed before choosing a production tile. Combining the best independent
component medians gives a rough serial C32-block budget of `2.825 + 6.444 =
9.269 ms` at this unusually large per-eye resolution. That sum is not a
combined-kernel measurement, but it prevents us from treating the 7 ms
attention number as the cost of a complete block.

The attention source is
[`tools/probe_native_style_c32_attention_cuda.py`](../tools/probe_native_style_c32_attention_cuda.py).
It uses a flattened launch because the full eye has more than 65,535 windows
and therefore cannot be represented directly as the second dimension of a
CUDA grid on this backend. That change is launch bookkeeping only; it does
not alter the window math.

## Complete C32 block follow-up

The two halves were then measured in one serial harness, with the fused MLP
output feeding the fused attention path. The primary result is
[`out/native_style_c32_block_probe_full_20260912/result.json`](../out/native_style_c32_block_probe_full_20260912/result.json).

| Quantity | Result |
| --- | ---: |
| Fused complete block (`MLP M=16`, attention `M=64`) | `11.037 ms` median |
| Fused MLP component in that run | `3.297 ms` median |
| Fused attention component in that run | `7.751 ms` median |
| Eager direct-FP8 complete-block control | `267.922 ms` median |
| Measured reduction | `24.28x` |
| Fused-vs-control MAE at block output | `0.0002454205` |
| Fused-vs-control p99/p999 sample | `0.00305176` / `0.0144043` |
| Fused-vs-control maximum | `0.380859` |
| Values differing by more than `0.001` | `3.1328%` |

This is the most useful local result so far. It shows that a real recovered
C32 block can be made a roughly ten-millisecond CUDA operation at the current
`2496x2688` per-eye feature size, instead of a several-hundred-millisecond
eager operation. It also exposes the important quality caveat: the end-to-end
block MAE remains small, but nonlinear attention amplifies the MLP's rounding
differences into a nontrivial tail. The current compact softmax helper is
therefore suitable for a timing/control experiment, not yet for a visual
replacement.

The complete-block source is
[`tools/probe_native_style_c32_block_cuda.py`](../tools/probe_native_style_c32_block_cuda.py).
The speedup is not a projection of the earlier two measurements: the harness
actually runs fused MLP, fused QKV/attention, and the residual serially inside
the timed GPU event. It still measures only `block0.layer0` and still uses the
local eager recovered graph as its control.

## Pooled C64 block follow-up

The next probe exercised the first pooled two-head C64 block, `block5.layer0`,
using the real recovered prefix `block0 -> average_pool2 -> blocks1-3 -> block4
downsample`. The first implementation carried branch sums in FP32 and split the
final C64 projection into two C32 reductions. That version was fast but failed
parity (`0.02452 MAE`). The kernel was corrected to preserve the reference's
half-visible boundaries after each input-head reduction and branch sum, and to
use a single C64 projection. The corrected intermediate checks are effectively
exact against the eager direct-FP8 control:

| Boundary | MAE |
| --- | ---: |
| C64 feed-forward residual publication | `0.0` |
| Q publication | `0.0000549183` |
| K publication | `0.0` |
| V publication | `0.0` |

The full-stage result is
[`out/native_style_c64_block_probe_full_20260912/result.json`](../out/native_style_c64_block_probe_full_20260912/result.json).

| Quantity | Full C64 stage | 480x272 top-left proxy |
| --- | ---: | ---: |
| Tokens | `419,328` | `130,560` |
| Fused complete block | `1.980 ms` | `0.701 ms` |
| Eager direct-FP8 control | `35.823 ms` | `16.213 ms` |
| Measured reduction | `18.09x` | `23.11x` |
| Fused-vs-control MAE | `0.0004544322` | `0.0004653407` |
| Values differing by more than `0.001` | `1.4287%` | `1.3855%` |

The C64 result is materially better than the first attempt and establishes the
important implementation lesson: matching the recovered graph requires
matching its FP16/E4M3 boundaries, not merely using the same matrices. The
remaining C64 output tail is in the attention path (the input, MLP, and Q/K/V
boundaries are already controlled); it is still a backend-control drift, not a
native-DLL parity result.

The reusable C64 probe is
[`tools/probe_native_style_c64_block_cuda.py`](../tools/probe_native_style_c64_block_cuda.py).

## C128 block follow-up

The next measurement kept the real recovered prefix and exercised the first
four-head C128 block, `block9.layer0`, at the full recovered stage size. The
stable run used a 16-row MLP tile and a 64-row attention tile; an earlier
32-row attention configuration was substantially slower because of register
pressure, which is an important reminder that a fused graph still needs
hardware-specific tile selection.

Result:
[`out/native_style_c128_block_probe_full_m16_m64_repeat_20260912/result.json`](../out/native_style_c128_block_probe_full_m16_m64_repeat_20260912/result.json).

| Quantity | Result |
| --- | ---: |
| Recovered stage | `312x336`, `104,832` tokens, `1,638` windows |
| Fused complete block (`MLP M=16`, attention `M=64`) | `1.715 ms` median |
| Fused MLP component | `0.948 ms` median |
| Fused attention component | `0.772 ms` median |
| Eager direct-FP8 complete-block control | `17.108 ms` median |
| Measured reduction | `9.98x` |
| Fused-vs-control MAE | `0.0013339057` |
| Fused-vs-control p99/p999 sample | `0.03515625` / `0.1361389` |
| Fused-vs-control maximum | `1.4375` |
| Values differing by more than `0.001` | `6.436%` |

The mean is inside the approximate `0.0013-0.0015` drift range the user said
would be acceptable for this experiment, but that is still a comparison with
the local eager direct-FP8 control. It is not a native NVIDIA output match,
and the tail is too large to call the kernel visually interchangeable without
an image-level review.

The reusable C128 probe is
[`tools/probe_native_style_c128_block_cuda.py`](../tools/probe_native_style_c128_block_cuda.py).

## C256 block follow-up and the shared-memory boundary

The C256 probe exercised `block15.layer0` after the real prefix through
`block14`. A monolithic grouped-MLP kernel requested about `139,264` bytes of
shared memory, above the approximately `101,376`-byte limit exposed by this
GPU/backend configuration. The attention projection also became unstable when
the entire C256 projection was kept in one large program. The working version
therefore splits at natural publication boundaries: grouped FFN fragments,
FFN projection/residual, per-head attention, and attention projection/residual.

The stable full-stage result is
[`out/native_style_c256_block_probe_full_padded_repeat_20260912/result.json`](../out/native_style_c256_block_probe_full_padded_repeat_20260912/result.json).

| Quantity | Result |
| --- | ---: |
| Logical stage / kernel stage | `156x168` / `160x168` (4 columns of right padding) |
| Logical tokens / window count | `26,208` / `420` |
| Fused complete block (`split` mode) | `1.166 ms` median |
| Fused MLP component | `0.571 ms` median |
| Fused attention component | `0.579 ms` median |
| Eager direct-FP8 complete-block control | `22.411 ms` median |
| Measured reduction | `19.23x` |
| Fused-vs-control MAE | `0.0010023043` |
| Fused-vs-control p99/p999 sample | `0.0234375` / `0.06640625` |
| Fused-vs-control maximum | `0.546875` |
| Values differing by more than `0.001` | `9.034%` |

The first full run was a cold/measurement outlier at about `9.7 ms`; five
stable repeated samples after warmup were about `1.16 ms`. This is why the
repeat result, rather than the first launch, is used for the feasibility
decision. The lesson is positive but bounded: splitting a large block can
make it runnable and fast, at the cost of extra dispatches and workspaces.

The reusable C256 probe is
[`tools/probe_native_style_c256_block_cuda.py`](../tools/probe_native_style_c256_block_cuda.py).

## C512 sixteen-head split block

The new C512 probe exercised `block23`, the first 16-head split-window block,
after the real recovered prefix through `block22`. It fuses the first
projection, eight grouped `64->256->64` quadratic FFNs, FFN projection and
residual, 16-head QKV/normalization, 8x8 window attention, and the final
attention projection/residual. The logical full stage is `84x80`; the kernel
pads the final four rows to `88x80` so every window is complete.

Result:
[`out/native_style_c512_block_probe_full_20260912/result.json`](../out/native_style_c512_block_probe_full_20260912/result.json).

| Quantity | Result |
| --- | ---: |
| Logical/kernel stage | `84x80` / `88x80` |
| Logical/kernel tokens | `6,720` / `7,040` |
| Window count / heads | `110` / `16` |
| Fused complete block (`split attention`, `M=64`) | `0.977 ms` median |
| Fused MLP component | `0.340 ms` median |
| Fused attention component | `0.645 ms` median |
| Eager direct-FP8 complete-block control | `8.209 ms` median |
| Measured reduction | `8.40x` |
| Fused-vs-control MAE on this full probe | `0.0` |
| Fused-vs-control p99/p999/max | `0.0` / `0.0` / `0.0` |

The zero-drift result is a useful observation for this particular input and
final FP8 boundary, not evidence of equality with NVIDIA. The latest saved
probe reports about `0.110 s` for cached compile/first-run setup; it is excluded
from the steady-state GPU-event timing. A real runtime would still need
ahead-of-time compilation or startup caching, plus persistent workspace and
buffer management.

This is the strongest local evidence so far that the recovered weights are
not inherently too slow. A high-channel split block can be reduced below one
millisecond on this GPU when its physical layouts and dispatch boundaries are
chosen deliberately. It still represents only one block, and the C512 family,
global core, decoder, full-resolution endpoints, host scheduling, and stereo
work remain unmeasured as one runtime.

The reusable C512 probe is
[`tools/probe_native_style_c512_split_block_cuda.py`](../tools/probe_native_style_c512_split_block_cuda.py).

### C256/C512 direct-packing check

The direct window-packing transformation was then applied to the two wider
split families using paired row-major and packed measurements in the same
invocation. It did not help either family:

| Family | Row-major block | Packed block | Packed / row-major | Output parity |
| --- | ---: | ---: | ---: | --- |
| C256 `block15` | `9.764 ms` | `9.859 ms` | `0.990x` | exact in the A/B control |
| C512 `block23` | `0.973 ms` | `0.983 ms` | `0.990x` | exact in the A/B control |

These are layout-comparison timings, not replacements for the earlier
resource-safe C256 split timing (`1.166 ms`) or the C512 split timing
(`0.977 ms`); the wider-family A/B harness has different launch and control
configuration. The conclusion is still robust: direct packing is not a
global optimization. It is useful for the tested C32/C64 shapes, while C128,
C256, and C512 require their own fusion, tiling, and workspace decisions.

Artifacts: [`out/native_style_c256_packed_probe_full_20260912/result.json`](../out/native_style_c256_packed_probe_full_20260912/result.json)
and [`out/native_style_c512_packed_probe_full_20260912/result.json`](../out/native_style_c512_packed_probe_full_20260912/result.json).

## C1024 global-core follow-up

The global core was the next critical test because its 32-head attention spans
the entire latent image instead of an 8x8 window. The probe exercised
`block31`, after the real recovered prefix through the C512-to-C1024
transition, at the full `40x44` global stage (`1,760` tokens). It uses a
streaming two-pass attention kernel: one pass forms the vendor-style softmax
denominator over 64-key tiles, and a second pass recomputes the weights and
reduces the value vectors. This avoids materializing the full 32-head
query-key/probability tensors.

The stable full-stage result is
[`out/native_style_global_block_probe_full_20260912/result.json`](../out/native_style_global_block_probe_full_20260912/result.json).

| Quantity | Result |
| --- | ---: |
| Global stage | `40x44`, `1,760` query tokens, `1,792` padded key tokens |
| Heads / channels per head | `32` / `32` |
| Fused complete block (`attention M=16`) | `2.455 ms` median |
| Fused FFN component | `0.774 ms` median |
| Fused global-attention component | `1.558 ms` median |
| Eager direct-FP8 complete-block control | `40.683 ms` median* |
| Measured reduction | `16.57x` |
| Fused-vs-control MAE | `0.0008533683` |
| Fused-vs-control p99/p999 sample | `0.015625` / `0.125` |
| Fused-vs-control maximum | `1.0` |

*The eager samples included one faster allocator/cache outlier (`23.45 ms`),
so the median is reported and the control is only a local reference. The
fused samples were stable at `2.4525-2.4614 ms`. The global attention
intermediate itself was only `0.0001888774` MAE when fed the exact reference
Q/K/V publications; the full-block drift is therefore small enough for this
backend experiment, but still not a native NVIDIA comparison.

The full-stage tile sweep was not a free win: attention `M=32` measured
`2.462 ms`, essentially tied but slightly slower, while `M=8` is rejected by
this Triton backend because its tensor-core dot requires at least 16 query
rows. The selected `M=16` is a measured configuration, not a universal CUDA
choice.

The reusable global-core probe is
[`tools/probe_native_style_global_block_cuda.py`](../tools/probe_native_style_global_block_cuda.py).

## Resolution scaling and feasibility boundary

The same complete C32 kernel was measured on a top-left proxy of the real
capture at `1920x1080`, and on a `960x544` proxy representing a pooled-scale
workload:

| Probe | Tokens | Fused complete block | Eager control | Speedup |
| --- | ---: | ---: | ---: | ---: |
| `2496x2688` full eye | `6,709,248` | `11.037 ms` | `267.922 ms` | `24.28x` |
| `1920x1080` proxy | `2,073,600` | `3.500 ms` | `80.169 ms` | `22.90x` |
| `960x544` pooled-scale proxy | `522,240` | `0.912 ms` | `21.259 ms` | `23.30x` |

These measurements are enough to reject two opposite mistakes. The eager
PyTorch path is not a meaningful runtime implementation: fusion removes an
order of magnitude of overhead across every measured channel family. But the
result also cannot be promoted to a full white-box runtime by multiplying one
block by 71. The graph has changing channel widths, spatial scales,
split/global attention, decoder transitions, and two full-resolution regions.
The C32 endpoints alone are roughly `22 ms` at the current full-eye shape,
while C64/C128/C256/C512 each have different dispatch and rounding behavior.
A complete VR schedule therefore needs structural resolution reduction, a
smaller network, or a specialized runtime that proves the entire graph fits
the frame budget.

### Whole-graph reduced-resolution check

To separate the resolution lever from the fused-kernel work, the existing
full-eye test row was also run through the recovered eager graph at reduced
internal resolution. The output was brought back to `2496x2688` with a
matched-residual composition, so this is a speed/appearance probe rather than
full-resolution white-box parity.

| Internal scale | Network resolution | Model median | Relative to full | Peak allocation |
| ---: | ---: | ---: | ---: | ---: |
| `1.00` | `2496x2688` | `2330.6 ms` | `1.00x` | `3.72 GB` |
| `0.75` | `1920x2048` | `1597.3 ms` | `1.46x` faster | `2.07 GB` |
| `0.50` | `1280x1344` | `1066.3 ms` | `2.19x` faster | `1.37 GB` |

These three runs confirm the direction but also show why simply turning down
resolution cannot rescue this eager executor: halving each dimension reduced
the measured model time by only about `2.2x`, not enough for a VR frame budget,
and the full model still executes all 71 blocks. The result is affected by
PyTorch launch and allocation overhead, so it should not be read as the final
scaling of a fused runtime. It does, however, support the public community
observation that a work-area/resolution dial is a real structural performance
lever. The saved outputs and command results came from the existing Skyrim
capture; no new training or raw capture data was needed.

The reusable reduced-resolution probe is
[`tools/benchmark_whitebox_resolution_scale.py`](../tools/benchmark_whitebox_resolution_scale.py).

There is also a useful local control from the separate portable-model study:
a fixed-shape TensorRT engine for that much smaller/different RGB model ran at
`7.48 ms/eye` median (`10.11 ms/eye` p95) at the same `2496x2688` color shape
on the RTX 5070 Ti. Its quality and conditioning contract failed the OpenNR
teacher gates, so it is not a candidate for promotion. It does prove an
important split: a compiled fixed-shape executor can meet a plausible model
budget on this GPU, while the recovered 71-block graph's current executor
cannot. The result is documented in
[`docs/DLSS5_PORTABLE_MODEL_ASSESSMENT_20260910.md`](DLSS5_PORTABLE_MODEL_ASSESSMENT_20260910.md).

As a lower-bound check, the same arithmetic was run with the actual
`block70.layer0` standard-C32 weights at the full-eye shape. It measured
`11.020 ms` fused versus `268.604 ms` eager. The input was deliberately the
block-0 adapter output because producing the real decoder-to-block-70 tensor
would require running the unoptimized middle of the network; this is therefore
an arithmetic timing result, not a block-70 feature-contract or quality test.
Nevertheless, it means the two full-resolution standard-C32 endpoints alone
would consume roughly `22 ms` if both were implemented with this current
kernel family, before transitions, low-resolution blocks, global attention,
decoder work, copies, stereo, or host scheduling are counted.

Result:
[`out/native_style_c32_block70_probe_full_20260912/result.json`](../out/native_style_c32_block70_probe_full_20260912/result.json).

## Representative 71-block budget estimate

The measured family results can now be mapped onto the recovered forward and
decoder schedule to obtain a current-kernel block-core estimate. This is not a
formal lower bound and is not a claim that every block has identical timing:
it uses the measured full-stage representative for each family, scales the C32
half-resolution representative by token count, and excludes transitions,
memory copies, allocation, compilation, host scheduling, and possible
cross-eye batching.

| Schedule region | Blocks | Representative basis | Estimated core time |
| --- | ---: | ---: | ---: |
| Full-resolution C32 entry | `1` | full C32 `11.037 ms` | `11.037 ms` |
| Half-resolution C32 | `4` | `960x544` proxy scaled to `1248x1344`: `2.930 ms` | `11.720 ms` |
| C64 encoder | `4` | full C64 `1.980 ms` | `7.919 ms` |
| C128 encoder | `6` | full C128 `1.715 ms` | `10.289 ms` |
| C256 encoder | `8` | full C256 `1.166 ms` | `9.325 ms` |
| C512 split encoder | `8` | full C512 `0.977 ms` | `7.818 ms` |
| C1024 global core | `8` | full global `2.455 ms` | `19.643 ms` |
| C512 split decoder | `8` | same C512 family basis | `7.818 ms` |
| C256 decoder | `8` | same C256 family basis | `9.325 ms` |
| C128 decoder | `6` | same C128 family basis | `10.289 ms` |
| C64 decoder | `4` | same C64 family basis | `7.919 ms` |
| Full-resolution C32 exit | `5` | same full C32 family basis | `55.184 ms` |
| **Block-core estimate per eye** | **`71`** | **representative-only sum** | **`~168.3 ms`** |

The C32 half-resolution row is the only token-scaled value; all other rows are
direct full-stage representative timings. The estimate is deliberately
optimistic because it omits every non-block cost, though cross-block fusion or
cross-eye batching could reduce it. If both eyes were run as independent
serial schedules, the corresponding block-core estimate would be about
`336.6 ms` per stereo frame. Even allowing for batching and overlap, this is
far outside an 11.1 ms 90-Hz or 22.2 ms 45-Hz VR frame budget for the current
kernel family and full-eye geometry.

This does not prove that a highly specialized NVIDIA-style implementation
could never be faster—the public PTX work shows how much fusion and fixed
layout can matter. It does prove that ordinary weight-only quantization of the
faithful 71-block graph is not the strategy that closes our VR gap. The
remaining credible levers are structural: lower processing resolution,
skipping or reducing blocks, a much smaller student, or reuse of the native
NVIDIA runtime on NVIDIA hardware. The local probes show that the recovered
weights are a usable teacher for those experiments; they do not make the
faithful graph itself a practical OpenNR runtime.

## What the new public evidence means for OpenNR

### PTX/SASS availability: contracts are public, drop-in kernels are not

The promised search for reusable extracted kernels did not find a public
drop-in NVIDIA PTX/CUBIN/SASS bundle. `neural-upstream` publishes its wrapper
and source code, while its findings document that the author extracted 15
fatbins and about 35 MB of readable PTX from a user-supplied DLL, translated
the Blackwell/Hopper synchronization features, assembled an Ada build, and
measured it. The repository does not present those NVIDIA kernel artifacts as
part of its source tree. The separate Linux bridge is explicit that it ships
no NVIDIA DLL, CUBIN, model weights, executable, capture, or log.

I also preserved a source-only depth-1 snapshot of the public project at
`C:\OpenNR\research\neural_upstream_20260912` (commit
`c06c07b27c3c5af0d916c3d9545434735d624bdf`). It contains the wrapper, HLSL
support code, and the written findings, but no vendor DLL or extracted kernel
payload.

That is still highly useful to us: it gives us the kernel families, fusion
boundaries, synchronization substitutions, and measurement methodology. It
does not give us a safe artifact we can copy into OpenNR. The local native DLL
inventory remains the provenance-controlled source for our own research, and
the local Triton probes remain independently written backend experiments.

The strongest timing evidence in that project is also a boundary marker, not a
promise that any graph wrapper will be fast: its profiler reports about
`3.27 ms` for the network at `1280x720` render resolution on an RTX 4070 Ti,
with colour encode/decode each around `0.014-0.017 ms`. The repository's own
source explains that this path hooks NGX and lets the shipped/rebuilt low-level
runtime execute the network; it does not execute the recovered PyTorch graph.
That is exactly the gap this local probe is beginning to close at the kernel
level, but only for individual block families so far.

Sources: [neural-upstream source repository](https://github.com/matiasLombo/neural-upstream),
[neural-upstream findings](https://github.com/matiasLombo/neural-upstream/blob/main/FINDINGS.md),
[Linux bridge artifact notice](https://github.com/ccoredesenvolvimento/dlss5-linux-bridge).

### AMD reconstruction: directly relevant engineering evidence

The public AMD project describes a from-scratch HLSL/D3D12 implementation of
the same 71-block Swin/ViT network. Its tag `0.08` reports about `24.4 ms` for
the network at `1920x1080` on an RX 9070 XT, with about `36–37 FPS` in Stellar
Blade and approximately `42 dB` PSNR against its exact reconstructed chain.
The repository also records the optimization progression from about `186 ms`
to `24.4 ms`, with the largest steps coming from fused QKV/normalization,
packed ViT/C512 paths, FP8 residual streams, reduced dispatch count, and
finally C32 FFN fusion into the attention prologue. This is the closest public
analogue to the backend problem we have, and it validates the order of work:
fusion and physical layout first, quantization as part of the fused kernel,
then dispatch/scheduling cleanup. It does not prove that the same timings are
possible on our RTX 5070 Ti or at our stereo eye resolution.

Sources: [AMD project README and status](https://github.com/lmxxf/dlss5-on-amd-9070xt-porting),
[optimization changelog](https://github.com/lmxxf/dlss5-on-amd-9070xt-porting#changelog),
[isolated-kernel profiling commit](https://github.com/lmxxf/dlss5-on-amd-9070xt-porting/commit/02ad50abb65dd4ce0341a439a5d5fbbdda39e214).

The project's newer runtime-design discussion is even closer to our local
measurements: it identifies memory round-trips, VGPR pressure, insufficient
fusion, and API synchronization as the practical bottlenecks, and proposes
modular fused FP8 GEMM/attention kernels plus a graph-level IR and explicit
zero-copy interop. That is consistent with the local result that a single
fused family kernel is useful while a 71-block eager schedule is not. It is a
design corroboration, not a ready-made implementation for OpenNR.

Source: [DLSS-NR-on-AMD runtime modularization RFC](https://github.com/danielblnc/DLSS-NR-on-AMD/issues/113).

### New independent-backend reference: NR-B580

The newest useful independent-backend lead is
[`gggz114514-oss/dlss5nr-b580`](https://github.com/gggz114514-oss/dlss5nr-b580).
It documents an independently replayed full network on an Intel Arc B580,
using a fixed RTX 4060 reference, exact physical layouts, explicit native
matrix accumulation/rounding, and a sequence of fused Triton kernels. Its
published fast-path comparison is approximately `3.57 ms` on the reference
RTX 4060 and `22.14 ms` on the B580 for a `256x256` input, with the latter
still not matching the reference. The repository is a research source
snapshot: it does not ship the NVIDIA DLL, CUBIN, weights, or captures, and it
does not establish a full-size 1080p or VR result.

This is relevant to our implementation in two ways. First, its recovered
arithmetic confirms that the exact FP8 boundaries, half-FMA order, window
layout, and separate C64/C128/C256/C512 branch structures matter more than
the nominal layer names. Second, its fast path uses the same type of changes
we are testing—streaming branch MLPs, direct QKV/window packing, fewer
intermediate tensors, and larger fused kernels. I cloned the source into the
external research area for inspection only; no third-party source or binary
was copied into OpenNR and no public license was assumed.

Sources: [NR-B580 overview](https://github.com/gggz114514-oss/dlss5nr-b580),
[reconstruction method](https://github.com/gggz114514-oss/dlss5nr-b580/blob/main/docs/01-reconstruction.md),
[numerics and layouts](https://github.com/gggz114514-oss/dlss5nr-b580/blob/main/docs/03-numerics-and-layouts.md),
[milestone timings](https://github.com/gggz114514-oss/dlss5nr-b580/blob/main/docs/05-milestone.md).

### Local transfer test: direct window packing

The first local transfer of the NR-B580 layout idea was tested on the same
full-eye Skyrim row used by the C32 baseline (`2496x2688`, frame 13, eye 0).
The new Triton probe projects the C32 Q/K/V values directly into
`[window,64,32]` storage, so the attention kernel does not first read a
row-major Q/K/V tensor and then remap it into 8x8 windows. With the best tested
`BLOCK_M=64` configuration, attention fell from `7.733 ms` to `6.076 ms`
(`1.273x`, or about `21.4%` lower). The complete packed C32 block measured
`9.342 ms`, versus `11.037 ms` for the earlier row-major complete-block
probe (`1.18x`, or about `15.3%` lower). The local eager direct-FP8 control
comparison remained `0.000245` MAE for the packed output.

This is the clearest local evidence so far that the public reconstruction's
physical layout choices transfer to our RTX 5070 Ti. It is also a useful
warning about scope: `BLOCK_M=32` erased the gain (`8.720 ms` packed versus
`8.633 ms` row-major attention), the packed path still allocates three large
intermediate tensors, and this is only one of the 71 logical blocks. The
experiment validates direct packing as a building block for a fused executor;
it does not make the full white-box graph VR-ready or establish native
NVIDIA parity.

Artifact: [`out/native_style_c32_packed_probe_full_20260912/result.json`](../out/native_style_c32_packed_probe_full_20260912/result.json).
The reusable probe is
[`tools/probe_native_style_c32_packed_cuda.py`](../tools/probe_native_style_c32_packed_cuda.py).

As a second C32 variant, the probe fused the C32 MLP and QKV projection into
the same per-window publication kernel, removing the full-frame MLP write/read
between those stages. With MLP `BLOCK_M=16` and attention `BLOCK_M=64`, the
fused MLP+QKV+attention path measured about `9.3 ms` versus `9.35 ms` for the
separate packed block (`~1.00x`). Its eager-control drift was unchanged at
`0.000245`. A stricter one-window kernel that kept the MLP, QKV, normalization,
attention, output projection, and residual in one program measured `9.499 ms`
at the full eye, about `1.6%` slower than the split packed block; the same
kernel was neutral on a `256x256` crop. The small MLP+QKV improvement and the
negative whole-window result mean that eliminating boundaries alone does not
reproduce the public runtime's large gain: attention tiling, register/shared
memory staging, output projection, workspace reuse, and the exact hardware
schedule must be designed together.

Both fused variants preserved the same `0.000245` eager-control MAE. Their
full-eye timings are recorded in
[`out/native_style_c32_window_fused_probe_full_20260912/result.json`](../out/native_style_c32_window_fused_probe_full_20260912/result.json).

The same transfer was then applied to the first pooled C64 encoder block on
the same full-eye row. The C64 stage is `624x672` (`419,328` tokens, `6,552`
windows) and has two 32-wide attention heads. At `BLOCK_M=64`, row-major
attention measured `1.399 ms` and direct-packed attention measured `0.937 ms`
(`1.493x`). The complete C64 block measured `1.518 ms`, versus `1.970 ms`
for the matched row-major block (`1.298x`, or about `22.9%` lower). The
packed-versus-row-major output difference was exactly zero in this run; its
MAE against the local eager direct-FP8 control was `0.000454`, matching the
existing corrected C64 control. With `BLOCK_M=32`, the complete-block gain
fell to only `1.071x`, again showing that the physical layout and tile shape
must be tuned together.

If the measured C32 and C64 complete-block ratios were applied optimistically
to every corresponding row in the representative schedule table above, the
`~168.3 ms` block-core estimate would fall only to about `154.5 ms` per eye
(`~309 ms` serial stereo). That is an extrapolation, not a benchmark, but it
quantifies why two successful family optimizations are not enough: the global,
split, decoder, transition, and workspace costs still dominate the distance to
the VR budget.

Artifacts: [`out/native_style_c64_packed_probe_full_20260912/result.json`](../out/native_style_c64_packed_probe_full_20260912/result.json) and
[`tools/probe_native_style_c64_packed_cuda.py`](../tools/probe_native_style_c64_packed_cuda.py).

### Same-size independent white-box anchor

The C32 packed probe was also repeated at the aggressive native `33%` work
surface (`824x887` nominally). Because the local Triton window kernel requires
8-row alignment, the independent probe used the nearest valid `824x880`
top-left feature extent (`725,120` tokens). On the same RTX 5070 Ti it measured
`1.058 ms` for one complete C32 block per eye, or about `2.12 ms` for that one
block across stereo. The native Feature 18 ladder's complete 33% network was
`4.674 ms` for both eyes. This is not an apples-to-apples quality comparison:
the white-box probe is one block and the native number is the entire network,
and the local probe used the available Triton environment (`torch 2.8.0`,
CUDA 12.9) rather than the earlier reference environment. It is nevertheless
a useful order-of-magnitude warning: at the native reduced work surface, one
independently fused C32 block already consumes roughly half of the native
network budget. Repeating that block family and then paying for C64/C128,
global attention, decoder, transitions, and stereo would not meet the native
number without more aggressive cross-block fusion, block reduction, or a
smaller student.

The local result is
[`out/native_style_c32_packed_probe_33pct_20260912/result.json`](../out/native_style_c32_packed_probe_33pct_20260912/result.json).
Its `0.0002643` packed-vs-eager MAE is still only a local recovered-graph
control, not native NVIDIA parity.

The next test applied the same transformation to the four-head C128 encoder
block. Here the result is not a useful speed win. At the existing
`BLOCK_M=32` configuration, row-major attention measured `0.832 ms`, while
packed attention measured `1.108 ms`; the complete block moved from `1.779 ms`
to `2.082 ms`. A `BLOCK_M=16` retry was effectively neutral (`1.803 ms` versus
`1.791 ms` for the complete block), and a `BLOCK_M=64` retry also ended up
effectively neutral (`16.824 ms` versus `16.736 ms`) while producing a much
less stable/slower attention subpath. The packed and row-major outputs were
exactly equal in all three tested configurations.

This is important evidence against blindly applying one NVIDIA-style layout
to every width. C32 and C64 benefit because their packed kernels fit the
available register/occupancy balance on this GPU; the wider four-head C128
kernel pays for the larger live working set. C128 therefore needs a different
split or fusion boundary—likely per-head streaming or a smaller tile—not the
same `[window,64,C]` materialization used by the lower-width families.

Artifact: [`out/native_style_c128_packed_probe_full_20260912/result.json`](../out/native_style_c128_packed_probe_full_20260912/result.json).
The `BLOCK_M=64` control is preserved separately at
`out/native_style_c128_packed_probe_full_bm64_20260912/result.json`.

### Native-runtime speed and reduced-resolution mode

Another current RTX 5070 Ti measurement is useful as a target calibration.
The `DLSS5-NeuralScreen` technical log reports approximately `16.6 ms` for a
full 4K desktop NGX evaluation, and approximately `2.9`, `4.6`, and `7.1 ms`
when the native runtime is explicitly fed `1280x720`, `1920x1080`, and
`2560x1440` work frames. Its matched-residual reduced-resolution mode reports
roughly `71.9 FPS` end to end versus `47.9 FPS` for its full-resolution desktop
mode in the cited test. This is a native-NGX wrapper, not an independent
reimplementation, but it confirms that a resolution reduction only buys
speed when the network actually receives the smaller frame.

Source: [NeuralScreen technical measurements](https://github.com/perseval-BLR/DLSS5-NeuralScreen/blob/main/TECHNICAL.md).

### Local native Feature 18 resolution ladder

To separate the network-size lever from the public desktop measurements, an
isolated benchmark was run against the same local `310.8.0.0` native runtime,
the same RTX 5070 Ti, and a preserved full-eye Skyrim frame. The 100% point is
the existing full-eye contract (`2496x2688` color and `1664x1792` guides). The
reduced points use the renderer's network dimensions for both the physical
input and output textures while retaining the full native guide dimensions.
The logical NGX input size was also set to the guide dimensions, matching the
renderer call in `Renderer.cpp`. Each point has 20 warm-up evaluations and 40
measured evaluations per stereo pair.

| Model scale | Network dimensions | Guide dimensions | Pair GPU median / p95 | Pair wall median / p95 | Relative wall speed |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100% | `2496x2688` | `1664x1792` | `23.160 / 23.199 ms` | `23.913 / 24.273 ms` | `1.00x` |
| 90% | `2246x2419` | `1664x1792` | `19.298 / 19.345 ms` | `20.110 / 20.539 ms` | `1.19x` |
| 85% | `2122x2285` | `1664x1792` | `17.428 / 17.470 ms` | `18.172 / 18.503 ms` | `1.32x` |
| 75% | `1872x2016` | `1664x1792` | `13.662 / 13.689 ms` | `14.377 / 14.650 ms` | `1.66x` |
| 50% | `1248x1344` | `1664x1792` | `6.936 / 6.950 ms` | `7.542 / 7.721 ms` | `3.17x` |
| 33% | `824x887` | `1664x1792` | `4.674 / 4.714 ms` | `5.341 / 5.453 ms` | `4.48x` |

All six scales completed `120` native evaluations without a runtime error, and
the saved outputs were nontrivial rather than pass-through. The benchmark
does not include the D3D11 model-input downsample, the full-eye output resolve,
or live renderer/compositor synchronization, so the reduced values are a
network-cost lower bound for the actual in-game reduced-resolution path. They
are not a claim that the small raw output is itself a valid full-eye Skyrim
image.

The result is directly relevant to the independent white-box plan. Native
Feature 18 obtains most of its practical speed by running a fused, specialized
network over a smaller work surface. The full-resolution native pass is already
about `24 ms` for sequential stereo on this machine; a 33% network pass is
about `5.4 ms` wall for both eyes before the surrounding resolve work. This is
the first local calibration that gives the independent backend a realistic
speed target. It also narrows the experiment: a white-box implementation that
only matches the full-resolution graph but remains unfused will not approach
the target, while a reduced-resolution clone must match both the fused kernels
and the renderer's downsample/resolve contract.

The generated configs, hashes, timings, and outputs for the corrected renderer
contract are preserved under
[`out/native_teacher_resolution_renderer_contract_20260912`](../out/native_teacher_resolution_renderer_contract_20260912),
with the machine-readable summary in
[`summary.json`](../out/native_teacher_resolution_renderer_contract_20260912/summary.json).
The preparation and summarization tools are
[`tools/prepare_native_teacher_resolution_study.py`](../tools/prepare_native_teacher_resolution_study.py)
and
[`tools/summarize_native_teacher_resolution_study.py`](../tools/summarize_native_teacher_resolution_study.py).

### Generic fixed-shape compilation check

The next bounded check used the same real test eye, the same recovered logical
weights, direct CUDA E4M3 activation boundaries, and the aggressive 33% input
scale. The input was `824x887`; the recovered graph's vendor-aligned network
extent was `832x896`. This isolates the question “can a generic fixed-shape
compiler turn the existing graph into the kind of low-launch-count executor
that the native runtime uses?”

The eager full graph completed at `897.45 ms` median per eye (`900.28 ms`
p95) after a `1084.36 ms` first call. Peak allocated CUDA memory was about
`1.05 GB`. `torch.compile(mode="reduce-overhead", fullgraph=False,
dynamic=False)` constructed its wrapper in `1.85 s`, but the first compiled
invocation spent approximately eight minutes in graph capture/code generation
and then failed with `OverflowError: Python int too large to convert to C long`.
No compiled steady-state timing was produced.

The same error reproduced at a much smaller fixed `320x320` network extent,
and it also reproduced when the recovered bitwise E4M3 implementation was used
instead of direct CUDA float8 casts. A block-only compile of the first C32
window path failed with the same exception as well. That narrows the result:
the current failure is not simply “the full frame is too large” or “Inductor
does not support the float8 cast”; this graph's dynamic Python/shape/layout
path is not currently a usable generic-compiler boundary.

Results:
[`out/whitebox_eager_33pct_20260912/result.json`](../out/whitebox_eager_33pct_20260912/result.json)
and
[`out/whitebox_compile_33pct_20260912/result.json`](../out/whitebox_compile_33pct_20260912/result.json).
The small-shape and block-only failures are recorded in
[`out/whitebox_compile_10pct_20260912/result.json`](../out/whitebox_compile_10pct_20260912/result.json)
and
[`out/whitebox_block_compile_bitwise_10pct_20260912/result.json`](../out/whitebox_block_compile_bitwise_10pct_20260912/result.json).
The reusable probe is
[`tools/benchmark_whitebox_compile_resolution.py`](../tools/benchmark_whitebox_compile_resolution.py).
The block-only companion is
[`tools/benchmark_whitebox_block_compile.py`](../tools/benchmark_whitebox_block_compile.py).

This is a practical negative result for the generic-compiler route, not a
mathematical impossibility result for a hand-written backend. It shows that
the current Python graph is too branchy/large for a useful one-shot compile at
the target shape, and that `torch.compile` cannot currently serve as the
missing NVIDIA-style runtime. A custom backend would need to lower the
known block families explicitly, keep workspace and layout decisions outside
the Python graph, and compile/fuse a bounded schedule rather than submit all
71 blocks as one generic program.

### Fixed-shape ONNX/TensorRT ceiling check

I then tested the last generic deployment path against a much smaller fixed
shape: the same recovered weights and graph at `320x320` (`10%` of the
full-eye work surface), with the E4M3 publication boundaries removed so this
would be a favorable FP16/TensorRT ceiling probe. The legacy ONNX exporter did
eventually succeed, but only after `528.8 s` of export time. The resulting
static file was `300,882,670` bytes and contained `101,403` primitive nodes and
`6,552` initializers. The ONNX checker passed, but its output dimensions were
still represented by inferred/symbolic reshape dimensions rather than a clean
fully-static output contract.

The largest node classes were `32,968` casts, `15,788` constants, `11,673`
adds, `11,530` gathers, `7,987` multiplies, and `6,413` matmuls. This is the
mechanical signature of tracing the Python reference (including bit/layout
helpers), not a compact representation of the recovered 71-block schedule.

TensorRT `10.13.3.9` parsed the graph and entered engine build/tactic
selection, but emitted no engine during a bounded observation window of more
than ten minutes. The builder reached about `9.48 GB` of private host memory
while the output directory remained empty, so I terminated that one builder
process to avoid an unbounded compiler run. No game, native DLL, or packaged
runtime was touched.

As a control for “maybe optimization level 5 is the problem,” I repeated the
build with TensorRT builder optimization level `0` and a `2 GiB` workspace.
That attempt also emitted no engine and reached about `13.83 GB` of private
host memory within several minutes. It was terminated under the same guard.
Therefore the negative result is not specific to exhaustive level-5 tactic
search.

This is stronger evidence that generic ONNX/TensorRT cannot recover the
vendor runtime from the current Python graph at useful engineering cost. The
failure is not a quality comparison and does not prove that TensorRT could
never build the graph with a different decomposition. It does show that the
graph is being presented at the wrong abstraction level: a tiny test surface
already expands the 71 logical blocks into over one hundred thousand nodes,
whereas the public native investigations describe a small inventory of fused
kernel families. A full-eye export would be larger and slower, not a sensible
next step.

Artifacts:
[`out/whitebox_onnx_10pct_20260912/export_manifest.json`](../out/whitebox_onnx_10pct_20260912/export_manifest.json),
[`whitebox_fp16_graph_320x320.onnx`](../out/whitebox_onnx_10pct_20260912/whitebox_fp16_graph_320x320.onnx),
and
[`out/whitebox_trt_10pct_20260912/build_result.json`](../out/whitebox_trt_10pct_20260912/build_result.json).
The level-0 control is recorded in
[`out/whitebox_trt_10pct_opt0_20260912/build_result.json`](../out/whitebox_trt_10pct_opt0_20260912/build_result.json).
The existing export and TensorRT builder helpers are
[`tools/export_whitebox_onnx.py`](../tools/export_whitebox_onnx.py) and
[`tools/build_semantic_joint_quantized_engine.py`](../tools/build_semantic_joint_quantized_engine.py).

The only dependency change was to the isolated research environment used for
export: `onnx 1.22.0` was installed, with `numpy` restored to the environment's
previous `1.26.4` version and `ml-dtypes` pinned to `0.5.4` for compatibility.
This does not alter OpenNR, Skyrim, or the native Feature 18 installation.

### Fresh search: native offload is an escape hatch, not an independent backend

A fresh search on `2026-09-12` found a new adjacent project,
[`Neural-coprocessor`](https://github.com/maohgad-web/Neural-coprocessor), that
drives the native DLSS-NR path on a second NVIDIA GPU while the first GPU
renders the game. Its documentation reports dual-RTX measurements and
describes keeping the result on the second card's display to avoid a copy back
over PCIe. This can reduce the render-card frame-time hit, but it requires a
second GPU/display arrangement and still executes the native NGX runtime. It
does not help a single-GPU SkyrimVR headset path and does not validate an
independent white-box implementation.

The same search found
[`NIGos/dlss5-bridge`](https://github.com/NIGos/dlss5-bridge), which mirrors
real DLSS calls into a private D3D12 device for D3D11/Vulkan games, and newer
one-click/sidecar wrappers that package the same native add-on contract. These
are useful references for a future isolated native-contract experiment, but
they should not replace the protected OpenNR Feature 18 route or be treated as
white-box kernel work. No new public DLSSNR-specific LoRA or small independent
checkpoint was found in this pass; the visible LoRA-oriented projects use
native DLSS output as training/media input and do not change the inference
schedule.

Sources: [native second-GPU coprocessor](https://github.com/maohgad-web/Neural-coprocessor),
[D3D11/Vulkan native bridge](https://github.com/NIGos/dlss5-bridge),
[DLSS5 one-click wrapper](https://github.com/faisalkindi/DLSS5oneclick).

A separate contract matrix against the same `310.8` family reports that
`DLSSNR.Style` values `0`, `1`, and `2` produce distinct deterministic
outputs, with style `3` aliasing style `2`, while changing
`DLSSNR.Hint.Render.Preset` did not change the tested checksum. It also found
that the live scaling value is supplied through the runtime-parameter
callback, not merely by setting the ordinary parameter. For OpenNR this means
styles should be treated as separate teacher targets or controls, but preset
knobs should not be assumed to change speed or network structure without a
measured contract test.

Source: [DLSSNR private-contract matrix](https://github.com/kibblerz/DLSS5-Reshade-AIO/blob/main/lab/PRIVATE-CONTRACT-FINDINGS.md).

### Resolution and cadence controls: relevant, but not a substitute for fusion

Community tooling around the recovered route exposes two structural controls:
run the neural pass every second or third frame, and reduce the model's work
area. Its README describes approximate `75%` and `50%` work-area modes as
roughly half and quarter cost respectively, while also warning that the model
and runtime are external/closed components. This is useful evidence for an
OpenNR experiment, not a guaranteed scaling law.

Our own whole-graph check on the existing Skyrim test row measured the eager
recovered graph at `2330.6 ms` at full internal resolution, `1597.3 ms` at
`75%`, and `1066.3 ms` at `50%`. The `50%` path was only `2.19x` faster because
the eager executor's launch, conversion, and allocation overheads remain. A
fused runtime could scale better, but this confirms that work-area reduction
must be paired with a compiled/fused executor and must be judged visually.

Source: [DLSS5-Autopilot route and work-area notes](https://github.com/Kizzuwatnaa/DLSS5-Autopilot/blob/main/README.md).

### Distillation and LoRA search result

The public material reviewed for this report exposes recovered weights,
runtime wrappers, and kernel work, but no public DLSSNR-specific LoRA or
small student checkpoint that we can adopt as a known-good high-speed model.
That absence is informative: LoRA changes weights, not the 71-block launch
schedule, and therefore would not address the dominant runtime problem by
itself. A student remains viable, but it must be a separately designed,
smaller graph trained against the recovered output and then validated against
native/temporal/stereo gates. It should not be treated as a drop-in compressed
version of the white-box network.

### Official NVIDIA timing: useful target, not an apples-to-apples gate

TechSpot's first independent RTX50-series measurements estimate the official
DLSS5 increment at about `7.8 ms` at `1440p` and `17.0 ms` at `4K` on an RTX
5070 Ti. The article says the cost follows output pixels much more than input
render resolution, because the official pass runs after upscaling. Those
numbers are useful for the order of magnitude we should aim at, but they are
not a per-eye SkyrimVR contract: the game, driver path, output dimensions,
guides, and stereo scheduling differ. They also show that “native speed” is
not zero-cost; even the official implementation is a substantial fixed frame
budget on this class of GPU.

Source: [TechSpot DLSS5 performance measurements](https://www.techspot.com/article/3170-real-dlss-5-performance/),
especially the measured timing table and the output-resolution discussion.

NVIDIA's own ADLR project page now makes the training/runtime boundary more
explicit: DLSS5 is described as a one-step pixel-space diffusion model whose
inference is conditioned on the current rendered frame, motion vectors,
carried temporal state, and artistic-direction values, with renderer-derived
consistency supervision during training. It is causal, deterministic, and
designed around a strict per-frame budget. This supports the conclusion that
the recovered weights are only one part of the product: exact conditioning,
state handling, and specialized execution are also part of the runtime
contract. It also explains why a generic student trained only on static RGB
targets is not a direct substitute for the native system.

Source: [NVIDIA ADLR DLSS5: Generative Neural Rendering](https://research.nvidia.com/labs/adlr/DLSS5/).

### MLX-DLSS: fidelity and portability evidence, not a runtime solution

MLX-DLSS reports `0.004–0.005 MAE` against NVIDIA on `1152–1408`-pixel game
renders and `18.4–20.1` input frames/s for a temporal video sample on an M2
Max. The README says that the video number includes startup, motion, decode,
and encode. This is relevant because it confirms that logical weight recovery
can produce a close portable reference, but it does not tell us how to meet a
VR frame budget on the RTX. It is therefore a quality/oracle reference, not a
kernel backend to adopt.

Source: [MLX-DLSS accuracy and speed measurements](https://github.com/iamwavecut/MLX-DLSS#accuracy-and-speed).

### DLSS5 Video Player: native-runtime comparison only

The video player reports about `8.4 ms` per `1080p` frame on an RTX 5090, but
its own README makes clear that its neural path uses the NVIDIA/NGX runtime
(with modified third-party components). This is useful evidence that a small
host wrapper need not add seconds of overhead, but it is not evidence that an
independent reimplementation can reproduce that number. It should not be
used as a student or white-box benchmark.

Source: [DLSS5 Video Player limitations and timing](https://github.com/2600th/dlss5-video-player#limits-to-know).

## Decision

The pasted material strengthens the native-style backend route. It does not
justify another round of broad Skyrim captures, LoRA training, or ordinary
weight-only quantization. The current white-box weights are already sufficient
to expose a measurable fused-kernel opportunity; the missing pieces are
compiled execution, fixed physical layouts, attention fusion, workspace
reuse, and the host scheduling contract.

The next bounded experiment is:

1. Keep the native resolution ladder as the speed reference: `100%` is the
   full-eye baseline, while `50%` and `33%` are the only tested network sizes
   that leave a plausible 90-Hz stereo budget before surrounding work.
2. If independent white-box work continues, measure the fused schedule at the
   same `33%` and `50%` model dimensions; a full-resolution-only schedule is
   not the relevant target for this speed question.
3. Keep the C32 result as a backend smoke test and a full-resolution cost
   anchor, not a promoted component.
4. Keep the corrected C64/C128/C256/C512 results as backend proofs, while
   treating their attention-tail drift as unresolved quality work rather than
   accepting timing alone.
5. Keep direct window packing as a family-specific candidate: it is a measured
   win for the tested C32/C64 configurations, neutral or slower for the tested
   C128 configurations, and must not be applied globally without a per-family
   occupancy/parity check.
6. Use the measured family ladder to build a schedule for the remaining
   repeated blocks, global core, decoder, and last full-resolution endpoint.
   The C256 split is the current template for handling resource limits.
7. Measure steady-state GPU events and launch count separately from one-time
   compilation, allocation, and host overhead.
8. Only after the remaining schedule is measured at the actual eye resolution
   should we compare the total against the native/runtime timing target.
9. Keep full-eye exact parity, temporal state, stereo, Feature 18 resource
   identity, and live VR frame-budget acceptance as separate gates.

No further data collection is required for this speed branch. A small native
runtime-contract capture may eventually be useful for validating launch and
buffer layouts, but more training images cannot repair an unfused executor.

## Explicit limits

- The local CUDA kernel uses Triton tensor-core dots and a recovered E4M3
  helper; it is not NVIDIA's PTX and does not claim bit identity with the DLL.
- The comparison control is the local direct-FP8 eager subgraph, not the
  native NVIDIA output. The low MAE is a backend-control result only.
- The complete-block measurement covers only `block0.layer0`. It cannot be
  multiplied by 71 to predict total latency because channel width, spatial
  scale, attention, global ViT blocks, decoder work, and memory reuse vary by
  stage.
- The result is offline model work. It is not Skyrim integration, temporal
  validation, stereo validation, headset validation, or a live frame-budget
  result.
