# DLSS-NR-on-AMD extraction development — 2026-09-04

Status: high-value reverse-engineering lead; extraction evidence is credible but
the converted weight container and backend remain closed and unreproducible.
No OpenNR-VR source, MGO profile, or game installation was changed for this review.
Scope: informational research-and-development data only; this is not an install
recommendation, production dependency, teacher replacement, or distributable model source.

## Executive assessment

The AMD project is a materially stronger development than a normal compatibility
layer or injector update. Its first-party v0.2.9 release note explicitly says that
some `nvngx_dlssnr.dll` versions were not recognized by “the extractor.” A public
v0.2.10 issue also includes a user log stating `weights build from
nvngx_dlssnr.dll: ok` before the HIP kernels fail to load. Together these support
the existence of a DLL-to-AMD model-processing stage.

That does not yet prove that `dlssnr_on_amd_weights.bin` is a portable tensor
checkpoint. It could be a tensor-like container, a de-swizzled/quantized native
representation, or an intermediate format consumed only by the closed AMD
backend. No sample file, parser, tensor manifest, shape list, checksum, backend
source, or reproducible build is published.

The correct project classification is therefore:

- **Green — model extraction/conversion lead:** the first-party release wording
  makes this substantially more than “CUDA translated on AMD.”
- **Green — architecture corroboration:** AMD-side kernel names and the separate
  weight-build stage are consistent with the independent Swin/QKV/FFN analysis,
  but the kernel observations remain community-reported rather than maintainer-
  audited.
- **Amber — trainable-model opportunity:** worth monitoring and potentially
  sampling in an isolated lab if a safe, auditable artifact becomes available.
- **Red — usable checkpoint today:** no public `safetensors`, ONNX, PyTorch state
  dict, full graph, or end-to-end independent implementation is available.

## What is verified from first-party project material

- The repository README targets Windows 11, DirectX 12 games using FSR, and AMD
  Radeon RX 9000/RDNA4 hardware. It asks the user to supply their own
  `nvngx_dlssnr.dll` version 310.8.0.0. The author reports approximately 28 FPS at
  1080p on an RX 9070 XT and describes performance as work in progress.
- Alpha v0.2.9 says it fixed recognition of some `nvngx_dlssnr.dll` versions by
  “the extractor.” Alpha v0.2.10 fixes multi-GPU detection. v0.2.8 reports a 2%
  performance improvement and v0.2.7 reports a 30-FPS 1080p milestone on an RX
  9070 XT.
- The public branch is not the backend source: the current tree contains the
  README and `.github/FUNDING.yml`, and the release assets expose the setup
  executable plus GitHub-generated source archives. The v0.2.10 release asset is
  a 4.57 MB `dlssnr_on_amd_setup.exe` with published SHA-256
  `5a28d907bba471504c6c7be6901a4eb6610f46b4d86ecb23b0430ba8bf3fc5d5`; no
  `dlssnr_on_amd_weights.bin` is published as a release asset.
- The project’s own legal text says it contains no NVIDIA code or data and
  requires the user’s own legitimately obtained DLSS-NR DLL. This explains why
  the possible model artifact would be generated locally rather than shipped in
  the release.

## Community evidence and its limits

The strongest publicly visible corroboration is an open v0.2.10 issue from an RX
9060 XT tester. The attached log excerpt says `weights build from
nvngx_dlssnr.dll: ok`, then lists named HIP stages such as `img`, `enc0`–`enc3`,
`vit512a`, `head`, `rep1d`, `b31`–`b38`, `vit1d`, `dec0`–`dec3`, and `out`. The
same report says D3D12/FSR hooks, HIP initialization, GPU selection, and zero-copy
interop succeeded before all kernels failed with `invalid kernel file`. This is
useful evidence that the work reaches a model/kernel execution backend, but it is
still a user report with no maintainer confirmation and it fails on gfx1200.

Another open issue reports valid-looking output on an RX 7900 XT/RDNA3, but gives
93–125 ms neural jobs at 1920x1080 and 172–297 ms at 2560x1440, followed by queue
growth and a timeout. A separate VR user reports that frame rate tanks and no
obvious quality change was visible. These are not controlled benchmarks, but they
reinforce that the port is an experimental research backend, not evidence of
real-time stereo VR suitability.

The community reports of a generated `dlssnr_on_amd_weights.bin`, native
`gfx1201` kernels, and recognizable Swin/QKV/attention/FFN stages are plausible
and consistent with the first-party “extractor” wording. They are not currently
reproducible from the public repository. Treat them as **moderate-confidence
observations**, not as a decoded weight release.

## Important parallel development: NVIDIA’s official description

NVIDIA’s September 1 DLSS 5 research page now states explicitly that the system
uses a **one-step pixel-space diffusion model**. It says inference is conditioned
on the current rendered frame, engine motion vectors, carried temporal state, and
artistic-direction values; training uses consistency supervision from
renderer-derived scene attributes; and the resulting process is causal,
deterministic, and trained for frame-to-frame temporal stability.

This upgrades “one-step diffusion” from only an inference-architecture hypothesis
to an official high-level training/inference description. It does not disclose
the production checkpoint, tensor format, exact layer ordering, losses beyond the
high-level consistency statement, or the internal AMD conversion format.

It also strengthens the case for our existing capture requirements: exact engine
motion vectors, temporal history/reset/order, artistic controls, and renderer
attributes are not optional metadata if the goal is to reproduce the teacher’s
behavior. Final-image-only collection remains insufficient.

## Value to OpenNR-VR

### High-value changes to our research plan

1. **Track the AMD converter as a possible weight-format oracle.** If a safe
   sample of `dlssnr_on_amd_weights.bin` becomes available, the first questions
   should be file size, header/framing, record count, tensor names, shape metadata,
   dtype/quantization, per-record offsets, and whether the file is stable across
   input DLL versions. Compare its inventory against the independent NVIDIA
   `WEIGHTS_HT/1033` observation of a 147,695,410-byte opaque resource with 153
   records, but do not assume that the two containers are one-to-one.
2. **Use conversion success as a gate, not as a checkpoint claim.** A log saying
   “weights build OK” proves that the AMD program accepted and transformed the
   DLL. It does not prove that the resulting bytes can be loaded by PyTorch,
   converted to `safetensors`, or numerically matched outside the AMD backend.
3. **Preserve the black-box path in parallel.** The AMD lead may eventually reduce
   the need for pure distillation, but it does not remove the need for our exact
   Feature-18 teacher capture. The two routes provide complementary evidence:
   AMD conversion could expose parameters/layouts, while OpenNR captures the
   actual game-conditioned outputs, temporal behavior, and stereo pairing.
4. **Update the student-model prior.** The AMD observations plus the independent
   binary reconstruction make a multiscale, tiled/local-attention model with
   fused QKV/FFN paths and a temporal state a better architecture hypothesis than
   a generic CNN. It remains an ablation target, not a reason to replace the
   measured compact POC or claim that a full 131.9M/148M-parameter model is
   available.
5. **Add the official training fact to future dataset design.** Organize samples
   around current color, exact motion vectors, depth/renderer attributes where
   available, carried history/reset state, controls, raw pre-SR Feature-18 output,
   and downstream SR/DLAA output as separate stages.

### Things that are not useful to change now

- The AMD port does not provide a direct runtime path for our RTX 5070 Ti or
  Skyrim VR installation. It targets AMD HIP/RDNA execution, FSR-fed DX12 games,
  and an experimental proxy architecture.
- It does not justify changing our exact `DLSSNR.Depth`/`DLSSNR.MVec` contract to
  estimated optical flow. The AMD bridge may consume FSR-derived inputs, but that
  is not proof that those inputs are equivalent to the renderer-native guides
  required by our teacher.
- It does not justify adding AMD binaries, the setup executable, or an unknown
  weight file to MGO, OpenNR-VR, Lentus, or the production teacher package.
- It does not establish stereo correctness, headset quality, temporal stability,
  or VR frame-time viability. The available AMD reports are flat-screen and
  experimental, and some show severe queueing or kernel failures.

## Safe future investigation protocol

Do not execute the closed installer on the known-good MGO/Lentus systems. The
release is closed-source, relies on DLL proxy/sideload behavior, and community
reports include antivirus/Defender concerns that have not been independently
resolved. A clean scan would not replace source audit or reproducible-build
evidence.

If an isolated AMD test machine or a separately supplied artifact becomes
available, the safe research sequence is:

1. Preserve the exact release asset hash and the supplied DLL hash; quarantine the
   test machine from credentials and production game paths.
2. Record installer/runtime versions, GPU ISA, driver, FSR path, resolution, mode,
   and all generated file hashes before running any workload.
3. Capture the generated weight file without modifying it. Inspect only copies
   using read-only header/entropy/offset/strings tools; do not redistribute the
   proprietary NVIDIA DLL or generated model artifact.
4. Check whether changing only the source DLL version changes the converted file,
   record whether conversion is deterministic, and compare file structure rather
   than guessing from a filename.
5. Require an independent loader or tensor enumerator before calling the output a
   trainable checkpoint. The decisive milestone is numerical parity at known
   intermediate boundaries, not merely a successful AMD game frame.

## Project decision and revisit gates

Keep the OpenNR-VR implementation plan unchanged and keep production MGO
untouched. Add the AMD project to the research watch list and revisit only when
one of the following becomes available:

- a public or safely inspectable `dlssnr_on_amd_weights.bin` sample with size and
  hash;
- a published parser, tensor manifest, or converter source;
- a reproducible build or independently audited release;
- a tensor loader that can enumerate shapes/dtypes/layouts outside the AMD
  backend;
- numerical parity for one or more intermediate NVIDIA/AMD execution boundaries;
- a complete forward pass without either NGX evaluation or the closed AMD
  executable.

## Sources checked

- [DLSS-NR-on-AMD repository](https://github.com/danielblnc/DLSS-NR-on-AMD)
- [Alpha v0.2.9 release](https://github.com/danielblnc/DLSS-NR-on-AMD/releases/tag/v0.2.9)
- [Alpha v0.2.10 release](https://github.com/danielblnc/DLSS-NR-on-AMD/releases/tag/v0.2.10)
- [v0.2.10 release assets and SHA-256](https://github.com/danielblnc/DLSS-NR-on-AMD/releases/expanded_assets/v0.2.10)
- [Public issue #29 with the weights-build log](https://github.com/danielblnc/DLSS-NR-on-AMD/issues/29)
- [Public issue #28 with RDNA3 timing/queue observations](https://github.com/danielblnc/DLSS-NR-on-AMD/issues/28)
- [Public issue #27 about the absent backend source](https://github.com/danielblnc/DLSS-NR-on-AMD/issues/27)
- [NVIDIA ADLR — DLSS 5: Generative Neural Rendering](https://research.nvidia.com/labs/adlr/DLSS5/)
- [Independent DLSS5 architecture/resource analysis](https://gist.github.com/madebyollin/55c703a34bf90962844edcd68d04e32e)
- [Community RDNA4 extraction discussion, treated as unverified observation](https://www.reddit.com/r/radeon/comments/1w6sv5m/well_that_happened_fast_dlss_5_neural_rendering/)

This note records the public evidence available on 2026-09-04. It does not claim
that a portable trainable DLSS5 checkpoint has been released, and it does not
redistribute or embed proprietary binaries, weights, or private artifacts.
