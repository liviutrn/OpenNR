# Matched temporal-delta continuation — 2026-09-08

The temporal-delta experiment is complete. It does not reach the ordinary 1×
MAE target and neither arm is promoted. The run was paused while the separate
TensorRT export and native probe used the GPU, then resumed only after those
tests finished. Training and inference artifacts remained in separate output
roots.

## Contract and provenance

Both arms started from the rebalanced hard-cohort checkpoint at absolute step
3,200:

`C:/OpenNR/Training/semantic_mixture_rebalanced_pair_20260908/continuation_3200_rebalanced/last.pt`

Its SHA-256 is
`76624869c6fd7c746ff730da4e1ed85a95414a0f568a2ff9fb5f9c5dc89fddf2`.
The two arms restored optimizer and RNG state, used the same 800-step schedule
(`f77e63e3a73827736aeb81c5bd250ed065186a2a90f8ac6b60ae02c4aba04cd`), used no
test rows, and sampled the six cohorts with probabilities
`0.25/0.10/0.10/0.15/0.20/0.20`.

The control kept the temporal-delta weight at `0.12`; the intervention doubled
it to `0.24`. The complete paired record is under
`C:/OpenNR/Training/semantic_mixture_temporal_delta_pair_20260908_resume`.

## Endpoint result

Values are ordinary validation MAE at absolute step 4,000. Lower is better.

| Cohort | Step-3,200 candidate start | Baseline delta 0.12 | Boosted delta 0.24 | Target |
| --- | ---: | ---: | ---: | ---: |
| Prior | 0.018280216 | 0.018539177 | 0.018533025 | <= 0.011 |
| High-effect | 0.014782214 | 0.014737105 | 0.014722999 | <= 0.011 |
| Older renderer | 0.012515421 | 0.012641598 | 0.012647441 | <= 0.011 |
| Fresh session | 0.013633489 | 0.013969104 | 0.013965551 | <= 0.011 |
| Renderer-state | 0.019923122 | 0.019530537 | 0.019531809 | <= 0.011 |
| New pairs | 0.026916588 | 0.025523025 | 0.025459345 | <= 0.011 |

The boosted arm is a small improvement over the matched baseline on prior,
high-effect, fresh-session and new-pairs, and a small regression on the older
renderer and renderer-state cohorts. It does not improve every cohort relative
to the step-3,200 candidate start: its maximum endpoint-to-start ratio is about
`1.024356`, and the all-cohort gate is false. The baseline has the same gate
failure. No checkpoint is promoted.

Endpoint temporal-delta MAE also remains mixed. The boosted arm ends at
`0.008506803 / 0.007448780 / 0.009432291 / 0.005291464 / 0.007366825 /
0.010814971` in the same cohort order. This is not evidence of a broad
temporal-stability win, even though several values are slightly lower than the
matched baseline.

The step-3,200 rebalanced checkpoint remains the better broad research
reference for the crop-cohort line because the 4,000-step continuation trades
small hard-cohort gains for regressions in prior, renderer-pilot and fresh
validation. The paired histories and checkpoints remain immutable for later
comparison; no runtime bundle was replaced.

## Runtime coordination

The separate runtime task completed the isolated TensorRT work while this run
was paused. The validated speed candidate is the 33% model-surface,
FP16-I/O, FP16-tactics, builder-opt5 engine with native guides retained at
`672x624`. The synthetic sequential-stereo median is about `17.058 ms`, and
the preserved-capture forward median is about `17.008 ms`; native TensorRT C++
deserialization and I/O probing passed. This remains an offline isolated
engine, not Skyrim or headset acceptance. The exploratory FP8/Q-DQ build was
rejected after repeated TensorRT reformat/fallback errors; no FP8 engine was
accepted. See [the runtime benchmark report](SEMANTIC_JOINT_RUNTIME_BENCHMARK_20260908.md).

## Data decision

More steps with the same crop-derived context and the same six cohorts are not
currently justified by this matched null result. A small full-eye temporal pilot
is now the highest-value data experiment, but a snapshot every three seconds
must be treated as spatial/global-context evidence rather than recurrent
temporal training data. It cannot supply contiguous history for the causal
student.

If the pilot is authorized, keep it separate from the existing crop cohorts and
capture a bounded set of 8–12 sequence-level scenes with both eyes, contiguous
reset-qualified temporal bursts, exact native Feature-18 guides, teacher RGB,
depth, motion vectors, validity masks and the renderer stages. Add sparse
full-resolution whole-eye input/teacher frames only as a paired context/color
tranche, with immutable sequence manifests and a predeclared storage budget.
Do not mix sparse rows into the current 64-frame temporal cache or use optical
flow in place of the native motion resource. The existing full-resolution
masters and their mixed context result support this small pilot; they do not
justify a large capture or Runpod spend yet.

A validated, disabled-by-default proposal is recorded at
`config/opennr_capture_full_eye_context_pilot_20260908.example.json`. It uses
eight full-eye samples per sequence at one sample every three seconds, keeps the
four paired 512-pixel crops, and writes to a new output root. At the observed
full-resolution-master rate of roughly 2 GiB per sequence, an 8–12 sequence
pilot would consume approximately 16–24 GiB before derived caches and should
leave a large free-space margin on C:. It has not been applied to the live
profile.

No capture profile, Skyrim installation, Feature-18 resource, Community
Shaders DLL, or Runpod allocation was changed by this experiment.
