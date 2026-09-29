# DLSS 5 and AMD-port update — 2026-09-05

This note records the new public material supplied for review and the changes
made to OpenNR-VR. It separates authoritative NVIDIA statements from community
reports about the closed AMD port. No AMD installer, proxy DLL, extracted weight
blob or unknown binary was installed or executed.

## What changed in the evidence

NVIDIA's September 1, 2026 DLSS 5 research page now identifies the high-level
runtime and training family directly. It describes a **one-step pixel-space
diffusion model** conditioned at inference on the current rendered frame,
engine motion vectors, carried temporal state and artistic-direction values.
It also says that training uses consistency supervision from renderer-derived
scene attributes, and that the runtime is causal, deterministic and trained for
frame-to-frame temporal stability. This confirms several points that were
previously only architectural hypotheses. It does not publish the checkpoint,
named tensor map, exact graph, or a usable training loss.

The SIGGRAPH presentation further explains that NVIDIA distilled broad
appearance knowledge from larger generative models into the compact real-time
model. This makes ordinary RGB regression a valid black-box imitation baseline,
but explains why a small student trained only on sparse Skyrim pairs is unlikely
to reproduce the teacher's skin, hair, lighting and material priors. NVIDIA's
own description also emphasizes renderer consistency and artistic controls, not
just final-image error.

The public `DLSS-NR-on-AMD` repository and its latest alpha releases now provide
strong evidence of a separate AMD execution path: the project targets FSR-fed
DirectX 12 games, requires the user's own 310.8.0.0 `nvngx_dlssnr.dll`, and
reports RDNA3/RDNA4 support. The repository remains a closed runtime: its public
tree does not provide the parser, neural kernels, graph, or a portable tensor
checkpoint. The open RX 9060 XT issue shows successful GPU detection, HIP
initialization, D3D12/FSR hooks and zero-copy interop before all neural kernels
fail with invalid kernel files for the reported gfx1200 target. That is useful
interop/kernel-contract evidence, not proof of a working RDNA4 execution on
that card.

The supplied update reports a generated `dlssnr_on_amd_weights.bin` and local
weight extraction/repacking. That claim is plausible and consistent with the
project's public “extractor” wording, but the blob, parser and tensor manifest
are not published in the repository or release assets. It remains a
medium-confidence research observation rather than a trainable checkpoint. A
successful AMD conversion would still need an independent tensor enumerator and
numerical parity at known boundaries before it could affect our training path.

## What applies to our project

The NVIDIA disclosure materially changes the model contract we should target:

1. **Temporal state is required for teacher-like behavior.** Our current
   `ContextStudent` is explicitly spatial and has no recurrent state, carried
   history, reset handling or temporal loss. It can improve a single frame, but
   it cannot learn causal stability, shimmer suppression or history-dependent
   appearance from the existing sparse corpus.
2. **Exact renderer guides remain valuable.** The current input path already
   preserves native Feature 18 depth and motion-vector resources, per-eye
   scales, validity masks and exact stereo pairing. The AMD FSR path does not
   justify replacing those with estimated optical flow or changing the
   `DLSSNR.Depth`/`DLSSNR.MVec` contract.
3. **Our guide set is incomplete relative to the disclosed training signal.**
   The capture has color, depth and motion, but no verified albedo, normal or
   lighting buffers. Those attributes must be collected only if the renderer
   exposes them through an auditable resource contract; they must not be
   invented from the final RGB image.
4. **The current dataset is not temporal-ready.** The new read-only audit finds
   zero temporal-ready sequences in both the 58-sequence primary capture and
   the 41-sequence supplemental capture. The existing recordings have no
   initial history reset and mostly have host-frame gaps larger than one.
5. **The AMD port is a watch item, not an implementation dependency.** It does
   not supply a safe RTX 5070 Ti runtime, a Skyrim VR integration boundary, a
   trainable checkpoint, or evidence of stereo/headset/frame-time acceptance.

## Changes made

`tools/validate_temporal_capture.py` is a read-only gate layered after the
existing capture validator. It checks that a candidate master clip has:

- complete committed frames with both eyes and full-frame input, teacher, depth
  and motion resources;
- frame ID, sample index and host-frame increments of exactly one;
- an initial `[true, true]` history reset and no mid-clip resets;
- no dropped frames, consistent Feature 18 route/settings and the exact native
  motion-vector contract;
- safe, present artifact paths without inferring crash-tail files.

`tools/test_temporal_capture.py` covers a valid contiguous clip, a sparse clip,
and a clip without an initial reset. The existing primary and supplemental
captures were run through the new gate:

- `out/fullres_audit_20260904/temporal_audit_primary.json`: 58 sequences,
  0 temporal-ready;
- `out/fullres_pilot_audit_20260904/temporal_audit_supplemental.json`: 41
  sequences, 0 temporal-ready.

`config/opennr_capture_temporal.example.json` is a disabled-by-default capture
template for a future short temporal pass. It requests full-frame master data,
both eyes, native depth/motion, 90-FPS sampling, 128 frames, two crops and a
larger queue. It is a starting configuration, not proof that the game can
sustain that rate; queue/backpressure and commit integrity must be checked live.

## Decision

Do not install or execute the closed AMD port on MGO, Lentus or the known-good
teacher system. Do not replace the teacher path, change native guides, or claim
that `dlssnr_on_amd_weights.bin` is usable for PyTorch/ONNX training. Preserve
the current FP16 student/runtime as the baseline.

The next model-bearing change should follow a clean contiguous capture and
audit. Then add explicit causal history and reset handling, evaluate on held-out
clips, and only afterward decide whether renderer-derived auxiliary buffers are
available and safe to add. The spatial student remains useful as pretraining and
as a frozen comparison branch.

## Sources

- [NVIDIA ADLR — DLSS 5: Generative Neural Rendering](https://research.nvidia.com/labs/adlr/DLSS5/)
- [NVIDIA — Multi-student Diffusion Distillation for Better One-step Generators](https://research.nvidia.com/publication/2025-03_multi-student-diffusion-distillation-better-one-step-generators)
- [DLSS-NR-on-AMD repository](https://github.com/danielblnc/DLSS-NR-on-AMD)
- [DLSS-NR-on-AMD releases](https://github.com/danielblnc/DLSS-NR-on-AMD/releases)
- [RX 9060 XT gfx1200 kernel issue](https://github.com/danielblnc/DLSS-NR-on-AMD/issues/26)

