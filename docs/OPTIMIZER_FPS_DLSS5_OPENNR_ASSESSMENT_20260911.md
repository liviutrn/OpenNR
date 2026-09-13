# optimizer-fps-dlss5 assessment for the OpenNR fork — 2026-09-11

## Decision

The new project is relevant as a performance research lead, but it is not a
production-ready OpenNR/Open Shaders patch.

The useful part is the temporal residual-reuse design:

```text
full Feature 18 pass:  residual = teacher_output - current_input
skipped pass:          current_input + reprojected(previous_residual)
```

I first ported that idea into the current repository as an isolated offline
probe: [`tools/evaluate_optimizer_temporal_reuse.py`](../tools/evaluate_optimizer_temporal_reuse.py).
It uses the existing strict cache contract, exact captured Feature 18 motion,
captured depth, paired eyes, reset-qualified streams, and held-out baselines.
I then added a disabled, opt-in runtime probe to the current Open Shaders
vendor checkout. The runtime branch is deliberately narrower than the public
project: it reuses the native Feature 18 output residual with exact game
motion, and does not add the public project's spatial remap, interposer, or
async queue.

Production decision: **keep temporal skipping and peripheral compression off by
default; live VR acceptance is still no-go**. Implementation decision: **the
narrow temporal residual path is now ported as an isolated full-eye experiment**
so it can be measured against the existing fallback without changing that
fallback or the teacher lineage.

## Source and provenance

The supplied development is
[`BeliyG3/optimizer-fps-dlss5`](https://github.com/BeliyG3/optimizer-fps-dlss5),
checked locally at commit `a47d9fb000e247df35f992b18f1020e24097ea2e` in:

```text
C:\OpenNR\research\optimizer-fps-dlss5_20260911
```

The checkout contains an MIT license for its own code. NVIDIA binaries,
private model files, and a Skyrim VR integration are not part of it. The
project README describes two independent modes: non-linear peripheral
compression before/after the neural pass, and running the neural pass only on
some frames while reprojecting the last residual on intervening frames. Its
reported timings are an author-run offline procedural benchmark on an RTX 4080
SUPER; the README explicitly treats real-game captures as future work. See the
[README](https://github.com/BeliyG3/optimizer-fps-dlss5/blob/a47d9fb000e247df35f992b18f1020e24097ea2e/README.md),
[integration guide](https://github.com/BeliyG3/optimizer-fps-dlss5/blob/a47d9fb000e247df35f992b18f1020e24097ea2e/docs/INTEGRATION.md),
and [limitations](https://github.com/BeliyG3/optimizer-fps-dlss5/blob/a47d9fb000e247df35f992b18f1020e24097ea2e/docs/LIMITATIONS.md).

The repository is technically useful enough to study: it has D3D11/D3D12
adapters, HLSL pack/unpack and temporal passes, reset handling, motion-chain
accumulation, and tests. That establishes implementation plausibility, not
Skyrim VR image quality, stereo correctness, frame-time savings, or deployment
readiness.

## Relevance to the current fork

| New idea | Relation to current OpenNR | Decision |
| --- | --- | --- |
| Residual of the native neural output reused on skipped frames | Directly relevant to the current Feature 18 output contract. It is different from training a residual student. | Ported in the offline probe and as a disabled runtime path. |
| Accumulated current-to-previous motion over skipped frames | Relevant and compatible in principle. The current captures already retain exact Feature 18 motion and the audited positive warp sign. | Ported in the offline probe and runtime shader with per-eye ping-pong state. |
| Depth rejection and colour rejection | Relevant for disocclusion and wrong-vector protection. Gate thresholds need native calibration and visual review. | Ported in the offline probe and runtime shader as conservative opt-in gates. |
| Depth-matched/low-resolution hole fill | Potentially useful around disocclusions, but the public implementation is more detailed than the cache-level proxy. | Probe only; not a shader/runtime port. |
| Non-linear peripheral compression | Not the same as the current foveated route. Current VR foveation crops a subrect, runs the selected path there, and stretches/blends the periphery; the new project remaps the whole input density before the neural consumer. | Do not port yet. It would create a new Feature 18 input/guide/resolve contract. |
| Run Feature 18 every Nth frame | High potential performance value, high temporal/VR risk. It changes history ownership, frame cadence, capture semantics, and per-eye state. | Ported only as disabled N=2/3/4 full-eye, 100%, single-pass runtime probe; no live promotion. |
| Async background neural pass | Requires queue ownership, fence retirement, pending-chain promotion, and correct behaviour under GPU saturation. | Do not port into the current D3D11-to-D3D12 bridge yet. |
| ReShade/NGX interposer and API-neutral SDK | Useful for understanding a generic consumer, but it owns a different hook boundary from the current direct `Runtime::Execute` path. | Do not vendor or merge it into Open Shaders. |
| Gaze/foveation stacking | The new project says it can be stacked with gaze, but the SDK itself lists moving eye tracking as out of scope. | Keep separate from the existing foveated and eye-tracking work. |

## Why only the narrow runtime port was appropriate

The current Open Shaders checkout is not a clean upstream baseline: it carries
user-owned VR, eye-tracking, model-resolution, capture, shader, and packaging
changes. The relevant renderer already has:

- a direct Feature 18 execution path with separate per-eye state;
- `modelResolutionPercent`, reduced-resolution input, and matched native
  resolve modes;
- `ApplyStereo`, per-eye resources, and explicit reset/history handling;
- capture metadata that records source/model dimensions, guide dimensions,
  motion scales, reset state, and route;
- a separate foveated subrect path and a periphery temporal-smooth path.

The runtime change is therefore gated to the smallest compatible contract:
native full-eye layout, 100% model resolution, one Feature 18 pass, and the
same exact motion-vector resource and scale already passed to Feature 18. It
is enabled only on the normal before-UI route; pre-upscale, reduced-resolution,
sequential, and cropped/foveated stages are excluded because they share the
renderer object without a stage-specific temporal-state namespace. On a full
frame it stores the current input, native teacher output residual, and depth.
On an intervening frame it accumulates the current-to-previous motion,
reprojects the private residual, applies depth/relative-luma rejection, and
writes back the reconstructed color. A skipped frame never evaluates or
advances native Feature 18 history; the next full evaluation is explicitly
reset. Any failed private dispatch falls back to a full Feature 18 evaluation.
The branch is disabled by default and skipped frames are excluded from the
OpenNR teacher-capture path.

The source locations inspected were:

- `D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d\src\Features\Upscaling\NeuralRendering\Renderer.cpp`
- `D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d\src\Features\Upscaling\NeuralRendering\Runtime.h`
- `D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d\src\Features\Upscaling\FoveatedRender\Modes.cpp`
- `D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d\src\Features\Upscaling\FoveatedRender\Core.h`

The new project's correct pipeline position is “pack inputs, run the renderer
at work resolution, then unpack before the native consumer.” That is not a
drop-in for the current path: the current renderer directly supplies the
Feature 18 colour, depth, motion, output, subrects, and per-eye reset state.
Adding a non-linear remap would require proving the remapped motion endpoints,
depth alignment, native resolve, stereo symmetry, and capture provenance as a
new contract.

There is also a local negative result that matters. The current paired study
rejected a **learned residual target**: on its frozen test, residual step 1,200
was worse than the direct step-0 arm by `+0.003818105` MAE,
`+0.001759656` temporal-delta MAE, and `+0.005805012` stereo-disagreement MAE.
That does not disprove runtime reuse of a native teacher residual, but it rules
out treating this project as evidence for promoting a residual-trained student.
See [`RESIDUAL_TARGET_FP8_EXPERIMENT_20260911.md`](RESIDUAL_TARGET_FP8_EXPERIMENT_20260911.md).

## What was ported

The new tool is a read-only data consumer with explicit output writing. It
accepts only a materialized strict temporal cache that has:

- `strict_initial_reset=true`;
- `temporal_training_allowed=true`;
- one crop index;
- contiguous frame IDs per eye;
- an initial reset and no mid-stream reset;
- both stereo eyes for every evaluated sequence;
- `motion_vector_contract=exact_feature18_bound_resource`.

It evaluates a schedule with a full captured teacher frame at frame 1 and then
every `N`th frame. On a skipped frame it:

1. upsamples the cached guide fields to the crop colour resolution;
2. composes the current exact motion with the accumulated current-to-reference
   displacement;
3. samples the previous full-pass residual at the reprojected location;
4. optionally rejects it using depth and relative-luma checks;
5. optionally fills rejected pixels from an average-pooled residual while
   preserving the current input chroma.

The output variants are deliberately separated:

- `input_baseline`: current input on every frame;
- `native_full`: captured teacher on every frame, an oracle and not a timing
  result;
- `pure_reprojection`: residual reuse with only in-bounds/validity checks;
- `guarded_reprojection`: residual reuse with depth and colour gates;
- `guarded_fill`: guarded reuse plus conservative low-resolution fill.

The probe uses no optical flow and does not treat a skipped reconstructed frame
as a teacher capture. Its JSON marks the result as a crop-scale proxy and
`test_used_for_tuning=false`.

The runtime probe is in the vendor checkout at:

- `src/Features/Upscaling/NeuralRendering/Renderer.cpp` — private per-eye
  residual/depth/motion state, cadence/reset handling, dispatches, fallback,
  and full-eye/stereo gating;
- `src/Features/Upscaling/NeuralRendering/Runtime.h` — opt-in cadence and gate
  tuning fields;
- `src/Features/Upscaling/FoveatedRender.h` and `.cpp` — persisted settings and
  UI, defaulting to cadence `0` (off);
- `src/Features/Upscaling/NeuralRendering/Integration.cpp` — settings mapping
  and crop exclusion;
- `features/Upscaling/Shaders/Upscaling/NeuralRendering/TemporalReuseCS.hlsl`
  — `Snapshot`, `Accumulate`, and `Reproject` compute passes.

This is a runtime probe, not a promotion. Verification on 2026-09-11 was:

- `Renderer.cpp`, `Integration.cpp`, `FoveatedRender.cpp`, and `Runtime.cpp`
  compile as isolated `CommunityShaders` objects;
- all three HLSL entry points compile with the fork's DXC (`Snapshot.dxil`,
  `Accumulate.dxil`, and `Reproject.dxil`);
- CMake configuration succeeds against the existing local dependency tree, but
  the full target stops in the unrelated existing `StbImageWriteImpl.c` third-
  party compile at `stb_image_write.h:1467` (`C2099: initializer is not a
  constant`), before linking a DLL;
- no DLL was deployed to Skyrim, and no live headset, SteamVR, frame-budget,
  or image-quality acceptance has been claimed.

## Local probe results

### Held-out every-frame crop tranche, N=2

Input cache:

```text
C:\OpenNR\TrainingCache\crop_temporal_every_frame_20260909_all18
split: test
4 sequences, 64 frames per sequence, both eyes
RGB: 512x512; guides: 128x128
source colour: 2496x2688; source guides: 1664x1792
rows_sha256: a3e79d701d423d325b356bacccf6090e59f4c3dad7a43ed9d46cde0c31a0657a
```

The schedule contained 128 full eye-frames and 128 skipped eye-frames. The
validity diagnostic accepted 98.13% of skipped crop pixels before depth/colour
gates and 88.44% after them.

| Variant | Skipped-frame MAE | Skipped temporal-delta MAE | Skipped stereo disagreement MAE |
| --- | ---: | ---: | ---: |
| Input baseline | 0.023104106 | 0.009134111 | 0.031554950 |
| Pure reprojection | **0.003382538** | **0.003382538** | **0.005162876** |
| Guarded reprojection | 0.004406345 | 0.004406345 | 0.007017938 |
| Guarded fill | 0.004863916 | 0.004863916 | 0.007780239 |

The result says that the residual-reuse mechanism is promising on this
crop-scale data, while the uncalibrated rejection/fill approximations lose
some of that benefit. It does **not** say that the pure path is safe to ship:
the public project's own limitations identify ghosting, disocclusion errors,
cadence shimmer, tone lag, and aged residuals as remaining risks.

The exact output is
[`optimizer_temporal_reuse_eval_20260911_test.json`](C:\OpenNR\Training\optimizer_temporal_reuse_eval_20260911_test.json).

### Held-out newer state-aware tranche, N=2

Input cache:

```text
C:\OpenNR\TrainingCache\full_eye_temporal_state_tranche_20260910_v1
split: test
2 sequences, 16 frames per sequence, both eyes
RGB: 512x512; guides: 128x128
```

The validity diagnostic accepted 99.65% of skipped crop pixels before gates and
96.15% after them.

| Variant | Skipped-frame MAE | Skipped temporal-delta MAE | Skipped stereo disagreement MAE |
| --- | ---: | ---: | ---: |
| Input baseline | 0.022402638 | 0.004112158 | 0.033204039 |
| Pure reprojection | **0.002878474** | **0.002878474** | **0.004435357** |
| Guarded reprojection | 0.003499708 | 0.003499708 | 0.005583139 |
| Guarded fill | 0.003678885 | 0.003678885 | 0.005958213 |

This newer tranche shows the same mechanism-level direction, but it is only
two 16-frame held-out sequences and still only a 512x512 crop. It is not a
replacement for the missing full-eye 64-frame temporal validation.

The exact output is
[`optimizer_temporal_reuse_eval_20260911_state_test.json`](C:\OpenNR\Training\optimizer_temporal_reuse_eval_20260911_state_test.json).

### Cadence sweep on the four-sequence held-out crop tranche

The sweep is useful as a stress indication, not as a frame-time benchmark. The
pure reprojection arm remained best numerically in this proxy, while error
increased as the residual aged. The guarded/fill arms were more conservative
but also more damaging under these uncalibrated thresholds.

| Cadence | Basic valid fraction | Guarded valid fraction | Pure skipped MAE | Guarded skipped MAE | Fill skipped MAE |
| ---: | ---: | ---: | ---: | ---: | ---: |
| N=2 | 98.13% | 88.44% | 0.003382538 | 0.004406345 | 0.004863916 |
| N=3 | 97.28% | 85.80% | 0.003888982 | 0.005120039 | 0.005827382 |
| N=4 | 96.54% | 83.58% | 0.004337065 | 0.005721902 | 0.006638080 |

The direction supports investigating N=2 first, matching the new project's own
quality recommendation. It does not reproduce the project's claimed FPS
numbers: the probe runs against pre-captured teacher outputs and has no
renderer timing, queue overlap, or headset delivery measurement.

## What remains unproven

The following acceptance axes are intentionally still open:

- native full-eye RGB/depth/MV residual quality rather than a centre crop;
- fast turns, disocclusions, particles, hair, transparency, HUD, tone changes,
  and frame-boundary shimmer;
- exact per-eye stereo consistency over long sequences;
- Feature 18 history interaction when the model is not evaluated every frame
  under live Skyrim timing and route changes (the explicit reset behavior is
  implemented, but not live-certified);
- model reset after overlay, stage, resolution, crop, layout, or route changes;
- GPU queue and fence ownership if asynchronous evaluation is attempted;
- frame-time reduction after pack/unpack, copies, synchronization, and resolve;
- SteamVR delivery, headset image quality, UI/audible state, deployment, and VR
  frame budget.

The tool's `native_full` arm is an oracle because it uses the captured teacher
for every frame. Its zero error is a schedule reference, not evidence of a
runtime path. The positive MAE improvements over `input_baseline` mainly show
that the captured teacher residual contains useful image correction; they do
not certify the skipped-frame artefact profile.

## Reproduction commands

Use the existing training environment:

```powershell
& 'C:\OpenNR\Tools\OpenNRTrainVenv\Scripts\python.exe' `
  'D:\.CODEX_Projects\OpenNR-VR\tools\evaluate_optimizer_temporal_reuse.py' `
  --self-test

& 'C:\OpenNR\Tools\OpenNRTrainVenv\Scripts\python.exe' `
  'D:\.CODEX_Projects\OpenNR-VR\tools\evaluate_optimizer_temporal_reuse.py' `
  --cache 'C:\OpenNR\TrainingCache\crop_temporal_every_frame_20260909_all18' `
  --split test --cadence 2 --device cuda --resample bilinear `
  --output 'C:\OpenNR\Training\optimizer_temporal_reuse_eval_20260911_test.json'
```

The self-test passed on CUDA. The two N=2 evaluations and the N=3/N=4 sweep
completed without modifying either input cache.

## Recommended next step

Keep the current Feature 18/Open Shaders path as the known-good fallback and
do not enable this port by default. If the mechanism is worth advancing, use
the new runtime only as a controlled experiment after a native full-eye
capture tranche with:

1. full teacher output every frame, exact depth/MV, both eyes, and initial
   `[true, true]` reset;
2. an offline reconstruction using exactly the same per-eye accumulated-motion
   state and a separately tuned gate/fill study;
3. visual review of N=2 fast-turn/disocclusion/tone cases;
4. enable the runtime probe at N=2 only for a disposable A/B (the persisted
   key is `neuralRenderingTemporalReuseCadence`), with capture disabled or
   limited to known full frames, and verify fallback/reset logs;
5. live Skyrim VR A/B with headset and VR-budget gates kept separate from
   source/package health.

Until those gates pass, the runtime branch remains research-only and the
known-good full Feature 18 path remains the acceptance baseline.
