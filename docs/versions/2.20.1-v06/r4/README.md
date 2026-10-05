# OpenNR 2.20.1-v06-r4 — boundary tone matching

**Built and package-audited:** [Download r4](https://github.com/liviutrn/OpenNR/actions/runs/37346929262/artifacts/11361958002) · [Build](https://github.com/liviutrn/OpenNR/actions/runs/37346929262) · [Package audit](https://github.com/liviutrn/OpenNR/actions/runs/37347213177).

Windows shader/DLL compilation and regression checks passed. The package adds one smoothing shader, changes the two existing tone shaders and DLL, removes nothing, and preserves every other r3 payload. Headset quality and GPU cost remain pending.

r4 replaces the inset-dependent outside-tone estimate with local **gain plus offset** matching. It measures the completed NR crop **before the outer crop feather**, so a weak feathered edge does not hide the tone change and a large inset does not borrow tone from a distant surface.

## Changes from r3

- Fit local RGB gain and offset from paired original/NR samples in a narrow strip along the actual rectangle or oval boundary.
- Carry additive shadow lifting, darkening, contrast compression, and broad color changes into the outside band. Black samples are no longer automatically assigned zero confidence.
- Sample the actual shaped/resolved/transition-handoff result used for writeback. Compact sequential passes and temporal-reuse routes retain their own completed output.
- Smooth only the small correction map. The existing scene image, inner feather, and pixels inside the crop are unchanged.
- Retain **Legacy inset gain** as an immediate A/B estimator.
- Add optional outside edge protection, **off by default**. It reduces transfer when an outside pixel differs strongly from the local original reference.
- Include coefficient smoothing in the GPU-cost readout.
- Preserve the r2 gaze geometry/history fix, FPS policy, neural tuning, and native resource contracts.

## Controls

Outside NR tone transfer remains **off by default**. Existing brightness, color, outside width/falloff, boundary ramp, static dither, and gain-limit controls remain live and saved.

| New control | Default | Range | Purpose |
|---|---:|---:|---|
| Tone estimator | Boundary gain + offset | Legacy / Boundary | Compare r3-style gain with local affine matching |
| Brightness offset limit | 0.08 | 0–0.25 | Cap positive/negative per-channel additive correction in the existing LDR representation |
| Boundary sample width | 32 px | 4–128 px | Local inward depth and tangential sampling width |
| Correction map smoothing | 0.50 | 0–1 | Spatial smoothing of coefficients; zero skips this pass |
| Outside edge protection | 0.00 | 0–1 | Optional attenuation across dissimilar outside colors |

The legacy sampling inset affects only the legacy estimator. The new mode samples near the boundary automatically; sample width controls how local the estimate is.

For visual comparison, select **Boundary gain + offset** and try brightness/color at **1.0** first, then reduce them if the transfer is too strong. Keep edge protection at zero initially. If an offset hits its limit, increase the offset limit cautiously; widening the fade spreads the correction farther.

This estimates broad local tone transformations. It cannot reproduce arbitrary neural detail, spatial relighting outside the available crop, or every nonlinear color operation exactly. Scene-dependent differences can still leave a seam or halo.

## Performance and integration

The default boundary mode runs map fitting, optional tiny-map smoothing, and outside application. There is **no new full-image copy, pixel readback, temporal history, or full-image guided filter**.

The coefficient textures occupy 24 KiB of texel payload in total and are reused sequentially for the eyes. Smoothing covers only 16×16 cells. Edge protection is optional; disabling it avoids its extra reference-map sample. Disabling tone transfer adds no new GPU dispatches or allocation. Full-eye and pre-SR routes still skip the effect.

**Measure outside tone GPU cost** reports the sum of active tone passes for both eyes using the existing nonblocking profiler. Initial allocation/shader compilation and query overhead are separate from the steady-state pass measurement. The requested **0.1–0.2 ms** remains a target until measured on the actual GPU.

Changing these controls does not recreate native NR, reset gaze history, or alter FPS-controller decisions. Failure skips the tone effect and retains NR rendering.

Devbench `configureOutsideTone` adds `mode` (0 legacy / 1 boundary), `offsetLimit`, `sampleWidth`, `smoothing`, and `edgeProtection`, with validation before assignment. `outsideToneStatus` returns the new fields. Existing save/load persists them.

## Verification scope

An independent r3-to-r4 replay checks the exact generated-source contract. CPU oracles cover identity, black shadow lifting, gain darkening, negative offsets, contrast compression, tint, invalid/extreme samples, valid rectangle/oval sample positions, outside-only writes, and alpha preservation.

The existing controller, zero-filter gaze, crop-grid, head-motion, and outside-mask suites are retained. CI checks nine CPU/HLSL buffer layouts, compiles the nine involved shaders, and builds/packages the full Windows runtime.

CPU/source checks do not execute native NR or prove headset quality. VR acceptance and GPU cost remain pending.

## Lineage

These are custom OpenNR 2.20.1 checkpoints. OpenNR inherits [Open Shaders](https://github.com/alandtse/open-shaders) and [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders) ([Nexus](https://www.nexusmods.com/skyrimspecialedition/mods/86492)).
