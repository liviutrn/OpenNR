# OpenNR-VR Phase 0 reconstruction

Status: M0.1 complete, static source reconnaissance only

Date: 2026-09-03

Teacher baseline: [Open Shaders 0.4.5](./BASELINE_OPEN_SHADERS_0.4.5.md)

This document answers where the working Skyrim VR Open Shaders integration receives its inputs, evaluates DLSS5 Neural Rendering, and produces the teacher result. It is based on the pinned local checkout and its current dirty state. It does not claim live headset acceptance, exact runtime resource formats, or GPU completion timing.

## Executive result

The working VR path is an in-process Open Shaders D3D11/D3D12 interop path. It does not call Streamline's DLSS evaluation function for Neural Rendering. The normal post-upscale route enters through the VR UI/image-space hook, isolates each eye into a separate D3D11 texture, evaluates Feature 18 sequentially for the two eyes, and copies the per-eye result back into the VR total target before the original UI/image-space composite.

For a clean first capture baseline, use the documented Full (100%) model-resolution route and capture:

1. `NeuralRendering::ColorLeft` / `NeuralRendering::ColorRight` immediately after the per-eye pre-NR copy.
2. `NeuralRendering::OutputLeft` / `NeuralRendering::OutputRight` after Feature 18 completion and before any reduced-resolution model resolve or copy-back.

At 100%, `OutputLeft/Right` are the raw per-eye Feature 18 teacher images at the output dimensions. At reduced model resolution, `OutputLeft/Right` are lower-resolution raw NR results and `ResolvedLeft/Right` is a later custom full-resolution composition; those must not be conflated.

## 1. Exact DLSSNR call

The normal post-upscale VR call chain is:

```text
FoveatedRender::UICompositeRenderHook::thunk
  -> NeuralRendering::ApplyFoveatedLdr()
  -> Renderer::ApplyStereo(...)
  -> Renderer::ExecuteCascade(...)
  -> Runtime::Execute(...)
  -> NVSDK_NGX_D3D12_EvaluateFeature(...)
```

Evidence in the teacher source:

- `src/Features/Upscaling/FoveatedRender.cpp:78-82` calls `NeuralRendering::ApplyFoveatedLdr()` before the original image-space/UI function.
- `src/Features/Upscaling/NeuralRendering/Integration.cpp:417-513` builds the normal VR inputs from `RENDER_TARGETS::kTOTAL`, the active eye UV rectangles, and the per-eye depth/motion-vector guides, then calls `Renderer::ApplyStereo` at `497-499`.
- `src/Features/Upscaling/NeuralRendering/Renderer.cpp:217-300` owns the stereo copy, interop submission, Feature 18 evaluation, optional reduced-resolution resolve, and copy-back.
- `src/Features/Upscaling/NeuralRendering/Renderer.cpp:332-365` calls `Runtime::Execute` once for each cascade pass and eye.
- `src/Features/Upscaling/NeuralRendering/Runtime.cpp:21-29` identifies `nvngx_dlssnr.dll` and the `NVSDK_NGX_D3D12_EvaluateFeature` export; Feature ID 18 is set at line 22.
- `src/Features/Upscaling/NeuralRendering/Runtime.cpp:286-382` defines the runtime wrapper. The vendor evaluation call is `NVSDK_NGX_D3D12_EvaluateFeature` through the loaded function pointer at `374-375`.

The per-frame Feature 18 parameters include:

- `DLSSNR.Color`, `DLSSNR.Depth`, `DLSSNR.MVec`, and `DLSSNR.Output`
- color/depth/motion/output subrect bases and dimensions
- `DLSSNR.MVecScaleX/Y`
- `DLSSNR.DepthInverted`, `DLSSNR.Enabled`, and `DLSSNR.Reset`
- intensity, local tone, local structure, skin structure, automatic mask, style, and UI correction tuning

The foveated composite is deliberately separate from that guide contract. The
DLSS/Feature 18 crop remains a rectangular per-eye subrect, while cropped writeback
can use an aspect-corrected oval feather/dither mask to remove the visible box corners.
`Nasal Convergence 60%` is a new preset for the left/right nose-side overlap; the
existing 50% preset remains available, and `Rectangle` remains the fallback mask.

This is distinct from the earlier DLSS Super Resolution call in `src/Features/Upscaling/Streamline.cpp:634-721`; its `slEvaluateFeature(sl::kFeatureDLSS, ...)` call at `704` is not the Neural Rendering teacher call.

## 2. Stereo representation

The NR renderer uses explicit per-eye resources, not a texture-array or opaque stereo structure:

- `Renderer.cpp:21-27` defines two eyes and maps `(eyeIndex, passIndex)` to independent Feature 18 slots.
- `Renderer.cpp:145-158` stores `std::array<EyeResources, 2>`; each eye has separate color, model input, depth, motion-vector, intermediate, output, and optional resolved textures.
- `Renderer.cpp:217-300` accepts `std::array<StereoEyeInput, 2>` and loops over eye `0` and eye `1` sequentially in one D3D12 command-list submission.
- `Renderer.cpp:247-252` splits the source using a `D3D11_BOX`; the right-eye `sourceX` includes the right-eye offset when the source is side-by-side.
- `Renderer.cpp:538-603` creates each shared texture with `MipLevels=1`, `ArraySize=1`, and `SampleCount=1`, using separate left/right resource names.

The surrounding DLSS SR route also uses left/right viewports and per-eye guide resources. The important capture fact is that Feature 18 itself receives two isolated, non-array eye resources. Eye identity is explicit in the loop index, resource name, source rectangle, Feature slot, motion-vector scale, and left/right UV selection.

## 3. Best pre-NR capture resource and insertion point

Best resource for the default Full (100%) route:

```text
NeuralRendering::ColorLeft
NeuralRendering::ColorRight
```

These are `State::EyeResources::color.resource11` created by `Renderer::EnsureResources`. The passive observation boundary is immediately after the per-eye source copy (and model-input downsample, when enabled) and before `BeginD3D12`. At that point the captured `input` resource is the exact per-eye color that becomes `eye.color.resource12` on the Full route, or `eye.modelInput.resource12` on a reduced route and is passed as `DLSSNR.Color` for the first Feature 18 pass.

The source color comes from the `RENDER_TARGETS::kTOTAL` region selected in `Integration.cpp:451-499`. The code's source rectangle is therefore a precise per-eye region, not a desktop mirror or a post-UI image.

Reduced-resolution handling: when `modelResolutionPercent < 100`, the capture records
`input` from `eye.modelInput` and also records the original `eye.color` as
`input_source`, with dimensions and route metadata for both.

## 4. Best post-NR teacher resource and insertion point

Best raw teacher resource:

```text
NeuralRendering::OutputLeft
NeuralRendering::OutputRight
```

These are `State::EyeResources::output.resource11`, the D3D11 side of the shared D3D12 output resource supplied as `DLSSNR.Output`. The capture boundary is immediately after `D3D12Interop::EndD3D12()` returns and before reduced-resolution `DispatchModelResolve` or final copy-back.

At Full (100%) model resolution, this is the raw Feature 18 result at the color output dimensions. At reduced model resolution, the raw output is lower resolution. `DispatchModelResolve` combines model input, raw output, and source color into `eye.resolved`; that resolved texture is captured as `teacher`, while the raw output is captured as `teacher_raw`.

Do not use the final `kTOTAL` target after UI/image-space composition as the raw teacher. The copy-back at `Renderer.cpp:295-296` is useful for validating route placement, but it is downstream of the raw output boundary and may be overwritten by the original composite.

## 5. Depth, motion vectors, jitter, exposure, and frame identity

Depth and motion vectors are accessible near the NR call:

- `Integration.cpp:445-448` selects full-eye or cropped per-eye depth and motion-vector guides from `Core`.
- `Integration.cpp:473-490` carries each eye's guide resources, source rectangle, and motion-vector scale into `StereoEyeInput`.
- `Renderer.cpp:252-258` copies those guides into `eye.depth.resource11` and `eye.motionVectors.resource11`.
- `Runtime.cpp:341-366` passes them as `DLSSNR.Depth` and `DLSSNR.MVec`, with guide dimensions, motion-vector scales, `DepthInverted=0`, and reset/tuning values.
- `Renderer.cpp:538-559` creates the depth guide as `DXGI_FORMAT_R32_FLOAT`; the motion-vector resource follows its source-derived format and must be measured at runtime.

Other useful metadata is available in the same path:

- source and destination rectangles, full-eye dimensions, guide dimensions, model dimensions, model-resolution percentage, pass count, and per-eye motion-vector scale
- eye UVs and `sourceX/sourceY` from `Integration.cpp:440-490`
- frame freshness via `Core::neuralGuidesFrame` and the host frame counter checked in `Integration.cpp:433-438`
- reset state from the per-eye `resetPending` array
- DLSS SR jitter from `VRDlssParams::Resolve` and `Streamline::CheckFrameConstants`; the current Feature 18 `Runtime::Execute` signature does not pass jitter directly

There is no explicit exposure parameter in the Feature 18 parameter block visible in `Runtime.cpp`. Streamline's separate DLSS SR setup enables auto exposure, but that is not proof that Feature 18 consumes the same value. Exposure, projection/pose matrices, and exact render-target semantics should be treated as additional runtime-capture questions.

## 6. Synchronization and resource lifetime

The teacher uses D3D11 resources shared into D3D12:

- `D3D12Interop.cpp:84-136` creates the D3D11 texture and shared handle, then opens it as a D3D12 resource.
- `D3D12Interop.cpp:139-179` signals a D3D11 fence and makes the D3D12 queue wait before recording Feature 18 work.
- `D3D12Interop.cpp:181-203` submits the D3D12 work, signals its fence, and queues a D3D11 context wait before later D3D11 output copies.
- `D3D12Interop.cpp:219-227` waits for idle only when the renderer explicitly needs all submitted work complete, such as resource recreation or reset.

The output textures are reusable per-eye resources, not immutable frame objects. A capture implementation must enqueue a copy into its own ring of staging/readback resources after the interop dependency has made the output available, retain the frame/eye metadata alongside that copy, and map/write it asynchronously. It must not synchronously map the teacher output on the render thread or write image files from the render thread.

The exact runtime resource state, GPU completion point, aliasing behavior, and whether any external consumer observes `kTOTAL` between the NR copy-back and UI composite are not established by static inspection. The capture hook must preserve the existing fence/barrier chain and be validated with a live GPU capture.

## 7. M0.2 capture boundaries (implemented; live validation pending)

The opt-in `OpenNRCaptureFeature` now taps the following existing boundaries. The
feature is disabled by default and leaves the Feature 18 route unchanged when it is
off:

| Data | Static hook boundary | Intended meaning |
| --- | --- | --- |
| Pre-NR color | `Renderer.cpp`, after each per-eye source copy/downsample | `input`; exact per-eye Feature 18 input (`modelInput` on reduced routes) plus `input_source` for the original color texture |
| Raw post-NR color | `Renderer.cpp`, after Feature 18 resolve and before copy-back | `teacher_raw` when reduced, otherwise `teacher`; raw Feature 18 output |
| Reduced-route visible composite | `Renderer.cpp`, after `DispatchModelResolve` | `teacher`; custom reduced-resolution composition |
| Periodic validation | same color boundaries every `full_frame_every_samples` samples | complete per-eye source rectangle alongside normal crops |

Each capture should record at minimum: host frame counter, eye index, route, source rectangle, width/height, DXGI format, mip/array/sample description, model dimensions, guide dimensions, motion-vector scales, jitter if available, reset state, and a copy/completion sequence identifier. The first implementation should not change the Feature 18 parameters or route selection.

## Remaining live validation gate

The main unresolved question is the live resource contract at the selected route: exact runtime dimensions/formats/states and GPU completion timing for the per-eye color/model-input and teacher resources, plus confirmation that the post-`EndD3D12` output is stable raw Feature 18 data before any later resolve or reuse. The implementation records these values at runtime and uses a D3D11 event query, but a live instrumented frame or RenderDoc capture is still required to accept headset output, sustained queue behavior, and artifact-free data.

## M0.1 acceptance statement

The exact Feature 18 call, per-eye representation, pre/post resource candidates, guide availability, synchronization boundary, and the largest runtime unknown were documented by this reconnaissance. The later M0.2 implementation is an opt-in source-side integration in the dirty teacher worktree; it does not modify the private runtime binaries or game installation.
