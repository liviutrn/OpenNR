# OpenNR 2.19.1: audit and Skyrim VR optimization plan

Date: 2026-09-27. Auditor: Claude (read-only source, settings, and report audit). No code, build, profile, or installed file was changed. No game or GPU run was performed. Every gain below is an estimate unless marked *measured*.

## 0. What "2.19.1" actually is

| Item | Location / value |
|---|---|
| Source | **Uncommitted** worktree `C:\Users\oleks\.codex\worktrees\opennr-2190-result-shaping\OpenNR-VR` (16 modified files, 5 new). `main` is still 2.18.0 (`8a30b22`). |
| Build | `E:\OpenNR_Builds\2.19.1` (CMake source dir confirms the worktree above); archive `dist\OpenNR 2.19.1.7z` (228.75 MB) |
| Install | MO2 mod `OpenNR 2.19.1`, profile `MGO NSFW - OpenNR 2.19.1` |
| Currently selected MO2 profile | `MGO NSFW - OpenNR V5 Turbo4-R16 HMD Test 20260927` (the V5 track, not 2.19.1) |
| 2.19.0 changes | Optional post-NR result shaping, per-eye stabilizer (Off/Static/Motion), NR status control, a DevBench query |
| 2.19.1 changes | NR menu reorganized, Strong preset removed (saved Strong maps to Custom), tooltip width cap |

The NR path in 2.19.1 is NVIDIA's Feature 18 (DLSS-NR 310.8) behind a D3D11→D3D12 shared-texture/fence bridge. It runs per eye after DLSS on the full-eye output (2496×2688). The V5 replacement graph is a separate, also uncommitted track. It is already covered by `E:\OpenNR_Research\CLAUDE_ONBOARDING_AUDIT_20260927.md`; this report only adds a few V5 notes in §7.

## 1. Where the frame time goes (measured, from your reports)

| Quantity | Value | Source |
|---|---|---|
| Game with NR off | ≈27.3 ms (36.6 FPS) | Sep 26/27 screenshots |
| Native Feature 18, stereo | 23.3–24.4 ms (11.66 ms/eye isolated) | Sep 23 bench, Sep 26 in-game |
| Frame with native NR | ≈45–48 ms (21–22 FPS) | Sep 26 screenshots |
| V5 / Turbo4-R16 stereo | 44.9 / 42.1 ms | Sep 27 timing logs |
| SteamVR target | 72 Hz (13.9 ms); 36 FPS half-rate line is 27.7 ms | vrcompositor log |

The frame is GPU-serial: NR time adds almost one-for-one to frame time. Even with NR free, the game alone sits at the 36 FPS line. **Winning in VR therefore needs two things: NR must get much cheaper, and the base game must drop a few ms.**

**Cost model used in this report.** External RTX 5070 Ti NGX figures (DLSS5-NeuralScreen: 2.90 ms at 0.92 MP, 4.60 at 2.07, 7.10 at 3.69) fit **per-eye ≈ 1.2 ms + 1.6 ms/MP**. That predicts 11.9 ms/eye at 6.71 MP, which agrees with your measured 11.66 ms. `DLSSNR.ScalingRatio` is reported inert; only real input-area changes move cost.

## 2. Bugs found (fix these first)

### B1 — High: VR pre-upscale NR sends motion vectors about 1,500× too small

- The post-upscale route passes `motionScale * guideWidth`, converting UV motion vectors to pixels (`Integration.cpp:688`).
- The VR pre-upscale route passes **`1.0f`** (`Integration.cpp:507-508`) for the same UV-unit vectors (`vrIntermediateMotionVectors`, written by `EncodeTexturesCS` / `PreparePerEyeInputs` in UV).
- The flat pre-upscale route correctly uses `motionDesc.Width`.
- Result: Feature 18 in VR pre-upscale mode sees almost no motion, so ghosting and smearing are expected during head motion. This likely explains why the biggest performance lever (§3, P2) never looked acceptable.
- Fix: `.motionVectorScaleX = static_cast<float>(eyeWidth)` and `.motionVectorScaleY = static_cast<float>(eyeHeight)`.
- Second pre-upscale gap: Feature 18 receives the **jittered** render-resolution image with no jitter information, which may cause shimmer. Test after the MV fix.

### B2 — Medium: temporal reuse and the new Motion stabilizer under-scale motion by about 41%

- The C++ side passes motion scale in **guide pixels**.
- `AdaptiveHandoffCS.hlsl:44-47` correctly multiplies by `colorSize/guideSize`.
- `TemporalReuseCS.hlsl:94` and `ResultShapingCS.hlsl:248` do not, and add guide-pixel motion to color-pixel positions.
- In the VR post-upscale route, guide width is 1468 and color width is 2496, so only 59% of the true motion is applied.
- Result: reprojected history lags during head turns. The depth and color gates then reject much of it, so the stabilizer/reuse looks flickery or does nothing.
- Fix: apply the same `guideToColor` factor in both shaders, or pass a color-pixel scale from `Renderer.cpp`. Add a unit fixture where guide ≠ color; no test currently covers MV scaling.

### B3 — Medium: stabilizer mixes shaped and unshaped deltas

- In `ResultShapingCS.hlsl:265-267`, `delta` is the *shaped* delta, while `currentLowFrequency` is recomputed from the *raw* NR delta. History comes from the previous *shaped + stabilized* output.
- With shaping enabled (for example Edit strength 0), the output becomes `w·(prevLF − curLF)`, which re-injects NR effect the user turned down.
- Fix: stabilize in one domain. Either compute low-frequency terms from the shaped delta, or stabilize the raw delta first and then shape.

### B4 — Low: release hygiene

- 2.19.x and V5 exist only as uncommitted worktree state. Commit on a branch and tag `v2.19.1` so the shipped DLL is reproducible.
- Stray `semantic_trt_*.obj` files sit in the repo root.

## 3. Performance opportunities, ranked for Skyrim VR

Savings are stereo ms per frame from the cost model, against about 24 ms of native NR.

| # | Change | Est. saving | Look risk | Effort |
|---|---|---|---|---|
| **P1** | **NR-only center crop.** Keep DLSS full-eye; run Feature 18 on a centered subrect at 100% model resolution and feather-blend onto the DLSS image. | 85%: **−6 ms**; 80%: **−7.7 ms**; 70%: **−11 ms** | Low in the center, where you look; periphery keeps DLSS quality (no stretch) | Medium |
| **P2** | **Pre-upscale NR after the B1 fix** (NR at 1468×1580, then DLSS) | **≈ −14 ms** | Medium to high: this is a reduced neural grid, which you parked before; needs a jitter check | Small (the fix) plus an A/B |
| **P3** | **Eye-staggered reuse:** alternate which eye gets native Feature 18 each frame; reproject the other eye's residual | **≈ −11 ms**, flat per frame | Medium (stereo mismatch on fast motion); needs B2 | Medium |
| P4 | Fixed 90–95% model tier with the existing matched-residual resolve | −2 to −4 ms | Low to medium | None (setting) |
| P5 | Lower VD/SteamVR per-eye output from 2496×2688 toward about 2208×2376 | ≈ −4.7 ms NR, plus DLSS/post savings | Some clarity loss | None (setting) |
| P6 | Zero-copy DLSS→NR: make the per-eye DLSS output the NR shared input; drop the `FinalizePerEyeOutputs`→`kTOTAL`→`eye.color` round trip | −0.3 to −0.6 ms | None (exact) | Small to medium |
| P7 | Single SBS Feature 18 evaluation (one handle, 4992×2688) to remove one fixed ~1.2 ms overhead | ≈ −1 ms (uncertain) | Seam risk; may improve stereo tone consistency | Small (experiment) |
| P8 | Stabilizer history ping-pong instead of three full-eye `CopyResource` per eye per frame (`Renderer.cpp:1777-1780`) | −0.2 to −0.4 ms when on | None | Small |
| P9 | Build with LTCG/IPO (`tools/Build-OpenNR.ps1:50` forces `IPO=OFF`; upstream ships with `/GL /LTCG`) | CPU-side only, a few % of plugin CPU | None | Small (check CommonLib prebuilt compatibility) |
| P10 | Construct `SignedRuntimePathScope` in `EnsureFeature` only when a feature is actually created (`Runtime.cpp:313` currently runs before the handle check at `:327`); cache `GetProcAddress` results | Tens of µs CPU per frame; removes per-frame IAT patching | None | Trivial |

### P1 detail: the best fit for your "full-resolution look" goal

- Today, a crop means **DLSS itself is cropped** and the periphery is a stretched render-resolution image (`FoveatedRender.h` header comment; `Integration.cpp:604-607` takes subrect guides only when not full eye).
- An NR-only crop keeps every pixel DLSS-quality and applies NR at native resolution in the central region.
- Building blocks already exist: stereo subrect inputs (`sourceX/Y`), `BlendSubrectToOutput` feathering, crop-local temporal history, and fixed resource envelopes.
- What's new is cropping the full-eye guides:
  - copy the depth/MV subrect with `CopySubresourceRegion`, or set the NGX subrect bases that `Runtime.cpp:404-429` already publishes as zero;
  - use motion scale `1/uv.w` times the crop guide width, exactly as `ComputeMvecScale` already does.
- Quest 3 users mostly look within about ±15° of lens center, so 80–85% coverage should be close to invisible with a 128 px feather. Your settings already use feather 128 and dither.

### P3 detail

- Current temporal reuse (N2) skips **both eyes on the same frame** (`Renderer.cpp:961-967`). Frame time then alternates between about 48 and 26 ms, which is bad VR pacing.
- Staggering the eyes gives a constant cost of about 12.4 ms.
- Keep `resetAfterSkip` semantics per eye and evaluate stereo disagreement.

## 4. Base-game cost: your current settings

From `E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json`:

| Setting | Current | Recommendation |
|---|---|---|
| **Disable at Boot → VRS** | **disabled** | The 2.17 VRS ring default has had no effect for you. Re-enable and A/B (peripheral shading savings). If you disabled it because of artifacts, note which. |
| **Disable at Boot → Grass Optimizations** | **disabled** | Culling and mid/far LOD are off. Re-enable and A/B in dense exteriors. |
| Performance Overlay | CS passes, draw calls, VRAM and graphs on | Adds GPU timestamp queries per pass and a VR ImGui draw. Close it when judging smoothness. |
| VR SSR foveation | off | Test `EnableSSRFoveation`. |
| Screen Space Shadows foveated | off | Test `EnableFoveated`. |
| Subsurface Scattering | Burley 16 samples | Test 8. |
| Volumetric Lighting | quality 2 | Test 1 separately (plan rank 5). |
| DLSS | Balanced, preset Default (transformer) | Only J/K/L/M are exposed. If DLSS 310.8 still honors a CNN preset, it would be materially cheaper; worth a 5-minute probe. |
| NR | 100%, full eye, intensity/structure/tone 2.0, resolve mode 1 | Keep as the look reference; A/B against P1 at 85%. |

## 5. Code-quality notes (no action required)

- **D3D11/D3D12 bridge.** `D3D12Interop.cpp` is sound: GPU-side fences, three rotating allocators, CPU wait only for backpressure. One detail to verify in PIX: no `Flush()` follows `context11->Signal`. Most drivers flush on `Signal`; if yours does not, D3D12 can start late.
- **Per-frame NR glue** (post-upscale, per eye):
  - one color copy in, a depth-convert compute pass (on data that is already R32), an MV copy, and one copy out;
  - together about 0.5–1 ms stereo, or 2–4% of NR;
  - P6 removes most of it.
- **Adaptive controller** logic is reasonable. With a 72 Hz setting and target 0, it aims at 36 FPS (27.8 ms), which your current game cannot reach even with NR off. Adaptive NR will sit at its 70% floor unless P1/P5 land.

## 6. Recommended order

1. Fix B1, B2, B3 (small, exact changes) and add guide≠color MV unit fixtures. Commit 2.19.1 on a branch; tag it.
2. Settings-only A/B on the 2.19.1 profile, one change at a time, same save and route, 60 s blocks alternating:
   - re-enable VRS;
   - re-enable Grass Optimizations;
   - overlay closed;
   - NR at 95% and 90%.
3. Build **2.20.0-exp: NR-only center crop (P1)** with coverage 100/90/85/80 and zero-copy (P6). This is the main recommendation: roughly −6 to −8 ms at full NR resolution where you look.
4. After the B1 fix, run one pre-upscale A/B (P2) purely to see whether the ~14 ms saving looks acceptable. If not, park it with evidence rather than on a broken implementation.
5. Only then try eye-staggered reuse (P3) and single-SBS evaluation (P7).

**Realistic target:** about 46 ms → **36–38 ms** with P1 at 80–85% plus settings (roughly 27 FPS). Reaching a stable 36 FPS (27.7 ms) also needs about 3–5 ms off the base game or output resolution (P5).

## 7. V5 notes (supplementing the existing V5 audit)

- An NR-only center crop (P1) applies equally to V5 if the graph accepts a non-full-eye extent, which today passes through when cropped. At 80% it would take about 36% off V5's 35 ms of graph time: a bigger lever than any kernel knob measured so far.
- The right-eye bimodal slowdown together with 85–92% VRAM budget points to WDDM residency/paging as a strong candidate. Log `QueryVideoMemoryInfo` per frame and try swapping eye order, as the V5 audit suggests.
- B2's lesson applies to any future V5 temporal shell: keep MV units explicit (guide px vs color px) in one helper, not in each shader.

## Evidence index

- Source: worktree above; `Integration.cpp`, `Renderer.cpp`, `Runtime.cpp`, `D3D12Interop.cpp`, `FoveatedRender/Core.cpp`, `Bridge.cpp`; shaders `ResultShapingCS`, `TemporalReuseCS`, `AdaptiveHandoffCS`, `EncodeTexturesCS`.
- Build: `E:\OpenNR_Builds\2.19.1\CMakeCache.txt`, `build-opennr.cmd`.
- Reports: `docs/OPENNR_VR_PERFORMANCE_PLAN_20260924.md`, `docs/OPENNR_2.18.0_RELEASE_20260924.md`, `reports/OPENNR_FULL_RESOLUTION_PERFORMANCE_DECISION_20260923.md`, `docs/PUBLIC_B580_FAST_PATH_CUDA_PROBE_20260912.md` (external NGX timings), `C:\OpenNR\Reports\V5_*_2026092[67]`, `E:\OpenNR_Research\CLAUDE_ONBOARDING_AUDIT_20260927.md`.

## Addendum — what 2.20.0 implemented (2026-09-27)

Direction from the project owner: any NR resolution below 100% is a no-go, because it weakens the neural effect.

| Item | 2.20.0 outcome |
|---|---|
| B1 pre-upscale MV scale | Fixed. The route itself is locked off (it runs NR at render resolution). |
| B2 reuse/stabilizer MV scale | Fixed in C++ (`GuideToColorMotionScale`, unit-tested). |
| B3 stabilizer domain mix | Fixed: stabilize the raw delta, then shape; history holds the stabilized, unshaped result. |
| B4 commit/tag | 2.19.1 committed and tagged; 2.20.0 committed and tagged. V5 and research work committed on separate branches. |
| P1 NR-only center crop | Implemented as **NR Coverage** (95–70%, default Full eye). |
| P2 pre-upscale NR | No-go (below 100% NR resolution). Locked off. |
| P3 eye-staggered reuse | Implemented (**Stagger eyes**, N2 only, default off). |
| P4 reduced tiers, P5 lower output resolution | No-go. Model resolution locked at 100%; adaptive NR (and the adaptive crop that needs it) disabled. |
| P6 zero-copy DLSS→NR | **Withdrawn.** The NR input is the LDR image *after* post-processing (`FoveatedLdrBeforeUI`), not the DLSS output, so the round trip cannot be removed. The small copy saving that *is* available was taken: an R32 depth-guide region copy replaces the conversion dispatch. |
| P7 single SBS evaluation | Not implemented. The model has global (1/64-scale) attention, so one SBS evaluation would couple both eyes' tone. That changes the look for about 1 ms of possible saving. |
| P8 stabilizer ping-pong | Implemented (one full-eye copy per eye per frame removed). |
| P9 LTCG | Enabled for the 2.20.0 package build. |
| P10 NGX proxy scope | Scope now installed only on feature creation (evaluate keeps its own). |
| Performance Overlay | Removed from the OpenNR build (`OPENNR_PERFORMANCE_OVERLAY=OFF`). |
| Grass Optimizations | Enabled at boot in the shared MO2 `SettingsUser.json` (backup kept). By design it culls and LODs grass; the in-game gain is unmeasured. |
