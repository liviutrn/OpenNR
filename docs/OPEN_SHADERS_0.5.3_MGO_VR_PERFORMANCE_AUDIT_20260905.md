# Open Shaders DLSSNR VR 0.5.3 — MGO VR performance and quality audit

Audit date: September 5, 2026. Read-only inspection of source, package listings, saved MO2 configuration, game INIs, and the last available game log. No game settings, installed mods, binaries, or source implementation were changed. Recommendations below are experiments, not measured FPS gains.

**Main finding.** There are worthwhile settings to test before sacrificing MGO's overall appearance. The strongest candidates are reducing the neural-rendered region or model resolution, reducing the local-shadow redraw budget, lowering volumetric lighting from High to Medium, and selectively foveating reflections. Several other optimizations are already enabled. Some attractive-looking switches can bypass neural rendering or do nothing in the current configuration.

**Evidence and version boundary**

- Selected MO2 profile: `E:\MGO-RC3-fresh\profiles\MGO NSFW - 4.0 BETA`, as selected in `E:\MGO-RC3-fresh\ModOrganizer.ini`.
- That profile enables `Open Shaders DLSSNR VR 0.5.2 OpenNR`, not 0.5.3. No installed 0.5.3 mod folder was found in this instance.
- Both 0.5.3 archives exist in `D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d\dist`. Their timestamps are September 5, 11:58–11:59, and sizes are 254,757,122 bytes (base) and 254,992,809 bytes (OpenNR).
- Source inspected: `D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d`. HEAD is `3bd930002a96135cff5b092a7e55e11cf28bc912`, with extensive existing modifications and untracked additions. HEAD alone does not identify these 0.5.3 changes or prove binary/source equivalence.
- Saved user settings: `E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json`.
- Most recent available log: `C:\Users\oleks\OneDrive\Documents\My Games\Skyrim VR\SKSE\CommunityShaders.log`, last written September 4 at 22:10. It records zero discovered settings override files for that session. Configuration load order in source is Default → User → Overrides → User Overrides; saved JSON remains distinct from effective settings in a future launch.
- Hardware queried: RTX 5070 Ti, approximately 16 GB VRAM, driver 616.56; Ryzen 7 7800X3D. SkyrimVR was not running during the audit. Current headset refresh rate, runtime render target, CPU/GPU frame times, VRAM residency, compositor and streaming performance were not measured.

Coverage includes the feature inventory, serialized settings, relevant UI controls and dependencies, upscaling/NR resource flow, VRS, stereo optimizations, lighting/shadows, AO, materials, vegetation, weather, water, cache/compilation controls, package contents, and MGO INIs/mod selection. This is a broad settings and architecture audit, not a formal line-by-line correctness proof of every shader or third-party dependency.

**What the last session actually rendered**

The September 4 log records:

```
[PerfMode] Latched display 2496x2688 -> render 1664x1792 per eye (quality mode 1, preset-derived)
[DLSSNR] resources eye=0 guides=1664x1792 color=2496x2688 model=2496x2688 modelPercent=100% ... passes=1
[DLSSNR] resources eye=1 guides=1664x1792 color=2496x2688 model=2496x2688 modelPercent=100% ... passes=1
[DLSSNR] LDR output written before UI composite ... edgeBlend=false ... path=direct-copy batchedAsync=true
```

Ordinary DLSS Quality already reduces the engine image to two-thirds width and height, about 44.4% of display pixel count. NR subsequently processes about 6.71 million pixels per eye, or 13.42 million across the pair. Reducing the engine resolution helps engine rendering, but post-upscale NR can retain the same model dimensions. The two resolution controls solve different costs.

The interop source already uses GPU fence synchronization with three command contexts and CPU waits for backpressure/reuse or teardown. It is not a simple unconditional CPU wait after each eye that can be fixed by checking an “async” box. A separate D3D12 queue does not make inference free or remove the dependency before output consumption.

**Prioritized experiments**

| Priority | Saved state | Suggested first experiment | Expected mechanism | Main tradeoff |
|---|---|---|---|---|
| 1 | Full Eye, NR 100% | Nasal Convergence 70%, Default DLSS mode, Oval, Feather, falloff 1.0 | Smaller per-eye DLSS/NR rectangle | Reduced peripheral treatment; binocular boundary must be judged in headset |
| 1 alternative | Full Eye, NR 100% | Keep Full Eye; NR 90%, then 85% | Reduce model pixels while keeping full display coverage | NR changes to fine texture, skin and outlines |
| 2 | Shadow budget Manual, 5 ms | Manual 2 ms; compare 3 ms if updates become visible | Limit local shadow redraw work | Shadow lag, delayed updates or popping |
| 3 | Volumetric lighting High inside/outside | Medium inside/outside; restart | Smaller volumetric workload | Coarser light shafts or temporal variation |
| 4 | SSR enabled, SSR foveation off | Enable feathered SSR foveation after selecting a crop | Reduce peripheral reflection raymarching | Reflection transitions and fallback appearance |
| 5 | Reflex low latency off | Enable low latency; Boost off initially | Reduce render queue latency | May slightly reduce maximum FPS |
| 6 | VRS disabled at boot and runtime | Load VRS, restart, enable Default with a crop | Reduce eligible peripheral pixel shader work | Coarse shading and outer culling; no direct NR compute saving |
| 7 | Skylighting loaded | A/B feature disabled, with restart as required | Remove probe/mask and shading work | Flatter environmental lighting |
| 8 | AO half resolution, 3 slices × 6 steps | First try 2 × 4; separately test adaptive sampling | Fewer AO samples | More noise or weaker fine occlusion |
| 9 | Quality grass, long fades | Density 70 → 85 → 100 in relevant grass INIs | Reduce vegetation geometry/overdraw | Sparser grass |

These are ordered by plausible benefit and preservation of appearance, not measured cost on this machine. Do not apply all at once.

**Neural rendering and foveation details**

1. The 0.5.3 fresh defaults are Nasal Convergence 70%, Oval, falloff 1.0 and intensity/local tone/local structure 1.70. The saved profile retains Full Eye and 2.0/2.0/2.0. Loading an updated build preserves existing choices; the version change alone is not an optimization.
2. Nasal 70 uses left UV `(0.3, 0.15, 0.7, 0.7)` and right UV `(0.0, 0.15, 0.7, 0.7)`. Both eyes retain equal dimensions, which the NR integration requires. It is a fixed region, not demonstrated gaze tracking. Check each eye and binocular overlap while looking sideways without turning the head.
3. A 70% × 70% rectangle has 49% of the full-eye pixel area. The oval is a blend mask over that rectangle; do not count it as an additional ellipse-shaped inference saving. At 90% model resolution the combined model area is nominally 0.49 × 0.81 = 39.69% of baseline, before integer rounding. That is workload geometry, not a 60.31% frame-time reduction. Engine work, peripheral reconstruction, guide copies, resolves and synchronization remain.
4. Model resolution choices are 100, 90, 85, 75, 50 and 33 percent per axis. Their nominal areas are 100%, 81%, 72.25%, 56.25%, 25% and 10.89%. Start at 90 or 85 for quality. At reduced resolution the renderer adds downsample/resolve work, so savings need measurement.
5. Saved Reduced NR Resolve is Matched Residual (experimental). It preserves the full-resolution source while adding the matched low-resolution model residual. Compare against Classic in the same motion sequence if halos, tone shifts or texture changes appear. At 100% the reduced-resolution distinction is not the principal cost lever.
6. Lowering intensity/local tone/local structure from 2.0 to 1.7 is an appearance adjustment, not a reliable inference optimization: it does not reduce model dimensions or pass count. It may make transitions and aggressive detail changes less distracting.
7. Keep sequential NR Off (already off). Two or three sequential model passes are explicitly screenshot/benchmark options.
8. Keep Default foveated DLSS mode when retaining NR. `Integration.cpp` rejects the VR post-upscale NR path unless mode is Default. Faster also restricts DLSS J/K presets. An FPS increase obtained through Faster is not evidence of faster equivalent DLSSNR output.
9. Experimental pre-upscale NR has its own contract: Full Eye + Default, native guides and no incompatible frame-generation/HDR route. It may reduce NR cost but changes the model's input and output appearance. It cannot simply be combined with Nasal 70. Treat as a separate research comparison after the simpler options.
10. Cropped feathered NR may need a private UAV-capable stereo target if `kTOTAL` lacks a UAV. The fallback incurs two full-frame copies. The log distinguishes `staged-uav`, `direct-uav`, and `direct-copy`. Watch this when measuring crop gains; full-eye direct-copy is not representative of cropped blending overhead.
11. Periphery temporal smoothing is already enabled, with alpha about 0.29 and blur radius 2.1. Keep it initially to control peripheral shimmer. Reducing blur may improve clarity, but can reveal aliasing and the treatment boundary. Dither is not automatically preferable to Feather in a headset.

**Shadows, lighting and reflections**

The local-shadow system is a major tuning opportunity independent of NR. Light Limit Fix has shadows enabled, 16 shadow lights, up to 16 redraws per frame, 32 converted slots, an 8192 atlas, and Manual budget mode (`BudgetMode=1`) with `RedrawBudgetMs=5.0`. Formula is mode 2; the saved `1 + isinterior` expression is inactive. At 90 Hz, a 5 ms allowance is large relative to an 11.11 ms application deadline, but it is not proof that the game spends 5 ms on these shadows every frame, nor a guaranteed GPU time cap.

Start by reducing the manual budget to 2 ms. Alternatively test Formula mode with the existing expression, meaning 1 outside and 2 inside under its intended boolean input. Inspect moving torch shadows, NPCs and doorway transitions. Keep due-gating and skip-zero-demand enabled; both are already on. If budget reduction is insufficient, test 16 → 12 → 8 shadow lights, then max redraws 16 → 8. Avoid extreme redraw throttling: source enforces a minimum of 4 to reduce temporal flicker.

An 8192² D32 texture alone is nominally 256 MiB; 4096² is 64 MiB. This does not describe the entire shadow allocation: engine slices and other resources remain. The log reports base tile 4096, so shrinking the atlas without considering tile size and light count can create capacity pressure. Prefer a budget test before reducing atlas size. The profile's directional shadow map is 4096 with distance 6000; 2048 and/or distance 4000 are later quality tradeoffs. Interior Sun separately exposes distance 5000 and double-sided rendering. Avoid defeating double-sided rendering casually: shadow leaks may outweigh savings.

Particle-light detection, culling and optimization are already enabled; particle contact shadows and general contact shadows in Light Limit Fix are off. Do not claim an additional win from enabling those optimizations. If combat spikes correlate with particles, test max particle distance 6000 → 4000 and per-emitter cap 256 → 128, checking fire, spells and luminous clutter. Particle-light changes cannot cure every CPU-heavy combat spike.

Screen Space Shadows are already in stereo Reprojection mode, with sample count 1. Both saved booleans being true does not mean two independent full raymarches plus reconciliation: the source's combined mode selects the reprojection path. Its cost-saving option still off is FOV Screen Space Shadows, which follows the upscaling mask and fades to no screen-space shadow outside. Test it after establishing the crop. Disoccluded right-eye pixels can fall back unshadowed; examine close geometry.

Dynamic Cubemaps has SSR on and Creator off. SSR foveation is currently off. Enable feathered foveation first, leaving Hard Cutoff off. Its usefulness is scene-dependent: wet roads, metal and water are better tests than a dry matte interior. Disabling SSR entirely is a larger visual sacrifice and can change the fallback reflection appearance. Do not assume disabling Creator disables SSR.

Volumetric Lighting is High (`2`) for both environments, despite `iVolumetricLightingQuality=1` in SkyrimPrefs. The feature has its own quality controls and VR restart gating; use its UI and verify after restart. Medium (`1`) is a reasonable early experiment. Exponential Height Fog and its volumetric fog are already off; disabling them again saves nothing. Volumetric Shadows is a separate loaded feature with downsample/blur work; profile it in scenes with shadowed local light shafts before removing it.

Skylighting and Cloud Shadows were loaded in the last session. Skylighting has probe-update and several mask passes; A/B it before stripping core terrain/material presentation. Cloud Shadows is a secondary test. Neither visibility/opacity set to a visually weak value nor a low strength necessarily bypasses the feature's work; use actual feature disable when measuring cost.

**AO, materials, characters, terrain, vegetation and water**

| Feature family | Verified saved state or log evidence | Assessment |
|---|---|---|
| Screen Space GI | Enabled, GI off, AO-only resources (`1`), half res (`1`), stereo reprojection on, 3 slices/6 steps | Already an economical AO setup; preserve AO-only allocation. Test 2/4 first. Quarter res is a later fidelity tradeoff. |
| AO adaptive sampling | Off | Candidate, not guaranteed saving: adds depth/normal variance work. A/B separately on distant/flat versus cluttered scenes. |
| AO temporal denoiser/blur | Both on | Keep initially; reducing samples without stabilization can cause objectionable VR shimmer. Vanilla SSAO is already off. |
| Extended Materials | Complex material, parallax, height blending, warping fix, shadows on; legacy terrain off | First test parallax shadows off. Retain complex materials and warping fix; disabling everything undermines MGO surfaces. Height blending relevance depends on the active material path. |
| True PBR | Loaded | Preserve as a material contract. Brightness/AO multipliers are not major cost controls. |
| Terrain Blending | On | Preserve initially; its visual benefit is high. This checkout exposes an enable checkbox, not the culling-distance slider mentioned in another fork's guide. |
| Terrain Shadows | On | Later exterior A/B, particularly large terrain scenes; check mountain and distant terrain grounding. |
| Terrain Helper | Last log says missing `LandscapeDefault` texture set and disabled | Configuration/asset compatibility finding. Do not count it as a running expensive pass or enable it for FPS. |
| LOD Blending, Terrain Variation, Horizon Fix | Present; variation tiling fix on | Mostly appearance/compatibility; not first-line global FPS levers. Horizon Fix log notes external plugin not detected, which is not itself a performance diagnosis. |
| Grass Collision | On, ragdoll tracking on | Test ragdoll tracking off during crowded combat, then collision off only if measured worthwhile. Grass density generally offers a more direct vegetation workload control. |
| Grass/Foliage Lighting | Scattering on; some ambient/wrapped extras off | Keep initially; these support material appearance. Tuning brightness is not a robust speed improvement. |
| Subsurface Scattering | Burley mode, 16 samples | For NPC-heavy scenes test 8 samples. Check faces/ears in changing light. This feature is distinct from the boot-disabled Advanced Skin feature. |
| Advanced Skin | `Skin` boot-disabled despite saved detail settings | No demonstrated current active cost to remove. Saved sliders do not establish execution. |
| Hair Specular | Enabled, self-shadow enabled | Secondary NPC-heavy test: self-shadow off before removing hair lighting. |
| Extended Translucency | SkinnedOnly true | Preserve unless a measured crowd/transparent-material bottleneck justifies visual compromise. |
| Wetness Effects | Wetness, raindrops, splashes and ripples enabled | In rain, test splashes off or range 1000 → 600 before removing all wetness. Separate dry and wet measurements. Vanilla ripples already off. |
| Water Effects | Loaded | Compare only near/under water; no global-cost conclusion from an empty/null settings section. |
| Unified Water | Boot-disabled | No current optimization to claim by disabling it. |
| IBL, Linear Lighting, Cloud Relight | Their enable values are off | Already avoiding these optional effects. |
| Post Processing | Boot-disabled | Saved tonemapping option is not proof of an active postprocess pass. |
| CS Utility / DOF / bloom enhancement | DOF strengths 0, bloom enhancement off | No basis for promising a large win here. Refraction Scale controls distortion strength, not render resolution. |
| Sky Sync / inverse-square lighting / Fresnel | Sky Sync on; Vanilla Fresnel off | Preserve the established lighting look initially; no evidence these are primary frame-time bottlenecks. |
| Editor, remote control, screenshot, weather picker, Effects11 | Utility/configuration surfaces; weather picker off, Effects11 preset path empty | No evidence of a large active effect workload. Avoid treating feature registration as continuous expensive rendering. |

**VR-specific options and interface traps**

VRS is available in source and its INI is in the 0.5.3 base archive, but the saved profile disables the feature at boot and its internal switch is also zero. Both layers must be addressed to test it. Start with Default rates, default LUT, diagnostics only during verification, and the chosen crop. Full Eye leaves VRS effectively 1×1. The current rate sequences extend to an outer Cull band, so inspect peripheral disappearance, not only blur. The implementation disables VRS around UI and Terrain Blending terrain work; do not promise equivalent savings on every MGO shader or any direct reduction of NR compute work. NVIDIA documents the underlying shading-rate mechanism, but the local implementation and driver diagnostics determine actual activation ([NVIDIA VRS](https://developer.nvidia.com/vrworks/graphics/variablerateshading)).

Both interior and exterior depth culling are already enabled. The saved CS occludee extent is 10; the profile INI also contains 60. Verify the effective runtime value before attributing behavior to the INI. Keep culling on. `bUseHiddenAreaMesh=0` is an additional exploratory lead; the upscaler itself handles hidden-area mask clearing, so enabling the engine setting is not automatically additive or compatible. Test only separately and inspect edge corruption in both eyes.

Full G-buffer stereo optimization is Off. It can omit some second-eye geometry and repair it through depth/G-buffer reprojection. That is a more invasive approximation than AO/SSS stereo reprojection, which is already enabled. The code has pass-readiness and menu guards; those reduce failure modes but do not establish visual correctness for MGO vegetation, disocclusions or NR guides. Keep it off in the first quality-preserving profile.

Stereo Blend is also off. It blends images for consistency; it is not the same geometry-saving technique and should not be enabled as a generic FPS trick.

Reflex was reported available in the last log. Test low-latency mode on, Boost off, FPS limiter off initially. Test marker optimization separately if available. This is primarily latency/queue behavior, not guaranteed FPS. Do not set a desktop 60 FPS cap merely because the saved inactive limiter value is 60.

The central Performance page is useful for finding controls but its global profiles require care: source Performance selects Faster foveated DLSS, while Quality disables foveation. The current NR integration depends on the Default foveated route. Therefore the existing generic profiles are not validated “DLSSNR quality/performance” presets. Balanced also changes multiple upscaling/crop/periphery settings at once. Prefer individual controls for this experiment.

The menu already supports boot-setting differences and restart notices. Keep “Render engine at upscaled resolution” enabled: despite its confusing name, its tooltip/source describe allocating engine targets at the reduced render resolution and writing a separate display-resolution result. It is already working in the last log. Changing engine scale/quality under this mode requires restart in this checkout. Do not follow another fork's hot-switch instructions blindly.

**Compilation, capture, and packaging**

Async compilation, disk cache and skip-unchanged shaders are already on. Developer mode, shader dumps, file watcher and frame annotations are off. These are sensible gameplay settings. Compiler-thread counts affect compilation contention, not a warmed-up shader's GPU cost. Do not clear the cache repeatedly for a benchmark; wait for compilation and let clocks/streaming settle before collecting data.

Partial Precision is off. Its toggle sets `D3DCOMPILE_PARTIAL_PRECISION` and clears the shader cache. The tooltip's broad FP16/throughput claims are not evidence that this FXC/driver path yields a 2× speedup on the 5070 Ti. Keep it as a later shader-disassembly and visual A/B experiment, especially for depth, temporal and high-dynamic-range math. Avoid Flow Control is another compiler experiment, not an all-purpose optimization.

OpenNR capture is enabled as a capability, but that does not mean recording starts automatically. The source uses explicit recording/hotkey requests; the last session contains many actual capture starts. For gameplay measurement, stop recording and set capture capability off, or use the base package in an isolated test profile. Otherwise GPU readback, render-thread mapping, CPU encoding and disk writes can contaminate frame-time spikes. Preserve the capture profile and output data. The configured output path is outside MO2 overwrite/Root.

The base 0.5.3 archive's listing includes FSR frame-generation and StreamlineDX12/DLSS-G files, even though `docs/DISTRIBUTION.md` describes the current pair as omitting them. This is a verified package/documentation mismatch. It warrants a manifest check and corrected packaging/documentation; deleting inactive DLL files is not a demonstrated frame-time optimization. Likewise a saved `frameGenerationMode=1` is not evidence of VR frame generation: the normal UI is gated to non-VR. Compositor reprojection is a separate system.

**MGO outside Community Shaders**

The selected list already includes Output VRAMr, VRAMr, Lightened Skyrim, H.O.A. occlusion content and Engine Fixes VR. Their presence does not prove ideal asset coverage, but reinstalling them is not a newly discovered FPS trick. SkyrimNet and IntelEngine are disabled in this profile; do not attribute its current workload to those systems.

Grass Density - Quality is enabled. Its Freak's Floral Veil INI uses `iMinGrassSize=70`, `iMaxGrassTypesPerTexure=15`, and fade range 8000; SkyrimPrefs has grass start/max fade 7000. Higher minimum grass size generally means sparser grass. A deliberate 85 then 100 trial across the applicable grass plugin INIs is preferable to an indiscriminate renderer downgrade. Only the Quality density folder was found here; do not assume an installed Performance alternative exists. Test distance separately, and watch LOD transitions.

Large draw-distance, object/actor and LOD workloads may bottleneck the 7800X3D even when lowering NR helps the GPU. Compare CPU and GPU application timings in a populated city and dense forest. Do not blindly raise Papyrus budgets, change generic threading INIs, or regenerate all DynDOLOD output as a first response.

The OCU mod is disabled in the selected MO2 list. Its stored configuration is not proof of current OpenComposite use. Current SteamVR/Meta/Virtual Desktop resolution, refresh rate and reprojection settings remain unverified. Choose one deliberate resolution/upscaling chain and record the resulting per-eye target; avoid accidental stacking. Resolution percentages across applications are not always defined the same way.

**External guidance compared with this build**

The current [MGO Community Shaders guide](https://synergyvr.org/mgo/performance/community-shaders/) recommends keeping depth culling, offers DLSS Quality or lower as GPU demands require, discusses Reflex, and identifies Skylighting as a potential cost. Those are useful priorities, not measurements of this DLSSNR build. Its descriptions of other fork UI controls and live render-scale switching do not all match the inspected code. This audit therefore uses local source for exact labels, dependencies and restart behavior, and does not transfer its quoted millisecond costs to this machine.

**Recommended first test configuration**

Use an isolated test profile with 0.5.3 verified as the winning DLL/shader owner. Retain the original capture/game profile. Establish baseline with current settings and capture inactive, then measure each change independently:

1. DLSS Quality, engine reduced-target mode on, Default foveated DLSS, full eye, NR100, single pass. This is the comparison baseline, not the intended final cost target.
2. Try Nasal70/Oval/Feather/falloff1 at NR100. Independently compare FullEye/NR90. Pick the approach whose visual compromise is less noticeable in the actual headset.
3. Set intensity/tone/structure to 1.7 if preferred visually; do not credit this as model-work reduction.
4. Shadow manual budget 2 ms, with 3 ms as the compromise if update lag appears.
5. Volumetric Lighting Medium both environments; restart.
6. If a crop is accepted, try SSR foveation, then FOV Screen Space Shadows, then VRS Default as separate steps.
7. Reflex low latency on, Boost off; compare responsiveness and frame-time tails.
8. Only after these, trial Skylighting, AO samples, rain extras, grass and shadow resolution according to which scenes remain slow.

A combined candidate is only accepted after repeating the benchmark; individual savings are not additive when the CPU/GPU bottleneck changes.

**Measurement and acceptance plan**

At 72/80/90/120 Hz, native application frame deadlines are approximately 13.89/12.50/11.11/8.33 ms. CPU and GPU stages overlap, so compare their timings rather than summing them mechanically. Compositor/encoding cost and scheduling margin also matter. A steady reprojection ratio can feel better than repeatedly crossing its threshold, but synthetic frames are not equivalent to native application FPS or lower input latency.

Use four repeatable 60–90 second scenes: a crowded lit interior, a city traversal, dense forest/grass with turns and strafes, and rain/water with combat effects. Fix save, weather, time, route, render target, headset refresh, runtime and reprojection policy. Warm shaders and assets first; measure A/B/A at least once to detect drift.

Record application CPU and GPU median/p95/p99 frame times, delivered/reprojected/dropped frames, total VRAM usage and any budget pressure, renderer pass costs, and the active NR route/model dimensions/pass count. Capture startup/resource-recreation pauses separately from warm steady rendering. Use the existing profiler for localization, but remember parent/child timing rows overlap. D3D11 timestamps around D3D12 interop cannot automatically isolate model inference from queue waits; end-to-end headset/application timing remains the acceptance metric.

Reject a performance comparison if NR falls back or ceases applying. The last log contains six repeated full-eye dispatch failures around 22:01:24–25, followed by fallback to standard DLSS. This proves transient route failure in that session, not its cause or continuous failure. Investigate whether it coincided with settings recreation, menus or resource pressure before drawing an FPS conclusion.

Visual acceptance must include left/right eye agreement, thin geometry and grass shimmer, hands/weapons crossing the crop, bright/dark doorway disocclusions, moving shadows, wet reflections, UI/text and loading/menu transitions. Static screenshots alone do not settle these tradeoffs.

**Implementation and interface improvements worth scheduling**

- Add an explicit effective-state display: selected versus boot-latched settings; actual engine/display/model dimensions; NR requested versus applied; fallback reason; DLSS mode; VRS active rates; shadow budget mode and effective budget; recording state.
- Make global performance profiles NR-aware. Warn before a profile chooses Faster or disables the route required by NR. Avoid leaving an apparently enabled NR checkbox beside a bypassed runtime.
- Show model-area estimates for crop × model scale, clearly separated from measured timing. Explain that Oval controls blending rather than elliptical model evaluation.
- Expose cropped NR staging-copy cost in profiler labels, and display the `staged-uav` status. A safe direct-UAV path is an engineering candidate only if profiling justifies it.
- Warn clearly when VRS is disabled at boot or Full Eye makes its rate reduction ineffective. Explain its outer cull band and Terrain Blending exclusions.
- Clarify Manual versus Formula shadow controls, and do not imply the unused expression is active.
- Correct package manifest/documentation disagreement. Include build provenance that covers the dirty source state; archive labels and old HEAD are insufficient on their own.
- Qualify the Partial Precision tooltip: compiler hints do not guarantee native FP16 instructions or a particular throughput gain.

**Source navigation**

All paths below are under `D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d`:

| Area | Source and useful entry points |
|---|---|
| Settings layering | `src/State.cpp:486` |
| Engine render scale | `src/Features/Upscaling.cpp:273` |
| Global upscaling profiles | `src/Features/Upscaling.cpp:402` |
| NR UI/model resolution | `src/Features/Upscaling/FoveatedRender.cpp:400` |
| Nasal70 preset | `src/Features/Upscaling/FoveatedRender.cpp:74` |
| NR compatibility and stereo output | `src/Features/Upscaling/NeuralRendering/Integration.cpp:450` |
| Model scaling and resolve | `src/Features/Upscaling/NeuralRendering/Renderer.cpp:179`, `:624` |
| GPU synchronization | `src/Features/Upscaling/NeuralRendering/D3D12Interop.cpp:159` |
| VRS limitations/UI | `src/Features/VRS.cpp:13`, `:74` |
| SSR foveation | `src/Features/VR/SettingsUI.cpp:168` |
| Shadow budget | `src/Features/LightLimitFix/ShadowScheduler.cpp:1664` |
| Shadow enum mapping/restart fields | `src/Features/LightLimitFix/ShadowCasterManager.h:300` |
| AO | `src/Features/ScreenSpaceGI.cpp:98`, `:250` |
| Screen-space shadow stereo and foveation | `src/Features/ScreenSpaceShadows.cpp:120` |
| Volumetric quality | `src/Features/VolumetricLighting.cpp:29` |
| Stereo geometry guard | `src/Features/VRStereoOptimizations.cpp:104` |
| Capture activation | `src/Features/OpenNRCapture.cpp:425` |
| Partial precision / refraction UI | `src/Menu/AdvancedSettingsRenderer.cpp:140`, `:686` |
| Performance hub | `src/Menu/PerformanceRenderer.cpp:155` |

No live gains are claimed by this report. The next meaningful evidence is a controlled in-headset A/B with verified NR application and stable rendering state.
