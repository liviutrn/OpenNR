# OpenNR shader and settings analysis: what NR can pick up, and what it can't

Date: 2026-09-27. Scope: every loaded Community Shaders / OpenNR feature in the MGO Skyrim VR profile, the game INI, and DLSS, judged against the Feature 18 ("DLSS 5 NR") effect. Output: OpenNR 2.20.1 (a live A/B benchmark plus DLSS CNN presets) and a ranked test list.

## 1. What your frame actually costs (measured)

The source is the per-pass GPU timings in your Performance Overlay screenshots (Steam, Sep 24–27, 2496×2688 per eye output, DLSS Balanced from 1468×1580). The overlay's per-shader-type table is CPU-timed (QueryPerformanceCounter around draws), so only the named passes below are GPU time.

| Pass | GPU ms | Notes |
|---|---:|---|
| NeuralRendering::EvaluateStereo | 24.4–24.6 | Feature 18, both eyes, full resolution |
| Upscale::Upscale (DLSS SR, both eyes) | **4.1–5.8** | Transformer preset K (the Balanced default) at 2×6.7 MP output. The Sep 24 value of 2.06 ms was Ultra Performance, so it isn't comparable. |
| Grass::Draw | 1.97–2.20 | Real grass raster; Grass Optimizations was disabled at boot until 2.20.0 |
| TerrainBlending::RenderPasses | 1.05–1.62 | Mostly the terrain lighting draws themselves, deferred into this pass; the real extra is the terrain depth pass |
| SCM:Rnd:Sun (sun shadows) | 0.58–0.98 | |
| Effects (engine particle/decal accumulator) | 0.45–0.49 | Game content, not Effects11 |
| PerfMode tonemap / refraction / downscale | 0.4 / 0.17 / 0.14 | |
| Deferred composite | 0.23–0.31 | |
| SSGI upsample (AO only) | 0.21 (one 0.96 outlier) | |
| SSS Burley + ray march | 0.04–0.16 + 0.11 | |
| Screen-space shadows stereo sync | 0.11 | |
| Skylighting occlusion mask | 0.06–0.10 | |
| Volumetric shadows downsample | 0.04 | |
| Encode textures (DLSS inputs) | 0.13–0.16 | |

The whole frame is about 27.3 ms with NR off and 45–48 ms with native NR. Point-light shadow redraws, G-buffer/lighting draws, water, sky and volumetric lighting are not broken out in the visible pass list.

## 2. The pasted "dial back in favor of NR" claims, checked

| Claim | Verdict |
|---|---|
| NR "replaces noisy screen-space filters with an AI model trained on offline renders" | **Wrong model.** That describes DLSS Ray Reconstruction, which replaces RT denoisers and is fed noisy lighting signals. Feature 18 NR is an image-to-image look model applied after tonemapping (`FoveatedLdrBeforeUI`), on colour, depth and motion only. It never sees AO, SSR or volumetric buffers, so it cannot denoise them. With Local Structure 2.0 and Intensity 2.0 it **amplifies** high-frequency detail, so leftover noise can get *more* visible. |
| SSGI/AO "saves ~0.8–1.0 ms" | Your measured SSGI upsample is ~0.2 ms, AO is already AO-only at 2 slices / 4 steps (2.17 defaults), and it already uses stereo reprojection. The real saving is probably a few tenths of a ms. NR does add contact-like shading on faces and cloth (seen in the V5 on/off shots), so **lighter AO is a fair look test**, not a free win. |
| SSR "Balanced 64–128 steps saves ~0.6 ms" | SSR on/off is restart-gated and VR SSR foveation does nothing at Full Eye. NR cannot recreate missing reflections. Unmeasured. |
| Volumetric "medium density saves ~0.4 ms; NR smooths banding" | Quality 2 → 1 applies live, so it is now a benchmark variant. NR does not dither the volumetric buffer; banding reduction is not established. |
| Stabilizer "eliminates left/right stereo shimmer" | **False.** It is a per-eye temporal filter with no cross-eye term. It helps temporal shimmer within an eye and can't fix disparity. |
| "Reclaim 2.2–2.6 ms → 9.0–9.8 ms, rock-solid 90 FPS" | **Not achievable here.** The game alone measures ~27 ms, and NR adds ~24 ms. Even every screen-space effect in the table combined is under 1 ms. |

## 3. Where the real levers are

Ranked by expected value. None of these reduces NR resolution.

1. **Point-light shadow redraw budget (Light Limit Fix).**
   - Your config is Manual, **5 ms per frame**, up to 16 redraws, 8192 atlas, 32 converted slots.
   - The shipped Formula mode gives `1 + isinterior` ms (1 ms outdoors, 2 ms indoors).
   - In villages and interiors this is likely the biggest non-NR saving. Lights still cast shadows; distant or static ones refresh less often, and moving casters can lag.
   - Benchmark variants: *Formula* and *8 redraws / 2 ms*.
2. **DLSS model preset.** K costs 4.1–5.8 ms for both eyes.
   - J costs about the same as K (per NVIDIA).
   - The CNN presets E/F are deprecated but still in the 310.x SDK, and typically cost roughly half.
   - NR re-synthesizes detail on top of DLSS, which makes CNN softness the most plausible "NR picks up the slack" trade. CNN ghosting on thin detail is not something NR fixes.
   - 2.20.1 adds E/F; the benchmark measures whether the runtime honours them.
3. **DLSS quality mode (restart).**
   - Balanced → Performance renders 1248×1344 instead of 1468×1580 (−28% pixels). Every render-resolution pass (G-buffer, lighting, SSGI, SSS, shadow mask, volumetrics) shrinks.
   - NR stays at 100% display resolution; the Performance default preset is M.
   - This is the classic place where a detail model helps. Compare across two sessions.
4. **VR Stereo Reprojection (restart, experimental, off).** It stencil-culls Eye 1 pixel shading where it can reproject from Eye 0, restores the G-buffer, and still lights both eyes natively. Potentially 1–3 ms in geometry-heavy views; watch alpha-tested foliage and edges.
5. **Grass.** Grass Optimizations is now enabled at boot (2.20.0). Mesh LOD is a benchmark variant.
6. **NR Coverage 85/80%** (2.20.0). Estimated −6 to −8 ms, and it's the only large NR-side lever that keeps 100% model resolution.

### Low value: keep these

SSS, screen-space shadows, Skylighting occlusion, volumetric shadows, wind and grass collision each measure ≤0.2 ms. Turning them off would cost visible quality for savings below the frame-to-frame noise.

### Optional, manual

- `bDoDepthOfField=1` in SkyrimPrefs.ini: set 0 if you never want DoF in VR.
- Advanced → Partial Precision: forces a full shader recompile, and whether DX11 drivers honour FP16 here is uncertain. Only as a one-off comparison.

## 4. What 2.20.1 adds

- **Settings Benchmark** on the Neural Rendering page, plus DevBench commands.
  - Each variant is applied live through the same settings-patch path DevBench uses, left to settle, then timed per frame with SteamVR `GetFrameTiming` (application GPU = pre+post submit), with CPU recorded too.
  - Every variant is bracketed by baseline blocks, so drift shows up as the reported uncertainty. Repeats run in reverse order.
  - Menus and loading screens pause and restart the current block.
  - Your settings are restored and never saved. Rows have **Apply** for a live look test.
  - The report is JSON in `SKSE/OpenNR-SettingsBenchmark/`, and variants are editable in `OpenNR-SettingsBenchmark.json`.
- **DLSS presets E and F.**

## 5. How to use it

1. Load the 2.20.1 profile. Stand in a representative, heavy spot (a village with torches is ideal for the shadow budget). Open Neural Rendering → Settings Benchmark → Start, close the menu, keep your head still for about 3 minutes.
2. Look at the green rows (saving larger than drift). Press Apply on one, judge it in the headset, and Save Settings if you keep it.
3. For restart-gated levers (DLSS quality mode, Stereo Reprojection), run the benchmark once per setting and compare the baseline medians in the two JSON reports.
