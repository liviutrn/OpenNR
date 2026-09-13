# OpenNR-VR: DLSSNR teacher-reliability and confidence-weighted distillation assessment

Date: 2026-09-08  
Audience: technical / research and runtime engineering  
Status: research assessment; no runtime or capture changes made

## Technical summary

The new work in [`edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass`](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass/tree/dlss-neural-rendering) is useful to OpenNR-VR primarily as a training-methodology result. It gives the first concrete project-relevant reason to stop treating every native DLSSNR teacher edit as equally trustworthy: in one held, pixel-aligned scene, the DLSSNR output recovered more reference-correlated fine detail, but it also increased high-frequency structure that the reference did not support. The measured gain was much weaker in the darkest brightness region than in the brightest.

The author reports a 5760×3240 reference render against aligned 4K base and model captures from the same frozen frame. At the reported measurement scale, “real detail” increased from 7.70 to 8.61 (+11.8%), while “invented” detail increased from 5.15 to 6.23 (+21%). In the darkest quarter, reference-detail recovery moved from 0.454 to 0.464; in the brightest quarter it moved from 0.777 to 0.889. These are author-reported values from the measurement commit, not an independently reproduced benchmark. The held-frame alignment and explicit reference decomposition make the observation materially stronger than a screenshot comparison, but one scene is not enough to establish a universal luminance law.

Decision: incorporate the result into the OpenNR research plan as a high-priority calibration and supervision experiment. Do not relabel the existing native Feature 18 teacher cache, replace the teacher, launch a blind training run, or promote a runtime shadow gate from this result alone. The next useful artifact is a separate reference-calibration cache containing aligned `(base, native teacher, high-quality reference, luminance/exposure, native guides, renderer context, and temporal-state metadata)` rows. That cache can support a continuous teacher-reliability map and a confidence-weighted distillation comparison while leaving the known-good route intact.

The terminal luminance gate is a credible isolated runtime candidate, not an accepted OpenNR change. Its placement maps cleanly to the current per-eye post-resolve path: preserve the raw teacher capture, apply any experimental gate per eye after the model resolve and before final SBS writeback/UI composition, and keep it disabled by default. The implementation still needs multi-scene, stereo, temporal, headset, and GPU-budget evidence.

## Key findings

### 1. The observation is valuable because it separates useful reconstruction from unsupported structure

The source author did more than compare a base image and a sharpened-looking output. The reported protocol holds the scene, renders a higher-resolution reference, pixel-aligns the reference to the 4K captures, and decomposes fine structure into a component correlated with the reference and a component absent from it. The measurement commit reports zero-pixel shifts for the relevant pairwise correlations and gives brightness-binned results. That is the right direction for evaluating a teacher used as a distillation target.

The most important implication is not the exact percentage. It is the asymmetry:

| Author-reported quantity | Base | DLSSNR model | Change | Interpretation for OpenNR |
|---|---:|---:|---:|---|
| Reference-correlated real detail | 7.70 | 8.61 | +11.8% | Teacher carries additional supported detail at this scene/scale. |
| Detail absent from reference (“invention”) | 5.15 | 6.23 | +21% | Teacher also adds more unsupported high-frequency structure. |
| Darkest-quarter reference-detail recovery | 0.454 | 0.464 | +0.010 absolute | Reported benefit is very small in the darkest region. |
| Brightest-quarter reference-detail recovery | 0.777 | 0.889 | +0.112 absolute | Reported benefit is much stronger in the brightest region. |

The source labels the darkest-quarter change as +0.9%. Because the displayed values are rounded, `0.454 → 0.464` is +0.010 absolute, about +1.0 percentage point and about +2.2% relative to the displayed base value. The exact unrounded values and denominator convention should be carried into replication before the small dark-region percentage is treated as precise.

Across ten brightness bins, the author reports a monotonic relationship between recovery benefit and brightness, with correlation +0.55, while the invention component stays roughly flat with brightness. This supports testing a luminance-conditioned reliability prior. It does not establish that brightness is the causal variable: exposure, material, shadow visibility, reference noise, tone mapping, LOD, stochastic rendering, and temporal state can be correlated with it.

### 2. The implementation sequence contains a useful engineering lesson

The first post-resolve gate used a sparse axis-aligned 3×3 sampling grid. The author reports that the grid followed texture patterns rather than illumination and exposed cross-hatch artifacts in the debug view. The follow-up replaced it with an isotropic two-ring estimator: a weighted center, an eight-tap inner ring, and an eight-tap outer ring with an angular offset. A later commit changed the thresholds from display-referred 0–1 brightness to stops below paper white because the original scene’s useful range was compressed into approximately 0.24–0.45.

That progression is directly relevant to OpenNR:

- A luminance gate must be tested with a debug visualization and artifact inspection, not accepted because its formula looks reasonable.
- Sparse directional samples can encode texture geometry into what is intended to be an illumination signal.
- Thresholds copied from a finished display image are not automatically valid for a pre-tonemap linear-light signal.
- A fixed radius and threshold pair are scene/exposure calibration values, not portable defaults.

The corrected estimator is still a terminal output heuristic. It is not evidence that the native Feature 18 network contains the same gate, and it does not identify the correct control signal for a distilled model.

### 3. OpenNR’s highest-value use is confidence-weighted supervision, not immediate gating

The existing project is trying to learn a DLSS-5-like output while preserving the native Feature 18 teacher’s quality and temporal behavior. A blind objective of the form `student → native teacher` can teach both the teacher’s supported reconstruction and its unsupported inventions. The new result justifies a calibration split where high-resolution references are available and the teacher can be evaluated locally.

A practical conceptual target is a per-pixel or per-block reliability value `c(p)` derived from the relationship between the teacher edit and the reference:

```text
teacher_edit(p) = teacher(p) - base(p)
supported(p)    = reference-correlated component of teacher_edit(p)
unsupported(p)  = reference-absent component of teacher_edit(p)
c(p)            = supported(p) / (supported(p) + unsupported(p) + ε)
```

The exact decomposition must be reproduced from the source protocol before these names become a project metric. In training, the reliability can be used to vary the relative supervision weights rather than to discard all low-confidence pixels:

```text
L(p) = w_teacher(p) · distance(student(p), teacher(p))
     + w_reference(p) · distance(student(p), reference(p))
     + w_base(p) · regularization(student(p), base(p))
```

with `w_teacher` increasing with measured teacher reliability and `w_reference` or a conservative base-preservation term increasing where the teacher edit is unsupported. This is a proposal for a controlled ablation, not a completed model design. The reference is a calibration/training signal and is not available at runtime; a deployed confidence predictor would need to infer its confidence from inputs available to the student, such as base color, native depth/motion vectors, renderer conditionings, luminance/exposure, and temporal state.

### 4. The result does not change the current capture contract or state-pair priority

The OpenNR captures already preserve the most important native inputs: base/pre-NR color, teacher output, depth, motion vectors, renderer conditionings, and strict initial history reset. Current local findings still show no promoted checkpoint and no proven exact same-current-frame reset/warm state-response pairs. The next temporal tranche remains at least eight exact reset/warm pairs, normally sixteen valid 64-frame clips, with formal audit and matched plain/renderer-only/state-only/combined controls.

The new result changes how a future calibration subset should be labeled and how teacher loss should be tested. It does not make missing temporal-state evidence irrelevant, and it does not justify removing native depth or motion vectors. The teacher-reliability work should therefore be a separate cache/experiment layered on top of the existing native capture contract.

## External source and provenance assessment

The relevant public branch is an experimental OptiScaler fork, not an NVIDIA-endorsed distribution. Its README describes a multi-pass DLSSNR experiment, requires the user to supply a proprietary `nvngx_dlssnr.dll`, and states that the setup is unsupported by NVIDIA. That provenance is appropriate for research leads but is not a production-quality assurance claim. See the [repository README](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass) and [current branch history](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass/commits/dlss-neural-rendering).

| Evidence item | What was inspected | Confidence | OpenNR implication |
|---|---|---|---|
| Measurement | [`dceeb57`](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass/commit/dceeb57b265044414c2c50f3c5559102170cce52) commit message and code diff | Moderate-high for the reported observation; not independently reproduced | Reproduce protocol and preserve raw measurements before using values as targets. |
| Isotropic mask correction | [`d09e832`](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass/commit/d09e832a58bbfee2b1f0b97e018942f9b984ee4d) | High that the implementation changed as described; effect still author-reported | Require debug views and artifact checks for any gate. |
| Stops-based thresholds | [`b791b1e`](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass/commit/b791b1e06220085125529d7fd66a920bc1dc4727) | High for source change; moderate for transfer | Calibrate in the signal’s actual linear/pre-tonemap space; do not copy display thresholds. |
| Internal control-mask lead | [`943ffe3`](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass/commit/943ffe3b5241830c8b2c810c6464b84ddcd8e697) and later branch notes | Suggestive binary evidence; no proof of a callable/current path | Keep as research-only. Do not equate it with the terminal luma gate or expose it in the native route. |
| New weights or clean-room checkpoint | No additional public fresh-weight training run, teacher→student checkpoint, LoRA/fine-tuning implementation, Hugging Face model/dataset, or weight-extraction breakthrough was found in the sources checked | High for the checked public material; not a universal negative | This is a supervision/measurement advance, not a new model artifact to install. |

The control-mask lead deserves separate treatment. The author reports compiled CUDA kernel names containing `control_mask` and a tensor name containing `CC_Control_History_Blend_Quantize_With_Teacher...weights`. The later project notes report no observable effect in the tested preset/format prints and describe the measured pairwise differences as near a noise floor. Even if the binary contains such kernels, that does not prove that the current Feature 18 route selects them, that the resource is user-controllable, or that the four-channel control surface corresponds to OpenNR’s 17 renderer-conditioning channels.

## Scope, data, and metric definitions

### Intended use

This assessment is for deciding whether the public result should change OpenNR-VR’s research priorities, data labeling, runtime experiments, or acceptance gates. It is not a claim that the upstream code is safe to install, that the native teacher has been improved, or that a distilled model is ready.

### External evidence grain

The reported measurement uses one controlled frozen scene and one reference/capture comparison. The reference is 5760×3240; the base and model captures are pixel-aligned 4K outputs from the same held frame. The source describes a three-pixel scale decomposition and brightness bins, including ten bins and darkest/brightest quarters. The raw reference image, raw captures, exact metric script, machine-readable result table, bootstrap intervals, and independent scene replications were not found in the checked branch tree.

### Terms used in this report

- **Base:** the 4K input before the DLSSNR model edit.
- **Teacher/model:** the 4K DLSSNR result with the model pass applied in the source experiment.
- **Reference:** the higher-resolution render of the held scene used to identify reference-correlated structure.
- **Real detail:** the source author’s reference-correlated fine-detail component. It means supported by this reference under this metric; it is not a universal perceptual truth.
- **Invention:** the source author’s reference-absent fine-detail component. This report uses “unsupported structure” interchangeably when discussing transfer risk, without asserting that every such difference is a hallucination; LOD, stochastic sampling, tone mapping, or reference mismatch can also contribute.
- **Reliability/confidence:** a proposed derived signal estimating how much of the teacher edit is supported by the reference. It is not currently present in the OpenNR cache and must not be confused with the upstream control-mask resource.

### Local OpenNR facts used for fit assessment

The current local route is direct NVIDIA NGX Feature 18 through `nvngx_dlssnr.dll`, with D3D12 evaluation and D3D11 interop. The renderer captures teacher output before final color writeback. In stereo, each eye is evaluated and resolved separately, then the result is blended or copied into the SBS output before UI composition. The local capture/training records include native teacher/base/depth/motion and renderer-context data, but the current research record has not promoted a model and has not proven exact reset/warm state pairs.

See the [current OpenNR findings](D:/.CODEX_Projects/OpenNR-VR/docs/OPENNR_LATEST_FINDINGS_20260908.md), [renderer-context conditioning status](D:/.CODEX_Projects/OpenNR-VR/docs/RENDERER_CONTEXT_CONDITIONING_20260908.md), and [local vendor Renderer.cpp](D:/.CODEX_Projects/DLSS_5_SKYRIM/vendor/open-shaders-dlssnr-vr-091bfb4d/src/Features/Upscaling/NeuralRendering/Renderer.cpp).

## Method and data-quality checks

The public branch was pinned locally in a temporary read-only research clone. The exact measurement, isotropic-mask, stops-threshold, and control-mask commits were inspected with their diffs and commit metadata. The branch tree was checked for raw captures, a metric script, a machine-readable measurement artifact, and reference data. No such reproducibility package was found in the checked tree. Local OpenNR source and current findings were then compared against the proposed gate location and training implications; no active project code, profile, package, capture root, or vendor binary was changed.

| Quality dimension | Finding | Severity if used without follow-up | Confidence |
|---|---|---|---|
| Scene control | Held-frame, aligned reference/base/model design is a strong within-scene control | Medium: same-scene findings may be overgeneralized | High for the reported protocol |
| Alignment | Source reports zero-pixel best shifts for the relevant pairings | High: misalignment would contaminate the decomposition | Moderate-high; raw correlation outputs are not packaged in the checkout |
| Metric transparency | Key numbers and the three-pixel scale are in the commit narrative, but exact implementation/data artifact is not available | High for replication and exact percentage interpretation | Moderate |
| Replication | One controlled scene is reported | High for universal claims | Low for generalization |
| Uncertainty | No confidence intervals, bootstrap, repeated renders, or sensitivity analysis were found | Medium-high | High that uncertainty is currently missing |
| Exposure space | Follow-up explicitly distinguishes display 0–1 from pre-tonemap linear-light stops | High if thresholds are transferred naively | High for the implementation lesson |
| Artifact correction | The initial 3×3 estimator was debugged and replaced after visible texture-following artifacts | Medium: shows the gate is sensitive to sampling design | Moderate-high |
| Runtime relevance | Gate is implemented at the end of resolve, but no OpenNR SkyrimVR/SteamVR live acceptance is reported | Critical for promotion | High |

The claim should therefore be used as a strong hypothesis generator and calibration design, not as a production threshold prescription. In particular, the correlation of +0.55 and the flat invention trend need uncertainty bands and replication before being encoded as a universal training prior.

## Fit to the current OpenNR architecture

### Offline training path: high usefulness

This is the clearest immediate value. OpenNR already stores the native teacher and its native guides, so a separate reference-calibration subset can add high-resolution references and derive teacher-reliability labels. The key controls should keep the same scene split, capture route, temporal state, and native inputs:

1. RGB/base only.
2. RGB plus native depth and motion vectors.
3. RGB plus renderer-context conditionings.
4. Full native input set with temporal/state metadata.
5. Each of the above with ordinary teacher imitation versus confidence-weighted teacher/reference supervision.

The result should be evaluated on both the prior validation cohort and a newly collected cohort. A confidence-weighted arm is not promoted because its teacher MAE improves on one calibration scene; it must improve the supported-detail/unsupported-structure tradeoff without breaking color, temporal behavior, stereo alignment, or the existing promotion gates.

### Reference-calibration protocol: high usefulness, bounded scope

The reference is expensive and may not be available for every capture. It is most valuable as a calibration instrument: choose a small, deliberately varied set of scenes/materials/exposures, reproduce the metric, derive labels, and then test whether a predictor can estimate reliability from runtime-available signals. Keep the calibration cache immutable and separate from the ordinary native teacher cache. Do not replace native labels with reference-derived labels globally.

The minimum useful replication should include multiple brightness regimes and at least several distinct scene/material/motion conditions, with exact reference/capture alignment recorded. The protocol should include static frames, motion bursts, disocclusions, and reset/warm state where practical; otherwise it only measures a static image prior and cannot inform a temporal VR model.

### Runtime luma gate: medium usefulness as an isolated experiment

The gate concept maps to the existing renderer boundary. The current renderer can retain the raw `teacher`/`teacher_raw` capture, apply an experimental per-eye gate to the resolved model output, and then write to the eye output/SBS surface before UI composition. This is a favorable integration point because it does not require changing Feature 18’s internal model or input contract.

The gate must be isolated and reversible:

- Keep the native teacher raw and gated variants as separate captures.
- Keep the mode off by default and use a separate experimental output root.
- Apply the gate independently per eye; never estimate luminance across the SBS eye seam.
- Define the sampling radius in final per-eye output pixels or a normalized scale, not as a copied 24-pixel constant across 4K, crops, and reduced model-resolution paths.
- Calibrate thresholds in the actual pre-tonemap linear-light signal, with exposure/paper-white metadata.
- Measure GPU cost at the headset target resolution and route; the corrected estimator adds many texture reads per output pixel.
- Test static, motion, disocclusion, reset/warm, eye symmetry, UI, and compositor behavior.

The main risk is that suppressing shadow edits can also suppress legitimate shadow detail or intentional denoising. A brightness gate is a useful candidate control, not an objective definition of quality.

### Direct native teacher replacement: low usefulness

Nothing in the checked result replaces the private signed Feature 18 teacher, exposes its weights, establishes a clean-room model, or proves a new public runtime contract. The result should not trigger a DLL replacement, model relabeling, or native-guide removal. Keep the pinned native teacher and exact Feature 18 resources as the authority for current OpenNR capture and acceptance.

## Acceptance layers

Any follow-up should be judged in separate layers rather than collapsing package health and visual quality into one pass/fail result:

| Layer | Required evidence | Current status from this result |
|---|---|---|
| Source/API | Reproducible metric, exact input/output definitions, and documented gate/label contract | Not complete |
| Package/provenance | Hashes, license boundary, isolated files, known-good fallback | Not changed; native route preserved |
| Offline quality | Reference-supported detail, unsupported high-frequency energy, MAE/LPIPS/color, temporal metrics | Calibration experiment not yet run |
| Renderer/game | SkyrimVR observes the intended route and output ownership | Not tested by this result |
| Stereo/temporal | Per-eye symmetry, reset/warm response, motion/disocclusion behavior | Exact reset/warm pairs still missing |
| HMD/compositor/UI | SteamVR/OpenXR delivery, UI/compositor stability, audible and controller behavior | Not tested |
| VR budget | GPU frame time, variance, reprojection/headroom, estimator overhead | Not measured |
| Deployment | Reversible package and rollback procedure | No deployment performed |

## Recommended execution sequence

### P0 — Preserve the contract and make the observation reproducible

- Keep the current direct Feature 18 route, native depth/motion vectors, renderer conditionings, and teacher captures unchanged.
- Complete the existing exact reset/warm tranche: at least eight exact pairs, normally sixteen valid 64-frame clips, with contiguous IDs, native guides, initial reset state, and formal pair audit.
- Recreate the public measurement on a small, varied scene set. Record raw reference/base/model images, exact exposure and paper-white settings, alignment shifts, frequency filter/scale, brightness-bin edges, normalization, and per-scene results.
- Bootstrap or otherwise quantify uncertainty. Carry exact unrounded numbers so small dark-region changes cannot be misread from rounded tables.

### P1 — Build the separate teacher-reliability calibration cache

- Store aligned `(base, teacher, reference, luminance/exposure, depth, motion, renderer context, eye, frame index, reset/warm/state metadata)` rows.
- Derive supported and unsupported teacher-edit maps with a versioned metric script.
- Compare ordinary teacher imitation against confidence-weighted teacher/reference supervision on identical train/validation/frozen-test splits and both prior/new cohorts.
- Keep the native teacher target and the calibration-derived labels immutable and separately named.
- Add a predictor experiment only after proving that the offline confidence map is stable across scenes, exposures, materials, and state conditions.

### P1 — Isolate the terminal gate candidate

- Implement only in a separate experimental branch/package if authorized later; do not modify the active profile now.
- Capture raw and gated teacher outputs from the same frames.
- Start with gate-off and a debug-mask mode, then compare isotropic sampling against simpler local-luminance controls.
- Test threshold/radius sensitivity in linear-light stops, per eye, across full-eye and cropped/foveated paths.
- Record GPU timings and VR acceptance separately from image metrics.

### P2 — Broaden and decide

- Expand across dark interiors, bright exteriors, emissive/metallic materials, foliage/geometry edges, shadows, motion, disocclusions, and different exposure states.
- Require a meaningful improvement in supported detail at no unacceptable increase in unsupported structure, temporal instability, stereo mismatch, or VR frame cost.
- Do not spend on cloud training until the local calibration experiment passes the two-cohort quality gates and the temporal capture contract is complete.

## Further questions

1. What exact frequency decomposition, filter support, normalization, and block aggregation produce the 7.70/8.61 and 5.15/6.23 values?
2. Are the reference and 4K captures rendered with identical LOD, stochastic seeds, denoiser state, exposure, and tone-map conventions, or are some “inventions” reference mismatch?
3. Does the brightness relationship persist across scenes after conditioning on material, depth, shadow status, exposure, and temporal history?
4. Is the reported flat invention component statistically flat, or are the differences hidden by missing uncertainty intervals?
5. Does a reference-derived confidence map remain stable through motion, disocclusion, history reset, warm state, and left/right eye differences?
6. Can a runtime-available predictor estimate confidence without accidentally learning scene identity or exposure-specific thresholds?
7. What is the corrected 16-tap gate’s measured GPU cost at the project’s actual per-eye resolution and foveated crop modes?
8. Does the gate improve accepted perceptual/stereo/temporal outcomes, or does it merely reduce visible shadow lift in the source scene?
9. Is the compiled control-mask path selectable in the native Feature 18 route, and can it be tested without modifying or distributing proprietary binaries? Until answered, it remains a separate research lead.

## Bottom line

This is a meaningful update for OpenNR, but its value is methodological. The public result strengthens the case for teacher-reliability maps and confidence-weighted distillation, and it provides a disciplined design pattern for a separately gated output path. It does not provide a new model, new weights, a Feature 18 replacement, a universal shadow threshold, or VR acceptance evidence.

Recommended decision: proceed with P0 replication plus the existing exact reset/warm capture priority; then run a small, immutable reference-calibration ablation. Keep the native teacher, guides, active profile, and known-good fallback unchanged. Treat the terminal luma gate as an off-by-default experimental candidate only after offline replication and per-eye/temporal/VR-budget tests.

## Sources and local evidence

- [OptiScaler DLSSNR THERMOTRON multipass repository](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass)
- [DLSSNR measurement commit `dceeb57`](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass/commit/dceeb57b265044414c2c50f3c5559102170cce52)
- [Isotropic luminance-mask correction `d09e832`](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass/commit/d09e832a58bbfee2b1f0b97e018942f9b984ee4d)
- [Stops-based threshold correction `b791b1e`](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass/commit/b791b1e06220085125529d7fd66a920bc1dc4727)
- [Control-mask binary-analysis lead `943ffe3`](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass/commit/943ffe3b5241830c8b2c810c6464b84ddcd8e697)
- [OpenNR latest findings](D:/.CODEX_Projects/OpenNR-VR/docs/OPENNR_LATEST_FINDINGS_20260908.md)
- [OpenNR renderer-context conditioning status](D:/.CODEX_Projects/OpenNR-VR/docs/RENDERER_CONTEXT_CONDITIONING_20260908.md)
- [Open Shaders DLSSNR renderer source](D:/.CODEX_Projects/DLSS_5_SKYRIM/vendor/open-shaders-dlssnr-vr-091bfb4d/src/Features/Upscaling/NeuralRendering/Renderer.cpp)

