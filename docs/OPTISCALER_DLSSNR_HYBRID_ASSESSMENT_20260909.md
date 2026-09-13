# OptiScaler DLSSNR pre-SR multipass v0.7.1-hybrid assessment — 2026-09-09

Source: https://github.com/wilsjo2/OptiScaler-DLSSNR-PreSR-Multipass/releases/tag/v0.7.1-hybrid

## Decision

**Research-only / hold. Do not install into the known-good MGO/Open Shaders path and do not use its output as native Feature 18 training labels.**

The release is potentially useful as an isolated runtime comparison because the project exposes Neural Rendering placement before DLSS Super Resolution, one-to-three-pass processing, per-pass history, and a Blackwell FP8/NVFP4 model selector. It is not a replacement for the pinned Open Shaders Feature 18 teacher, an OpenNR student checkpoint, or a validated Skyrim VR integration.

## What the release actually provides

The v0.7.1-hybrid release was published on 2026-09-08 at commit `ec96f42`. Its stated changes are:

- a selector containing the original NVIDIA FP8 path and an experimental FP8/NVFP4 hybrid;
- a measured complete NR-pass reduction of approximately 1–2% at 4K on Blackwell, explicitly not a game-FPS claim;
- removal of async NR and the abandoned NVFP4 modes;
- startup-crash handling when NVIDIA overrides replace bundled Streamline plugins;
- retention of the v0.7.0 Vulkan and compatibility work.

The package includes packed hybrid weights and compiled kernels, but still requires a separately obtained original NVIDIA Neural Rendering runtime. The release describes itself as experimental and says final Baldur's Gate 3 gameplay acceptance remains pending.

## Relevance to this project

Our RTX 5070 Ti is a Blackwell target, so the hardware class is relevant. The potentially useful observations are:

1. whether the hybrid selector changes output quality, temporal behavior, or GPU cost on a controlled scene;
2. whether guarded pre-SR placement gives a useful comparison against post-SR placement;
3. whether multipass history and final composition expose instrumentation ideas for our runtime/capture diagnostics;
4. whether the startup fix is relevant to an isolated OptiScaler process on a disposable test target.

Those observations would be separate experiment records. They would not change the native teacher label, training split, or accepted runtime.

## Why it is not an immediate OpenNR path

- The repository's verified example is Baldur's Gate 3; its compatibility statement is generic to 64-bit games whose upscaler call reaches an OptiScaler D3D12 path, including D3D11/Vulkan bridges. I found no Skyrim VR validation in the release or repository documentation.
- Skyrim VR is our D3D11 renderer with a separate D3D11/D3D12 Feature 18 interop boundary. A proxy that intercepts an upscaler call does not prove ownership of Skyrim's native depth, motion-vector, reset, per-eye, history, or SteamVR/OpenXR compositor contract.
- A hybrid result is not necessarily the same teacher distribution as the pinned NVIDIA/Open Shaders Feature 18 output. Mixing it into native teacher labels could teach a different model or runtime route while looking like a small MAE change.
- Installing a proxy DLL, forwarder, or alternate runtime beside MGO could create a second owner for the same render path and invalidate the current capture provenance. The repository itself requires a complete package, a separately sourced runtime, a game-specific proxy choice, and backups.

## Safe follow-up, if later justified

Use a disposable copy or non-MGO DX12 test target. Preserve the exact package hash, commit, runtime hash, driver, proxy name, INI, model selector, pass count, input/output resolution, and whether the route is pre-SR or post-SR. Capture same-frame A/B output and GPU timings with NR off, stock FP8, and hybrid FP8/NVFP4. Keep the results in a separate manifest and do not promote them unless they pass independent image, temporal, stereo, and VR-budget checks.

The current priority remains the version-matched native Feature 18 capture and TensorRT validation. This release may be revisited as a bounded runtime/instrumentation comparison after those gates, but it does not justify pausing or replacing the existing teacher path.



## FP8 teacher versus FP16 student

“DLSSNR is FP8” describes a low-precision inference path, not a requirement that a distilled student must also use FP8. The release label does not establish that every internal tensor, activation, accumulator, input, or output is FP8. In mixed-precision inference, FP8 tensors can use scale metadata and higher-precision accumulation; the exact NVIDIA kernel contract is private.

The current OpenNR student plan is intentionally staged:

- training uses mixed precision for optimization stability;
- the delivery reference is a TensorRT FP16 engine with FP32 reduction preference and FP16/FP32-compatible I/O;
- FP8 is deferred until FP16 visual and temporal equivalence checks pass;
- NVFP4 is a later weight-only experiment, not the first live path.

The student only needs to reproduce the teacher's observed input/output and temporal behavior. It does not need to share the teacher's internal numeric format. A higher-precision FP16 student can learn an FP8 teacher's output distribution; lowering the student to FP8 early would add quantization error and hidden-state drift before the quality target is met.

The eventual low-precision sequence should be:

1. reach the quality and temporal gates with the FP16 student;
2. build an FP8 candidate with the same FP16 I/O contract first, where possible;
3. calibrate using an immutable train/calibration cohort, never the frozen test cohort;
4. compare FP16 and FP8 on identical reset-qualified sequences, per eye and per frame;
5. require no meaningful regression in ordinary 1x MAE, color error, temporal-delta error, reset/warm behavior, or VR-budget timing;
6. consider NVFP4 weight-only conversion only after FP8 has an accepted baseline.

The v0.7.1-hybrid release's small NR-pass reduction should not be projected onto our student. Its gain comes from NVIDIA's model/kernels and may be dominated by different operations; our small recurrent student may instead be limited by preprocessing, guide/context preparation, D3D interop, or compositor cost.

