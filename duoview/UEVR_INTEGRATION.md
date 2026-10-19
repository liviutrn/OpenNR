# Active public-backend integration

The active build uses `apply_public_mono.py` followed by `apply_public_duoview.py`. The older `apply_stage1.py`, `apply_stage2.py` and `apply_stalker_publicsdk_abi.py` remain historical experiments against Joey's newer private-SDK-dependent tree; they are not the installable injector pipeline.

## Source pins

| Component | Public source | Pin |
|---|---|---|
| UEVR | praydog/UEVR | 4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d |
| UESDK | elliotttate/UESDK-RenderDoc | 418729025bad57b094bf6b2e2b55734454c97de6 |
| Injector | joeyhodge/uevr-frontend | 60be4b0f9a646109fd9fdf448bacd41477234091 |
| Mono algorithm reference | joeyhodge/UEVR | becc96692839f0087ccef238f03af618051fb765 and db6729dd9f5745705b1cdec2ec6f51bdc9570983 |

## Render flow

1. A guarded mode transaction retires GPU consumers before committing at a game-frame boundary. Mono ID 5 and DuoView ID 6 are distinct; IDs 3/4 remain reserved and unavailable in this public backend.
2. During main-viewport view construction, a `ConfigLatch` freezes crop/density/peripheral settings and Toolkit gaze once for the generation/frame. A bounded `State` ring retains packets for pipelined frames.
3. The first UE view's final camera position/rotation is captured after normal UEVR head tracking and mod callbacks. The second uses those exact values. Mismatches invalidate the packet.
4. `AdjustViewRect` places the selected foveal view and peripheral view into disjoint regions of the existing double-wide atlas. The projection callback uses one common Mono optical frustum, with an off-axis crop for the foveal view. The near clipping plane is frozen from the current game value.
5. The main family must contain exactly two views. Rectangle, projection and camera observations are required for both indices. Non-eye callbacks do not seed a DuoView crop or change its index convention.
6. The producer frame carried through the inherited RHI path is captured under the OpenXR assignment lock. Effective frame-delay compensation is zero in Mono; the saved preference is retained. A mismatched or already consumed packet cannot be copied.
7. On the existing game graphics queue, the DX12 compositor samples the two Native Fix sources directly when their formats allow it, while retaining the validated atlas gather as a compatibility fallback. The experimental Direct XR output option defaults OFF. With it enabled and the OpenXR target format matching, one raster draw writes the same Mono image across both eye halves; otherwise the compositor uses its dedicated single-width RTV and copies that image into both halves. Resource states and packet lifetimes remain owned by the current fenced command slot.
8. Resources, SRV/RTV descriptors and timestamp buffers belong to each OpenXR command slot. Compositor SRVs and the direct XR RTV are reused while their resource identities and formats stay unchanged, and refreshed when those keys change. Stable descriptor handles and increments are captured during prewarm. Slot reuse waits for its own fence. The source is retained through the copy consumer. GPU diagnostics measure raster/output work, excluding scene rendering and source gather copies. Compare both output routes on hardware; neither is established as faster. Fallback textures remain preallocated. Swapchain teardown releases compositor references only after command-slot retirement and before destroying the swapchains.
9. Joey's calibrated Mono projection-layer geometry selects the corresponding optical image regions for each eye using the same camera origin and optical basis.

## Public SDK adapters

The public SDK exposes `FUObjectItem::get_object()` rather than a public object field. Runtime callers use that accessor instead of assuming a memory offset. The SDK's `FSceneView::get_view_family()` accessor now follows its existing engine-layout policy: family offset 0 through UE5.5, after the virtual-table pointer in UE5.6–5.8, and null for explicitly unsupported newer layouts. No private SDK declarations or speculative virtual-table stubs are introduced.

## Proof boundaries

Policy tests establish layout/crop math, pose immutability, packet rejection and generation behavior. Production Windows WARP tests execute `Compositor::record`, its embedded shader, moved crop, per-slot reuse, GPU timestamps and exact duplicate eye copies. Full DLL/injector compilation is a separate CI step.

Present on the inherited graphics queue normally orders composition after the game's scene command stream. The frame token establishes command-stream correspondence; actual atlas production, major game-pass rectangle sizes, asynchronous compute dependencies, temporal histories, exposure, Lumen and headset output still require STALKER 2/PSVR2 testing or a GPU capture. Do not label callback observations as completed per-view GPU renders or theoretical pixel budgets as measured speedups.

## Submission continuity fix after Build 168

The Native producer freezes the exact validated OpenXR pose before the split renderer callbacks and attaches it to the immutable source packet. Submission consumes that snapshot without rereading the mutable runtime ring. Short missing-pair intervals can reference the last successfully submitted scene image for up to 100 ms with its original pose and the current display time. The hold expires from the original successful submission; repeated holds do not renew it. History invalidates before another scene-image acquisition, during swapchain destruction, on generation/handle changes, or on a failed scene submission. Startup cannot invent history. Peripheral shading and the source rendering topology are preserved.

DuoView viewport draws use an independent 64-bit transaction serial rather than deriving draw identity from the XR pose token. Auxiliary-only renderer invocations do not invalidate a completed main pair. The UI exposes copied/held/empty-or-failed scene submission counts; reset them after startup to check steady-state delivery.
