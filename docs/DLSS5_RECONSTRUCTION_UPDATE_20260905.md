# DLSS 5 reconstruction and teacher-harness watch — 2026-09-05

This note reviews the new reverse-engineering reports supplied on September 5,
2026 and separates source-backed observations from researcher claims. It does not
install, execute, redistribute, or vendor proprietary NVIDIA or closed AMD
artifacts.

## Executive decision

The update is useful, but it does not justify replacing the current teacher path,
promoting a recovered teacher graph, or changing the production MGO profile.

The highest-value addition is the public `DLSSCamDemo` source tree. It provides a
possible future isolated black-box teacher harness for generating controlled
RGB/guide/output pairs from video, with same-frame A/B capture and saved guide
resources. Its guides are estimated from image history rather than Skyrim's native
Feature 18 resources, and its working path still depends on an unofficial or
community-provided NR runtime. It is therefore an auxiliary pretraining and
diagnostic route, not a replacement for the exact Skyrim capture contract.

The independent reconstruction report is a stronger architecture lead than the
earlier resource inventory. Its reported 153 tensor payloads, approximately
131.9M active parameters, multiscale Swin/ViT/Swin core, local-window attention,
FP8 E4M3 packing, and roughly 99% intermediate agreement are all self-reported
and incomplete. They are useful priors for a future ablation and for interpreting
FP8 behavior, but there is still no public full graph, portable checkpoint, or
end-to-end independent output.

The AMD issue is now evidence that the closed backend can execute on gfx1200,
not merely initialize. The reported RX 9060 XT result still takes approximately
62–63 ms per 1080p neural job, and Async changes scheduling rather than neural
execution time. That is not a real-time stereo VR path and does not provide a
trainable checkpoint for OpenNR-VR.

## Finding 1: partial numerical reconstruction

The supplied Reddit report says an independent reconstruction has reached several
controlled intermediate checkpoints with approximately 99% numerical agreement
against NVIDIA reference execution. It describes the current hypothesis as:

```text
RGBA
  -> multiscale front end
  -> 8 x 512-channel Swin blocks
  -> 8 x 1024-channel ViT blocks
  -> 8 x 512-channel Swin blocks
  -> multiscale reconstruction
  -> RGBA
```

The report also names a representative 512-channel block with 16 heads, 32
dimensions per head, 8x8 local windows, L2-normalized Q/K, scaled-cosine
attention, per-head scaling, and an attention-bias table. It reports FP8 E4M3
packed weights, Tensor Core-oriented layouts, fused QKV/attention/projection/FFN
operations, permutations, masks, normalization vectors, and multiscale
transitions.

These claims are materially more specific than the previous DLL/resource
inventory, but the post explicitly says that the FFNs, transitions, front end,
and reconstruction are unfinished. The approximately 99% number applies to
controlled intermediate checkpoints, not to a complete image. The reported
approximately 92 ms warm pass on an RTX 2070 Mobile is also a researcher
measurement, not a target-hardware benchmark.

The most useful project implications are:

1. Retain the current compact spatial student as the measured control. Add a
   separate multiscale/local-attention ablation only after the capture contract
   and evaluation split are stable.
2. Treat FP8 E4M3 as a clue about the teacher's internal representation, not as
   evidence that our current FP8 TensorRT export should be promoted. Our existing
   MatMul-only FP8 path passed parity but supplied no material speed gain over
   FP16.
3. Keep the spatial-first then temporal plan. The reported image-to-image test
   suggests that a first spatial student can learn useful appearance behavior
   without reproducing the full NGX lifecycle; it does not remove the need for
   native motion, reset, history, and stereo validation for the Skyrim runtime.
4. Require a public block implementation, reproducible intermediate tensors, or a
   complete forward pass before attempting to instantiate a 131.9M-parameter
   teacher-shaped model.

## Finding 2: AMD gfx1200 execution

AMD issue #49 reports an RX 9060 XT 16 GB on Windows 11 and gfx1200 with HIP,
D3D12/FSR hooks, zero-copy input/output interop, and successful neural jobs. The
reported 1920x1080 test receives a 1920x1080 color buffer and approximately
1129x635 motion and depth buffers. Warm jobs are reported around 62–63 ms, with
initial jobs ranging from 46–78 ms. The issue's output self-check reports about
0.1% zero bytes as healthy.

The same report says Inline waits for the same-frame neural result, while Async
uses a residual from an earlier frame. Async changes synchronization behavior but
does not reduce the approximately 62–63 ms neural execution time. The evidence is
stronger than the earlier gfx1200 kernel-failure report, but it is still a
first-party user issue on a closed experimental backend, not an independently
audited benchmark.

For OpenNR-VR this is useful as a runtime-contract and performance observation:

- the port can now be treated as a possible future AMD execution research target;
- its color/motion/depth dimensions are useful for comparing guide contracts;
- its current timing rules it out as a real-time stereo VR backend;
- it does not justify installing its setup executable, proxy, generated weight
  file, or DLL into MGO, Lentus, or the known-good teacher system.

## Finding 3: DLSSCamDemo teacher harness

`jpneagle/dlss5-webcam-demo` is public source and describes a D3D12 webcam path:

```text
webcam BGRA
  -> temporal guide generator
       (estimated motion, depth proxy, bias mask)
  -> linear FP16 color + RG16F motion + R32 depth + R8 bias
  -> NGX DLSS / Feature 18 consumer
  -> same-frame A/B output and capture
```

The repository contains no proprietary binaries. Its README says that the user
must supply the NVIDIA SDK, ONNX Runtime, ReShade, an NR runtime, and one NR
consumer. It exposes the input, motion, depth, bias, and final output views and
can save still sets. It also documents a same-frame side-by-side comparison and
configurable input/output resolution, which are valuable properties for controlled
teacher-query experiments.

The important limitation is guide provenance. The harness estimates motion and a
depth proxy from ordinary camera frames. These resources can make a controlled
black-box teacher dataset, but they are not equivalent to Skyrim's native
`DLSSNR.Depth` and `DLSSNR.MVec` resources. The source also says that the working
path relies on an NR consumer/bridge and that direct standalone Feature 18
initialization without the compatibility route fails with `0xBAD00002`.

The safe interpretation is:

- **High value for future auxiliary pretraining:** generate diverse image-to-image
  teacher pairs and test whether a student learns appearance priors before native
  Skyrim fine-tuning.
- **High value for black-box diagnostics:** vary input resolution, controls, pass
  count, and same-frame A/B captures while retaining the exact generated guides.
- **Low value as final Skyrim supervision:** approximate guides, unknown runtime
  preprocessing, and the inability to isolate ordinary DLSS-SR from the NR result
  make it unsuitable for mixing directly into the native master split.

If this path is used later, its records must be stored under a separate dataset
identity with `source=external_teacher_harness`, `guide_provenance=estimated`,
`native_feature18=false`, and the exact runtime/consumer hashes. It must never be
silently merged into the native Skyrim train, validation, or test split.

## Changes to the project decision

No production code, teacher checkout, MGO profile, capture data, or runtime binary
was changed for this review. The existing temporal validator and disabled capture
template remain the correct immediate work. The next model-bearing work remains a
clean contiguous native temporal capture followed by a stateful student and
history/reset losses.

The external harness is now a separately gated future workstream:

```text
source-only harness review
  -> isolated authorized runtime
  -> captured guide/output manifest
  -> provenance and same-frame checks
  -> auxiliary spatial pretraining experiment
  -> native Skyrim fine-tuning
```

The architecture reconstruction is a watch item with these revisit gates:

1. published block code, weights, or intermediate tensors;
2. reproducible numerical agreement for a complete block and its FFN;
3. a complete forward pass without NGX evaluation;
4. a documented history/control/input contract;
5. end-to-end stereo timing on hardware relevant to our deployment.

## Sources checked

- [Independent DLSS 5 reconstruction report](https://www.reddit.com/r/radeon/comments/1w5wv5m/after_getting_dlss_5_neural_rendering_running_on/)
- [DLSS-NR-on-AMD issue #49](https://github.com/danielblnc/DLSS-NR-on-AMD/issues/49)
- [DLSSCamDemo repository](https://github.com/jpneagle/dlss5-webcam-demo)
- [DLSSCamDemo temporal-guide source](https://github.com/jpneagle/dlss5-webcam-demo/blob/master/src/TemporalGuides.cpp)
- [DLSSCamDemo Feature 18 backend source](https://github.com/jpneagle/dlss5-webcam-demo/blob/master/src/DLSSNRBackend.cpp)
- [Independent NVIDIA resource/architecture analysis](https://gist.github.com/madebyollin/55c703a34bf90962844edcd68d04e32e)
- [NVIDIA DLSS 5 research description](https://research.nvidia.com/labs/adlr/DLSS5/)

