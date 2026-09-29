# DLSS 5 reconstruction update — 2026-09-04

Status: high-value research lead; not yet a usable model artifact or a change to
the OpenNR-VR implementation plan.

## Executive assessment

The latest public reconstruction work is materially more useful than the earlier
static DLL/resource inventory. The researchers report numerically reproducing one
DLSS 5 attention block against NVIDIA's execution, with approximately 99% agreement
at intermediate checkpoints. If the result survives independent reproduction, it
gives us a credible architecture prior and a future reference target for a larger
distillation student or an independent backend.

It does not yet justify replacing the current compact student, changing the Phase 0
capture contract, or claiming that an open DLSS 5 model is available. The reported
work still lacks a public full forward pass, public tensor dump/checkpoint, and the
FFN, temporal, front-end, transition, and reconstruction pieces needed for an
end-to-end model.

## What is currently reported

The update from the collaborating researchers reports:

- about 131.9M active parameters across 153 tensors;
- a 24-block core described as 8 Swin blocks at 512 channels, 8 ViT blocks at
  1024 channels, and 8 Swin blocks at 512 channels, surrounded by multiscale
  input/reconstruction stages;
- for `block23`, 1,056 tokens on a 24x44 grid, 16 heads, 32 dimensions per head,
  local 8x8 windows, packed QKV, native activation permutation, L2-normalized Q/K,
  scaled-cosine attention, per-head scaling, bias, boundary masking, projection,
  and residual handling;
- reported attention-context cosine similarity of 0.9909, projected-branch cosine
  similarity of 0.9890, and 97.54% MSE explained.

The same thread reports an RX 9070 XT timing of about 0.290 ms for one 512-channel
Swin block and about 4.64 ms for 16 Swin blocks. This is an encouraging kernel
signal, not an end-to-end neural-renderer or VR-frame result. The measurement and
the public bridge are Linux/RDNA4 evidence, whereas our current target is Windows,
Skyrim VR, and an RTX 5070 Ti; neither is a drop-in runtime path for OpenNR-VR.

## Evidence and confidence

| Item | Current evidence | OpenNR-VR interpretation |
| --- | --- | --- |
| DLSS 5 is a renderer-grounded, single-pass generative stage conditioned on color, engine motion, carried history, and controls | NVIDIA's public DLSS 5 description | Consistent with our exact-guide and temporal-capture requirements; it does not reveal the internal graph |
| 153 resource records, 71 logical `blockN` IDs, and a roughly 147.7 MB `WEIGHTS_HT` payload | Earlier public static/resource analysis | Storage/container inventory, not a trainable checkpoint or proof of active execution order |
| 131.9M active parameters and 24-block Swin/ViT/Swin core | Researcher-reported reconstruction update | Strong architecture lead, but still self-reported until code, checkpoints, or an independent reproduction are available |
| `block23` intermediate agreement near 99% | Researcher-reported reference comparison | Meaningful reverse-engineering milestone; it validates one block boundary, not the full image path |
| Linux NGX/D3D12 bridge | Public source and build instructions | Useful execution/interception plumbing; it explicitly does not include model weights, CUBINs, or a vendor-neutral model |
| RDNA4 FP8 E4M3 support | AMD specifications and GPUOpen/ROCm documentation | Makes a native alternate backend technically plausible; it does not establish parity, licensing, or VR performance |

The 131.9M active-parameter estimate and the older 147.7 MB opaque resource size are
not necessarily contradictory: one is an inferred count of active learned values,
while the other is a serialized payload containing storage formats, metadata,
padding, and possible auxiliary records. The two separate `153` counts should not
be treated as a proven one-to-one tensor/record mapping without the researchers'
exported map.

## Value to this project

### High value later

1. **Architecture-informed student design.** The multiscale plus local-window
   attention shape gives us a better candidate for a medium student than a generic
   image CNN. We can scale the widths and block count down while retaining the
   useful inductive biases: multiscale features, local attention, FFN/residual
   blocks, and a temporal state path.
2. **A better distillation ladder.** The current compact RGB-only/guided POC remains
   the control. A future temporal multiscale student can be compared against it,
   then an architecture-informed student can be added as a separate ablation. In
   the current exploratory held-out run, RGB-only beat the same-size RGB+depth/MV
   student, so the recovered architecture should guide controlled ablations rather
   than be taken as proof that every teacher input helps a small student.
3. **A possible independent backend.** If the researchers complete FFN recovery,
   repeated-block chaining, and a first image without NGX, their intermediate
   checkpoints could become a numerical oracle for a portable implementation.
4. **Capture priorities.** The result reinforces that exact native motion vectors,
   reset/order metadata, temporal history, full-frame stereo data, and internal
   intermediate checkpoints matter more than collecting a large number of isolated
   RGB pairs.

### Not useful yet as a direct implementation input

- There is no public weight dump, safetensors, ONNX, trainable checkpoint, or full
  architecture source as of this dated review.
- Our current capture records pre/post color, native depth and motion vectors, and
  reset metadata, but not the proprietary block23 checkpoints, persistent previous
  output/history tensor, or the complete front-end/control preprocessing.
- A 0.9909 attention-context comparison does not prove correct FFNs, transitions,
  history reprojection, final color reconstruction, stereo consistency, or frame
  time.
- The public bridge can make NVIDIA's reserved Feature 18 call reachable on Linux;
  it does not replace `nvngx_dlssnr.dll` or supply an independent network, and it is
  not a Windows Skyrim VR drop-in. Our existing teacher-side tap is the relevant
  integration boundary for this project.

## Project decision

Keep the current OpenNR-VR course unchanged:

- finish the isolated live Phase 0 gate and validate the exact per-eye Feature 18
  input/output resources;
- keep the current compact spatial POC as a measured baseline, without presenting
  it as a full DLSS 5 reconstruction;
- collect contiguous temporal clips with exact native guides, reset/order/drop
  metadata, stereo pairing, and measured frame-time impact before designing the
  larger student;
- do not replace renderer motion vectors with optical flow for the teacher contract;
- do not alter the production MGO profile or teacher ownership for this research
  lead.

The recovered-core path should be a gated future workstream, not a Phase 0 change:

```text
public block23 checkpoint/code
        -> independent block23 reproduction
        -> FFN + repeated-family chaining
        -> first image without NGX
        -> temporal/history/front-end integration
        -> measured stereo VR backend
```

The next useful modeling experiment for us is therefore a smaller temporal
multiscale/window-attention student trained from the validated capture contract,
not an immediate attempt to instantiate the 131.9M-parameter topology.

## Revisit gates

Revisit this note when one or more of these become available:

1. released block23 reference code, weights, or intermediate tensors;
2. exact FFN and repeated-block numerical agreement;
3. an independently rendered frame with no NGX/NVIDIA evaluation;
4. a documented input/history/control contract;
5. end-to-end timing at the target per-eye resolution on hardware relevant to our
   VR deployment.

## Sources checked

- [NVIDIA ADLR — DLSS 5: Generative Neural Rendering](https://research.nvidia.com/labs/adlr/DLSS5/)
- [Researcher update thread and comments](https://www.reddit.com/r/radeon/comments/1w4n1a1/i_got_dlss_5_neural_rendering_running_on_an_rtx/)
- [Earlier DLSS 5 architecture/resource analysis](https://gist.github.com/madebyollin/55c703a34bf90962844edcd68d04e32e)
- [Public Linux NGX/D3D12 bridge](https://github.com/ccoredesenvolvimento/dlss5-linux-bridge)
- [AMD Radeon RX 9070 XT specifications](https://www.amd.com/en/products/graphics/desktops/radeon/9000-series/amd-radeon-rx-9070xt.html)
- [AMD GPUOpen RDNA 4 WMMA guide](https://gpuopen.com/learn/wmma-guide-amd-rdna-4-gpus-part-1/)

This note records public claims and their project implications as of 2026-09-04;
it does not reproduce or redistribute proprietary NVIDIA binaries, weights, or
private researcher artifacts.
