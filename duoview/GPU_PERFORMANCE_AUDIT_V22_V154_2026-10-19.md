# DuoView v22 → v154: GPU efficiency source audit
Date: 2026-10-19. Status: source-proven architecture + hypotheses for measurements; no actual GPU profiler capture, no game benchmarks run by the reviewer. Not an optimization release.

## Baselines, hard constraints
- Working v22 git commit `bd8024c9e83debaaee6890d36c756f186e8421e1`; v154 `8c64ec6030043d5c10b9616598356be7685f860e` (user says excellent periphery shading).
- Official Joey source `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`. SDK pin `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`.
- v22, v154 source here: `duoview/joey_stage1/apply_stage234.py`, `duoview/DuoViewD3D12.hpp`, `duoview/DuoViewGeometry.hpp`, `duoview/DuoViewMonoCopyD3D12.hpp`, `duoview/DuoViewCompositeRaster.hlsl`.
- Never change the quality-preserving Native Stereo Fix shading configuration or fallback protections without isolated A/B verification and headset test.
- Other known v154 defects (separate projects): intermittent missing packets/black XR frames; gaze-linked temporal-history shimmer; settings/UI lockup. Missed frames distort utilization and must be filtered from performance runs.

## Supplied GPU utilization and approximate rendering output
Assuming exactly 3144x2500 pixels per full-eye target (actual live dimensions must be logged) and 40 displayed FPS:
| Mode | Scene-view rectangle pixels | FPS | GPU utilization | 25ms*util: *approximate* busy time |
|---|---:|---:|---:|---:|
| Native stereo (stock) | 15,720,000 | 34 | 100% | 29.41ms at 34fps |
| Mono | 7,860,000 | 40 | 91% | 22.75ms |
| v22 Duo (fovea .5x.5, periphery .2x.2) | 2,279,500 | 40 | 69% | 17.25ms |
| v154 Duo (same) | 2,279,500 | 40 | 75% | 18.75ms |
| v154 Duo (.5x.5 fovea, .5x.5 periphery) | 3,930,000 | 40 | 84% | 21ms |

These pixel counts reflect requested UE view *rectangles*, not verified actual GPU shaded/rasterized/postprocessed pixels. The ratio v154 .2-periphery / stereo is 14.5%. The v22 → v154 difference is +6 percentage points, +8.7% relative utilization, or 1.5ms estimated per frame if the 40-FPS delivery rate, clocks and utilization definitions match.

Critical caveat: busy-time=frame-interval × utilization is NOT equivalent to measured per-pass GPU milliseconds; waits, asynchronously overlapping work, clock/power, the 40FPS cap, the VR compositor and pipeline bubbles confound it. No claim of v154 true GPU frametime or attainable FPS is justified by utilization alone.

For periphery .2 → .5, additional nominal scene-view area is 1.6505M pixels, +9pp GPU load (~2.25ms busy estimate). A purely algebraic, two-point fit is `busy_ms ≈ 15.64ms + (1.363ms/Mpixel)*requested_view_Mpixels`. **This intercept is not proven engine fixed cost**: only two points, same full-output composition, unrelated drawing/state work, possible nonlinear Lumen/TSR and occupancy differences. In particular **do not multiply it into expected fps**. Full input (1x1 +1x1) is not reachable through current periphery slider capped at .5.

## Confirmed source render pipeline
1. In v154, `FFakeStereoRenderingHook::get_desired_number_of_views_hook` returns 2 for ID6, and `adjust_view_rect` sets UE per-view rectangles at `(0,0,w,h)` using `make_layout().fovea` and `.periphery`; foveal crop adjusts current projection. These are genuine requests to Unreal's scene view setup and **are not only compositor masks**.
2. `DuoViewGeometry.hpp::make_layout` computes fovea `round(W*cropW*density) × round(H*cropH*density)`, periphery `round(W*p) × round(H*p)`. It allocates logical 2W×H atlas geometry even when sparse. `rendered_pixels` sums these view rects, not actual UE per-pass pixels.
3. Joey Native Stereo Fix **splits one original two-view main view family into two separate renderer invocations** on UE5.5 STALKER2. Source: upstream `FFakeStereoRenderingHook.cpp`, in native split `views.count=1; call_original();` then `view_family->set_render_target(rtfrt);` / `views.data[0]=native_right_view; views.count=1;` / `render_secondary_view()`. This is not an extra third *scene view*, but it duplicates an engine renderer invocation and may duplicate per-family work and invalidate one-pass/stereo instancing opportunities.
4. Native primary texture `m_game_tex.texture` and secondary `m_scene_capture_tex.texture` are created at original full-eye extents (see user log NativeFix 3648x3220 and 3132x2768 generations). Reducing UE ViewRect does not shrink those resources. UE intermediate allocations and Lumen/TSR processing extents are NOT established by current source logs: only a GPU capture/engine RDG event/resource trace can answer.
5. `DuoViewD3D12.hpp::record_native` copies **two reduced source regions** to `atlas_` using `CopyTextureRegion`, source->COPY_SOURCE transitions and back, THEN `record()` renders a full W×H fullscreen triangle into `output_` and calls `copy_composite_to_stereo`, copying W×H *twice* to a 2W×H XR destination. Note gathers copy only fovea and peripheral rectangles, not both full textures.
6. `prepare` pre-creates a 2W×H Native gather atlas plus W×H compositor output **per XR command slot**, with root signature/PSO/descriptors. These are not newly allocated every normal frame if prewarm succeeds. Each standard 3144x2500 BGRA8 atlas is ~62.9 MB; compositor output ~31.4MB, or ~94.3MB per slot / ~283MB at three slots (excludes native sources, original eye buffers and XR swapchain).
7. `DuoViewCompositeRaster.hlsl` samples the atlas full W×H once (peripheral everywhere; fovea also near crop), then writes full W×H; the output is copied to both eyes W×H each. Costs scale with *output resolution*, NOT nominal fovea+periphery view pixels. A large amount of "fixed" busy time vs changing periphery quality can therefore be useful output-work, though avoidable with more advanced direct-XR compositor designs.
8. Current `DuoViewD3D12.hpp::record` starts/end timestamp query around full-screen shader + XR copies but *after* `record_native` gather. Thus UI GPU composite timer **excludes Native primary+secondary texture gather** and their transitions. If timestamp queries are toggled off or no retired slot yet, "waiting" does not measure zero.
9. The OpenXR `m_openxr.copy` gating in `apply_stage234.py` verifies Native pair frame identity/generation + pose + source and command slots. User v154 log contains stale packet rejects and empty-frame submissions, so benchmark only accepted, successfully submitted source frames and separately count rejects.

## Costs: likely inherent vs custom
**UE/scene inherent** (must measure independently and not call it redundant):
- 2 independent scene frusta → two view-dependent visibility/occlusion, some depth/base pass, screen-space AO/Lumen/reflections, postprocessing, VR-specific view uniforms.
- Off-axis foveal and full-frustum periphery projections can cause different occluders, history and GI; forced shared history can cause visible artifacts.
- Expensive shadow/Nanite/Lumen surface-cache work may be globally shared, or may happen more than once due 2 renderer calls. Determine per-event count in GPU capture before changing.
- Some passes scale with global textures or geometry count rather than viewport area; late post-upscale passes may still be full-resolution.
**Avoidable/changeable candidates**:
A. Native split 2 renderer invocations vs one-family (high possible gain, high risk). Goal: one original main view-family invocation with two real mono-view members, each own correct independent ViewRect, projections, scene histories and Native Fix-quality secondary shading. But the chosen shading currently relies on Native Fix path; MUST prove Lumen/constructor parity first. Do not toggle unrelated Native fix bits blindly.
B. Gather atlas 2 x D3D12 texture region copies + 2W×H persistent resource + associated transitions (low/medium potential gain, lower risk). Direct SRV bind primary/periphery into one compositor, sample each with source-local UVs and equivalent sRGB/half texel, keep per-slot lifetime and barriers; WARP pixel equivalence/gradient tests first.
C. Mono W×H output plus 2 copies into XR (medium potential, nontrivial). Optional raster direct into the two XR-eye rectangles with separate viewport/scissors or instanced draw / hardware layered stereo, avoiding intermediate + copy, but verify XR image access, fences, blending parity and native UI/alpha layering. Do NOT blend into currently sampled image.
D. Per-frame GetDevice, descriptor re-creation, copy/reset command handling in `record()`: smaller CPU/driver costs measurable via CPU profiler; not likely entire GPU busy gap.
E. Resize scene capture scratch textures only if engine safely allows; changing Native Fix target size may break hooks/shading and UE allocations, so benchmark actual resource extents first.
F. Same view-family shadow/Lumen sharing/one renderer call: possible large saving or measurable regression, depends UE version (UE5.5 STALKER2), not guaranteed. Instanced Stereo is known mainly as CPU/render thread optimization and can have mixed GPU benefit.

## Required experiments (single scene, same camera, no loading, reliable 20–30 sec samples)
- Keep DLSS mode, screen percentage, brightness, view size (live exact W/H), fovea rect/density, shade Native Fix ON/OFF, timewarp/SteamVR max FPS and any reprojection policy controlled; log clocks, CPU frametimes, GPU frametime p50/p95/p99, GPU active% and power. Disable FPS limiter/reprojection *for diagnostic run only*, restore afterward. Headset eye tracking OFF/manual fixed center for first profile; no changes to shading.
- Baselines: original stock native stereo (Native Fix OFF), native stereo Native Fix ON, v22 Duo, v154 Duo Native shading ON and OFF, Joey Mono. Explicitly separate whether source pair actually completes (log `packet_pair_valid`, rejected count) and whether UE renders the two views in 1 or 2 calls.
- Two-dimensional DuoView scaling matrix, not only .2 vs .5: crop 0.25/0.50/0.75, periphery .20/.35/.50, density 1; profile 4 representative points first then expand.
- **True equal-res comparison**: stock Native 1x1 +1x1 vs temporary **diagnostic-only** DuoView 1x1 +1x1 (requires loosening periphery max .5 to 1 and validating geometry, output, quality). This is NOT allowed in production UI currently. Do not compare against "native stereo equivalent" until sources and VR pixel geometry verified.
- Measure UE ProfileGPU/Stat GPU for pass counts and extent per view: Nanite visibility, shadow depth/VSM, base pass, Lumen Scene, Lumen ScreenProbeGather, Lumen reflections, translucency, TSR/DLSS, tone map, exposure, UI, compositor, XR copy, UE RHI barriers.
- Capture GPU frame via PIX/RenderDoc (only if stable with anti-cheat/hook injection; keep separate sacrificial test run). Inspect view rectangles, per-pass dispatch sizes, UAV/RTV texture extents and histogram of draw/dispatch count. Count duplicate renderer and Lumen invocations. Epic docs: https://dev.epicgames.com/documentation/en-us/unreal-engine/introduction-to-performance-profiling-and-configuration-in-unreal-engine and https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-performance-guide-for-unreal-engine .
- Instrument four *GPU* timestamp ranges at fixed prewarmed per-slot query heap, resolving after GPU fence, preserving exact recorded frame key: source render primary/secondary (UE capture, may need engine RenderGraph events instead of hook timing), Native gather, Mono blend, XR double copy, plus barriers/queue waits. CPU timestamps around each renderer invocation and XR command recording are distinct from GPU timestamps. Async queues can overlap; summing ranges is NOT total frame time.

## Release gates / nonregression requirements
1. Source/test-only profiling branch first. No destructive edits to v154 or stable v22. No GPU allocations / PSO compile / map or fence waits in xrAcquire/copy hot paths.
2. Verify retained Native Fix peripheral shading on screenshots/in-headset; color/exposure/Lumen consistency, fixed/gaze fovea, no black frames, same high output resolution.
3. Baseline 0% optimization expected: new instrumentation identical outputs/frametimes (within variability) and WARP equivalent.
4. For any renderer topology rewrite, test previous/current matrices, separate temporal histories, GPU fences, persistent scene-capture lifetime, complete pair validation, and fallback; shadow/Lumen parity before interpreting performance.
5. Move in order: full GPU frame capture → direct primary/secondary SRVs (easy A/B) → direct doublewide output (if worthwhile) → single-family architecture (highest risk), then size-scaling performance curve.
6. Claiming 2x FPS or GPU-cost reduction is premature without one comparable uncapped GPU capture. At fixed 40 FPS, throughput cannot double no matter how much GPU headroom is freed until the cap/bottleneck is removed.

## Suggested interpretation of double-performance idea
The relative +6pp v22→v154 cannot account for the whole 75% usage. Largest latent cost is UE 2-view rendering+Lumen etc plus fullscreen outputs. Redesign could in principle save large amounts, but fixed overhead includes real work; goal is *profiler-proven* removal of duplicated passes, not arbitrary halves. Any claims of 2x at 40-FPS cap are not meaningful.
