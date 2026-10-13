# Exact released Joey D3D12/OpenXR copy-boundary audit — 2026-10-13

## Provenance

The **byte-verified official** `101226HELLRAISERp1` Mono backend
SHA-256 is `19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966`.
Its `get_commit_hash()` string is
`5ac7edc207866569334175e4ed8a7517971547f6` (2026-10-11);
the corresponding PUBLIC Joey source is accessible at
https://github.com/joeyhodge/UEVR/tree/5ac7edc207866569334175e4ed8a7517971547f6 .
The GitHub release tag points to `387ccb744b57387b438bab7027fd017a23df66a8`
(the neighboring release pointer), but the compiled backend reports `5ac7edc2...`.
Binary embedded commit text alone is not cryptographic proof that all compiled
source matches the repository; correlate entry RVAs, signatures, call operands,
resource types and runtime behavior before enabling new hooks.

## Actual scene consumption and copy destination

Exact embedded-commit source:
* `src/mods/vr/D3D12Component.cpp:2527`:
  `D3D12Component::on_frame(VR*)` (binary known RVA `0x1f0f50`).
* `:2652-2657`: picks `acquire_scene_target_resource`; this is not
  necessarily `StereoHook::get_scene_render_target()`.
* `:2757-2780`: separate STALKER2 UE5.5 engine-owned scene source is declared
  SRVMask (`ENGINE_SRC_COLOR = NON_PIXEL_SHADER_RESOURCE | PIXEL_SHADER_RESOURCE`).
  Overwriting it from assumed RENDER_TARGET state was unsafe.
* `:5243-5374`: Normal non-AFR Native Stereo requests the DOUBLE_WIDE OpenXR
  copy, usually `m_openxr.copy(DOUBLE_WIDE, backbuffer, scene_source_state, nullptr)`,
  but a validated native-stereo capture packet may choose a **pre_commands**
  callback and null `resource`. A future hook must support, or safely reject,
  both source variants **before any Unreal cropped views are activated**.
* `:5469-5614`: `on_frame` calls `OpenXR::end_frame()` on the same call
  chain, after the scene copy, unless an early return/recovery occurs.
* `:7690-7960`: real `bool D3D12Component::OpenXR::copy(`:
  checks XR frame, acquires and waits for the exact swapchain image,
  obtains destination `ctx.textures[texture_index].texture`,
  records a D3D12 copy/pre_commands, executes on the graphics queue,
  calls `xrReleaseSwapchainImage`, and finally returns success only
  if the command context was not poisoned and conditional invariants hold.
  Merely queuing a plugin compositor **before** `on_frame` is not proof
  Joey copied its pixels.
* `src/mods/vr/runtimes/OpenXR.cpp:3940-4156`: chooses frame pipeline
  `get_submit_state()` then `XrFrameEndInfo.displayTime =
  pipelined_frame_state.predictedDisplayTime`. This is distinct from
  pose sample time: `xrLocateViews` uses predicted time plus
  Prediction Scale × predicted period, at OpenXR.cpp ~1485.

## Native ABI source correlation

The COPY method is declared exactly in
`src/mods/vr/D3D12Component.hpp:420-439` and has a non-inline version
with `this`, uint32 swapchain index, pointer to ID3D12Resource, optional
std::function pre_commands, optional additional_commands, D3D12 source
state, source box, optional post_copy_commands, retained Mono resource,
and optional std::shared_ptr<PairFrame>. The four-argument convenience
overload is **inline** and delegates to this function.

The released DLL's unwind table maps RVA `0x1c4280` to `0x1c4d34`;
entry prologue starts:
`4c 89 4c 24 20 4c 89 44 24 18 89 54 24 10 55 53 56 57 41 54 41 55`.
The method's decoded entry stores MSVC x64 register arguments and
accesses an internal mutex at `this+0x168`; source begins by locking
`this->mtx`. This is strong evidence for the function's identity,
**not yet a tested runtime hook**. The compiled method has a complex
by-value MSVC C++ ABI; do not hook it from a simplified signature.

## Required safe plugin redesign

1. Add a **passive observer hook** of this exact copy boundary while
   native Stereo remains unmodified, first validating RVA/prologue,
   source shape, `swapchain_idx`, source state, actual graphics device,
   and which of the ordinary vs callback-based source paths Joey chooses.
   It must call original immediately and never alter pixels.
2. Precompile HLSL and construct all owned compositor resources outside
   active frame processing, with a bounded GPU slot/queue retirement strategy.
3. Only activate two-view rect/projection/camera modifications on the
   **next complete UE frame** once the source/copy contract has been
   proven for its mode, device, generation, swapchain and source shape.
4. Do not overwrite engine-owned scene textures. Render into an owned
   double-wide composite; provide that owned source to Joey's **normal**
   swapchain copy function, with the **true** source resource state and
   appropriately fenced lifetime.
5. Publish the packet only **after** the exact copy returns success. Tie
   it to the rendering frame/generation and submit call path, **never**
   assume `xrLocateViews.displayTime == xrEndFrame.displayTime`.
6. Before enabling modified views, establish a coherent fallback image
   and frame-aligned pose: copied scene, valid full-periphery crop, or
   rollback to unmodified native render on the **next frame**. It is
   invalid to silently omit projection layers or submit a raw atlas
   as if it were a coherent stereo scene.
7. Verify all of the above with a deterministic copy-boundary ABI
   harness and D3D12 debug layer before one deliberate fixed-gaze
   STALKER2 in-game acceptance test; eye tracking comes later.

**As of this audit the new source-boundary has NOT been hooked or
runtime verified.** The safety-gated Build46 therefore cannot render
DuoView. Do not call it fixed or benchmarkable. Its original Joey
backend remains untouched, and its Lua status explicitly says
`FrameCopyContract=UNVERIFIED`.
