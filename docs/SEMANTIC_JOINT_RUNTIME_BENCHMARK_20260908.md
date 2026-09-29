# Semantic joint-1200 inference runtime benchmark — 2026-09-08

## Executive result

The best current speed candidate is the isolated TensorRT engine built from the
frozen `seed812` joint update-1200 checkpoint at the 33% model surface:

- model surface: `887x824` per eye;
- native guide tensors retained at `672x624` per eye;
- FP16 TensorRT I/O, FP16 tactics, builder optimization level 5;
- numerical reset and steady-state comparison passed against the FP32 eager
  reference;
- synthetic GPU-resident sequential stereo: `17.058 ms` median,
  `17.683 ms` p95, `18.087 ms` p99;
- preserved full-resolution capture input: `17.008 ms` median,
  `17.564 ms` p95, `17.659 ms` p99 for the fixed TensorRT forward;
- native GPU preparation measured separately at `1.763 ms` for both eyes
  sequentially, giving a conservative model-plus-preparation estimate of
  approximately `18.770 ms` median before D3D interop, output resolve,
  compositor, game rendering, and headset acceptance.

The current native Feature 18 reference is approximately `24.157–24.423 ms`
for sequential stereo GPU work in the existing benchmark. The isolated engine
therefore has a meaningful speed margin, but this is not yet a live Skyrim VR
acceptance result. No Community Shaders DLL, MGO profile, or live capture
settings were changed.

A native D3D11/CUDA/TensorRT boundary probe also passed against the same
engine. It created a hardware D3D11 device, associated it with CUDA, registered
shared buffers, mapped/unmapped the buffers, executed the engine through
`enqueueV3`, ping-ponged the hidden/previous state, and verified finite output.
The probe measured `8.231 ms` steady median per eye (`8.847 ms` p95,
`8.957 ms` p99) and a separate `91.837 ms` first-reset/setup call. This is
stronger than a deserialize-only ABI check, but it still uses synthetic zero
inputs and is not a Skyrim render-path acceptance result.

## Frozen source and inference artifacts

The source checkpoint was frozen before export. Training-only state was removed
from the inference bundle; the causal parent and semantic head tensor contents
were preserved by digest in the bundle manifest. The engine is a separate
deployment artifact and does not replace the checkpoint or the training run.

| Artifact | Location | SHA-256 |
| --- | --- | --- |
| Source checkpoint | `C:\OpenNR\Training\semantic_parent_seed812_joint1200_20260908\best_all_cohorts.pt` | `a233c7bda73ffd1cbc5af268fbbdf01afcc9e3acad106effd29d88e1f498509` |
| Inference bundle | `C:\OpenNR\Inference\semantic_joint_seed812_update1200_20260908\bundle.pt` | `fa2f7c3626cef474f56ffe0d2d3632316cfb09d4acf0d785dda506a5d47ffe57` |
| 33% FP32-ONNX graph | `C:\OpenNR\Inference\semantic_joint_seed812_update1200_20260908\trt_33pct_824x887\semantic_joint_runtime.onnx` | `c65adf8ba2af8b0740ce9a2f0e8123fa8073250f77addaf38270f89adbfc448a` |
| 33% optimized FP16-I/O engine | `C:\OpenNR\Inference\semantic_joint_seed812_update1200_20260908\trt_33pct_824x887_fp16io_opt5\semantic_joint_fp16_io.engine` | `0fefafe6c12f91f72c2201b7ed0254233d86a66d618d79319ee1d2d8e4b41562` |
| Native TensorRT ABI probe | `C:\OpenNR\Inference\semantic_trt_cpp_probe.exe` | `321aad2efdaee83ee484b511bbb85f57f26a0a8f87142ab25bd08928d0964360` |
| Native D3D11/CUDA/TensorRT bridge probe | `C:\OpenNR\Inference\semantic_trt_d3d11_bridge_probe.exe` | compiled and passed against the engine |

The inference bundle manifest is at
`C:\OpenNR\Inference\semantic_joint_seed812_update1200_20260908\manifest.json`.
It records the removed optimizer and RNG state, the parent/head tensor
digests, and the reset contract. The full benchmark JSON files are kept beside
the bundle rather than being copied into the active game installation.

## Input and temporal contract

The actual capture contract is asymmetric by design:

| Tensor | Runtime shape | Meaning |
| --- | --- | --- |
| `rgb` | `[1,3,887,824]` | RGB/model surface after the renderer's reduced-resolution path |
| `guides` | `[1,5,672,624]` | native-resolution depth/motion guide tensor |
| `context` | `[1,8,96,96]` | native preprocessing context grid |
| `hidden` | `[1,64,111,103]` | causal per-eye recurrent state |
| `previous` | `[1,3,887,824]` | previous model-surface RGB |
| `prediction` | `[1,3,887,824]` | model output |

There is an independent state chain for each eye. A reset sets hidden state to
zero and previous RGB to the current RGB. The benchmark measures first-reset,
warm-reset, and steady temporal calls separately. It does not insert a hidden
reset between the two eyes of a stereo pair.

## Runtime measurements

All timings below are GPU timings for sequential stereo unless noted. They do
not include Skyrim rendering, D3D11/D3D12 interop, compositor scheduling, or
headset presentation.

| Candidate | Model surface | I/O and tactics | First reset | Steady median | p95 | p99 | Result |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| TensorRT 512 smoke test | `512x512` | FP32 I/O, FP16 tactics | `9.846 ms` | `10.026 ms` | `10.480 ms` | `10.666 ms` | Equivalence/runtime smoke pass |
| Exact 100% model | `2496x2688` | FP32 I/O, FP16 tactics | `140.659 ms` | `140.803 ms` | `149.772 ms` | `156.410 ms` | Too slow for the target |
| 50% model | `1248x1344` | FP32 I/O, FP16 tactics | `33.995 ms` | `34.182 ms` | `34.781 ms` | `35.243 ms` | Too slow for native comparison |
| 33% model | `887x824` | FP32 I/O, FP16 tactics | `23.123 ms` | `22.037 ms` | `23.034 ms` | `23.741 ms` | Slightly faster raw, but little margin |
| 33% optimized candidate | `887x824` | FP16 I/O, FP16 tactics, opt level 5 | `16.717 ms` | `17.058 ms` | `17.683 ms` | `18.087 ms` | Best current isolated candidate |
| 33% candidate on real capture inputs | `887x824` | FP16 I/O, FP16 tactics, opt level 5 | `17.437 ms` | `17.008 ms` | `17.564 ms` | `17.659 ms` | Capture-input forward pass |

The real-capture benchmark used preserved full-resolution color, depth, and
motion-vector files from
`C:\OpenNR_Captures_FullRes_Pilot_20260904\seq-1788564568291-1`. The native
guide/context preprocessing plus both model-surface resizes took `1.763 ms`
sequentially on the GPU. Adding that measured preparation cost to the forward
timing gives approximately `18.770 ms` median, `19.327 ms` p95, and
`19.421 ms` p99. This arithmetic is a planning estimate, not a live frame
measurement: interop and output resolve still have to be implemented and
measured.

The optimized candidate's reset/temporal state was finite for both eyes. The
numerical comparison against the FP32 eager reference used deterministic
inputs and passed the stated tolerances of mean absolute difference `<=0.002`
and maximum absolute difference `<=0.1`:

| Check | Mean absolute difference | Maximum absolute difference |
| --- | ---: | ---: |
| First prediction | `0.0002206` | `0.0017737` |
| Steady prediction | `0.0002191` | `0.0016700` |
| First hidden state | `0.0000118` | `0.0001017` |
| Steady hidden state | `0.0000175` | `0.0001699` |

The optimized synthetic benchmark recorded approximately `0.102 GiB` peak
PyTorch allocation and about `771 MiB` of total NVML-used-memory increase over
the benchmark's before/after sample. These are process/system observations,
not a final Skyrim VR frame-budget measurement.

## Native TensorRT ABI check

The isolated C++ probe loaded the installed TensorRT 10.13.3 runtime and
deserialized the optimized engine successfully. It reported the following
fixed contract:

```text
rgb          input  FP16 [1,3,887,824]
guides       input  FP16 [1,5,672,624]
context      input  FP16 [1,8,96,96]
hidden       input  FP16 [1,64,111,103]
previous     input  FP16 [1,3,887,824]
prediction   output FP16 [1,3,887,824]
next_hidden  output FP16 [1,64,111,103]
next_previous output FP16 [1,3,887,824]
```

This proves the serialized engine is consumable through a native TensorRT ABI.
The separate D3D11/CUDA bridge probe then passed the shared-buffer mapping and
causal ping-pong boundary as described above. It does not yet prove texture
resource format conversion, native guide/context preprocessing, output packing
back into the renderer, or live renderer integration.

## FP8 and NVFP4 feasibility

The RTX 5070 Ti reports compute capability 12.0, and the installed TensorRT
10.13 Python API exposes both `DataType.FP8` and `DataType.FP4`. NVIDIA's
TensorRT quantization documentation describes FP8 as an explicit Q/DQ format;
NVFP4 uses explicit Q/DQ with per-block scales and block size 16, and requires
dynamic activation quantization. This means neither precision is a safe
builder-only switch on the current FP16 engine.

The installed NVIDIA ModelOpt 0.41 stack exposes `FP8_DEFAULT_CFG` and
`NVFP4_DEFAULT_CFG` in its PyTorch quantization path. Its ordinary ONNX PTQ
entry point advertises `int8`, `int4`, and `fp8` modes, while the package also
contains a lower-level NVFP4 weight exporter. The practical order is:

1. build a separate FP8/Q-DQ candidate from the frozen bundle, keeping FP16
   input/output bindings and initially quantizing only convolution/linear
   heavy blocks;
2. calibrate with representative reset and steady temporal capture tensors;
3. compare prediction and hidden-state drift, then run long contiguous motion
   bursts and visual/stereo checks;
4. only if FP8 leaves insufficient margin, evaluate NVFP4 through the ModelOpt
   PyTorch path or another explicit Q/DQ export route, starting with a
   selective/blockwise candidate rather than quantizing every normalization,
   residual, resize, or state-update operation.

The first FP8 trial was actually attempted, not merely planned. ModelOpt
generated a 232-node FP8 Q/DQ graph from 22 capture-derived samples. TensorRT
parsed that graph, but the high-optimization-level build did not serialize: the
builder repeatedly reported unsupported FP8 reformats, unimplemented scalar
types, and fallback reformat assertions. The isolated builder was stopped after
the bounded attempt; no FP8 engine was accepted. The Q/DQ graph, calibration
archive, log, and candidate manifest remain under
`C:\OpenNR\Inference\semantic_joint_seed812_update1200_20260908\fp8_33pct_capture`.

NVFP4 was then tested as a narrower one-node weight-only candidate. The
installed ModelOpt NVFP4 exporter produced a valid explicit FP4E2M1 graph for
one `384x1152` DINOv2 MatMul with FP8 block scales and block size 16; all other
operations and all recurrent state tensors remained unchanged. TensorRT parsed
the graph but failed to serialize even this single quantized node with the same
`Unsupported data type FP8` cuTENSOR/reformat errors, plus packed-reformat and
unimplemented-scalar-type failures. The candidate graph and manifest remain
under
`C:\OpenNR\Inference\semantic_joint_seed812_update1200_20260908\nvfp4_33pct_selective_probe`.
This makes both FP8 and NVFP4 toolchain follow-ups rather than immediate speed
options in the current installed builder. More nodes must not be quantized into
this path until a compatible native FP4/FP8 build stack is available.

The unquantized 33% FP16-I/O engine remains the control. Any FP8 or NVFP4
engine that improves speed but fails temporal, stereo, or visual acceptance is
an optimization experiment, not a promoted runtime.

## Live integration status and next gates

No live integration has been attempted yet. The existing Feature 18/MGO route
and its single `CommunityShaders.dll` owner remain unchanged. The next isolated
implementation must provide:

- CUDA/D3D11 resource registration or a verified staging path for color,
  native guides, context, recurrent hidden state, and previous RGB;
- a per-eye CUDA stream and explicit synchronization with the renderer;
- FP16 input packing, TensorRT enqueue, FP16 output unpacking, and output
  resolve back to the renderer's D3D11 resource;
- exact reset, resize, and device-loss behavior;
- a fallback to the existing Feature 18 path until the new backend passes a
  live Skyrim/SteamVR test;
- warm steady-state and first-reset timing measured inside Skyrim at both eyes,
  followed by headset, stereo, audible, UI, deployment, and VR-budget checks.

Training and inference artifacts stayed separate. The saved training endpoint
was paused while the long TensorRT builds and capture-input tests used the
GPU; it was not overwritten, and the inference work can resume independently
from the frozen bundle.

## Source benchmark files

- [inference bundle manifest](C:/OpenNR/Inference/semantic_joint_seed812_update1200_20260908/manifest.json)
- [optimized synthetic benchmark](C:/OpenNR/Inference/semantic_joint_seed812_update1200_20260908/benchmark_tensorrt_fp16io_opt5_33pct_824x887_compare.json)
- [optimized preserved-capture benchmark](C:/OpenNR/Inference/semantic_joint_seed812_update1200_20260908/benchmark_tensorrt_fp16io_opt5_33pct_actual_capture_frame1_v2.json)
- [optimized TensorRT engine](C:/OpenNR/Inference/semantic_joint_seed812_update1200_20260908/trt_33pct_824x887_fp16io_opt5/semantic_joint_fp16_io.engine)
- [native TensorRT C++ probe source](../tools/semantic_trt_cpp_probe.cpp)
- [native D3D11/CUDA/TensorRT bridge probe source](../tools/semantic_trt_d3d11_bridge_probe.cpp)
- [selective NVFP4 candidate preparation tool](../tools/prepare_semantic_joint_nvfp4_onnx.py)
- [native runtime and baseline notes](LONG_TRAINING_AND_NATIVE_RUNTIME_20260905.md)
