# v43 adversarial review — 2026-10-15

Reviewed production code: `ebee6feae18e4dec437ca173b74a67f5fec8f9d5`, tree `aba6c63f9283c4fc0ff1b652fe98a7421cb8f7ee`. Later documentation changes do not change that binary. The user explicitly requested three independent GPT-6 Luna reviews at maximum reasoning and one GPT-6 Astra review at low reasoning. Reviewers inspected shared read-only source with separate initial contexts; root checked their concrete findings.

## Independent reviewer results

| Reviewer | Model and reasoning | Scope | Verdict |
|---|---|---|---|
| luna_render_math | GPT-6 Luna, max | Geometry, rotation, sampling | Model passes; fixation density regression and runtime gaps |
| luna_integration | GPT-6 Luna, max | Generated UE hooks, frame pairing, state | No confirmed hook/math defect; temporal acceptance unresolved |
| luna_research | GPT-6 Luna, max | OpenNR/Cheeky/Toolkit research, freshness, tests | CAPI rationale justified; composed expiry and timing gaps |
| astra_audit | GPT-6 Astra, low | Independent overall critique | Credible candidate, not demonstrated fix |

All four completed. No reviewer modified production source. The first two were scoped independently; root subsequently shared concrete findings with reviewers for challenge, so later corroboration is not presented as fully blind replication.

## Decision

The architecture is a plausible candidate, not a demonstrated solution to the reported gaze shaking. Passing synthetic geometry and raster checks cannot establish that STALKER 2 consumes correct temporal camera data. No headset validation occurred. No claim of no regressions or unchanged quality is warranted.

## Confirmed findings

1. **Off-center density loss at fixation.** `DuoViewSteering.hpp:26-53,110-115` uses a fixed centered frustum, while `DuoViewGeometry.hpp:57-58,100-110` gives the old off-axis crop linear full-image UV sampling. For horizontal eccentricity theta, the new-to-old horizontal pixels-per-radian ratio at the crop center is `cos(theta)^2`. With P00=0.78, symmetric projection and crop center u=0.75, theta=32.66 degrees and the ratio is 0.709: about 29% fewer samples at fixation. At u=0.85, ratio=0.554. Root independently confirmed the first result using finite differences through the actual homography. Previous documentation saying center angular density was identical was incorrect and is corrected. This is a quality tradeoff, not proof of shaking.

2. **Two cache layers can retain gaze for about 100 ms.** `DuoViewPSVR2Gaze.hpp:152-168` returns a cached mapped UV for up to 50 ms. `DuoViewCropStability.hpp:20-29` treats every returned UV as fresh and then holds it for another 50 ms. Root compiled an independent probe: a real sample at t=0, Reader reuse through t=50, no samples thereafter; the target stays at (0.7,0.4) through t=100 and recenters at t=101. A blink clears Reader immediately, but the crop layer can still retain the previous target. This behavior is inherited from v42. Its component tests do not exercise the full Reader-to-State expiry/blink path. This composed policy should carry freshness/validity explicitly or have one expiry owner. It is not demonstrated to cause the user's world-image instability.

3. **Current temporal diagnostics do not describe actual foveal camera motion.** `DuoViewState.hpp:138-150` compares canonical Mono poses and crop-origin deltas, although v43 rotates the stored source camera. `same_pose=true` can coexist with a changing foveal camera. These fields cannot prove correct foveal history. Consume also precedes successful XR-copy acceptance.

## Unresolved causal and validation gaps

- CAPI device timestamps are not mapped to render/XR time (`DuoViewPSVR2Gaze.hpp:101-102`). The head-turn oracle derives gaze from the exact head quaternion used for that rendered frame (`tests/GazeSteeringOracle.cpp:84-94`), so it does not cover real delayed or repeated sensor packets. Stale gaze can miscenter the high-resolution patch. With exact current camera/homography agreement it does not, by itself, displace world color; actual world jelly needs further camera, timing, history or rendering mismatch.
- Composition does not require distinct persistent UE scene states (`DuoViewState.hpp:124-130`). Sharing would be a temporal risk, but actual sharing in the target game is unobserved. Adding a uniqueness gate alone could force fallback rather than fix history. Even distinct addresses would not prove correct consumed previous transforms or velocities.
- WARP production testing uses useful but narrow synthetic coverage: smooth world gradients, symmetric projection, horizontal gaze positions, nine central comparison pixels (`joey_stage1/ProductionWarpPinned.cpp:187-218,246-258`). It does not validate fine detail, full feather boundaries, temporal upscaling or target GPU performance.
- Tracking OFF preserves the inactive steering/original crop path by construction. Tracking ON with missing gaze uses image center, which can differ from the optical-forward axis for asymmetric projections. Neither path has new physical-headset acceptance evidence.

## Research cross-check

The Luna research reviewer checked pinned OpenNR r10 (`1a6057eef550296a7aa7efa6295fa7ad46308fc8`) and Cheeky (`4e47eefe51a512dcaf76bbdc672dcdab5251fc71`). Their owned reconstruction/motion-input policies do not establish a safe UE history repair. Root also rechecked OpenNR's explicit crop-change reconstruction resets in `NativeOpenVRGaze.cpp`.

Toolkit primary source checked during this audit: `BnuuySolutions/PSVR2Toolkit` at `0ef56b05405ac5c37c50cc9cd9c633597e8c6149`. Its shared CAPI notification counter and zero-timeout false-path packet copy support reader-local packet identity. A false result can contain a newer coherent packet; the copy remains protected by the lock. This does not establish physical sample age or a device-to-XR clock mapping. The v43 original research note lacked this exact Toolkit revision. The reviewer also noted that the packet header checks size/magic but does not enforce its version field; compatibility implications require establishing the supported ABI contract before choosing a rejection policy.

A conditional integration risk is that setup flags prove callback execution, not completed source draws. A skipped/aborted source after successful setup could pass that gate. Ordinary queue ordering may already guarantee the normal path; no target-game skipped-draw evidence was obtained, so this is not a confirmed defect.

## Evidence retained

The Luna math reviewer independently compiled the quaternion/homography oracle with strict warnings and reran all 20,000 deterministic cases successfully. Root reran the downloaded artifact audit: all 14 payload hashes, eight reviewed source headers, x64 native DLLs, compiled shader/UI identity and the 52-test CI evidence match the delivered build. This establishes build provenance and software checks, not runtime acceptance.

Windows run: https://github.com/liviutrn/OpenNR/actions/runs/38649697690

ZIP SHA256: `772b5070c3a7d8e7d654daa3d299c8dab2ef535f6a2a09e64a3fcbe4cd2e79a7`.

This review does not rebuild or replace v43. Documentation corrections do not fix the identified source-policy issue or close runtime evidence gaps.
