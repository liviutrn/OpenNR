# Scale-conditioned resolve pilot — 2026-09-12

## Decision

The public native-output distillation release is relevant as a methodology
reference, but it does not change the current runtime decision by itself. The
local experiment shows a clearer route to a fast *DLSS5-look approximation*:
run the native neural pass at a reduced internal resolution and use a fused,
very cheap full-resolution residual resolve. A full-resolution learned
resolver is currently too expensive for VR, even when reduced to four hidden
channels.

No branch in this report is promoted. The measurements are offline and use
retained stateful Skyrim sequences/replays; they do not establish live Feature
18, temporal, stereo, headset, compositor, or frame-budget acceptance.

## User-directed look objective

For the portable look branch, exact numerical reproduction of NVIDIA's Feature
18 output is now a diagnostic reference rather than the primary acceptance
criterion. The useful outcome is a repeatable, visually preferable neural-
rendering character over the raw full-resolution input, with no objectionable
halos, invented geometry, face distortion, or temporal shimmer. The native
50% residual remains valuable as a high-quality look reference and as evidence
that the reduced-work composition is sound, but a student does not need to
match it pixel-for-pixel to be useful.

The first visual review of the current sequence-5 samples is still negative for
the student branches: the native 50% residual has an obvious contrast/detail
change, while the 99k and streamed 346k outputs remain visually close to raw
identity in the face, foliage, and distant-NPC crops. They are fast enough to
continue testing, but they have not yet demonstrated a reliably visible neural
look. The next quality gate should therefore combine blind human preference
over raw input with artifact checks and temporal stability, rather than relying
only on MAE to the native teacher.

## New public evidence: NeuralScreen v1.7.0

The September 12, 2026 `DLSS5-NeuralScreen` v1.7.0 release is directly
relevant to this pilot. Its author reports that the neural work is capped at
2560x1440 and that the earlier resolution control was not changing the neural
workload. The new Boost path actually lowers the work resolution, then
composites the neural edit over the untouched native-resolution frame. On an
RTX 5070 Ti at 4K, the reported network time falls from 16.0 ms to 7.0 ms in
the default Boost setting and 5.0 ms in the lowest setting; the whole-program
rates are reported as 45.7, 72.6, and 83.4 FPS respectively. The release
also explicitly says motion quality has not yet been validated, so this is
strong runtime evidence but not temporal or VR acceptance evidence.

Static inspection of the tagged source confirms the mechanism rather than
only the prose: the host creates the neural feature at the smaller work
dimensions while retaining full-resolution input/output resources, and the
residual shader samples the reduced neural input/output and applies

```text
full_native + strength * (reduced_neural_output - reduced_neural_input)
```

at full resolution. This is the same family of composition tested below. The
local source was inspected but no public binary was installed or executed.

The release's `nvngx.dll` return-path observation is useful for a future
isolated NVIDIA teacher harness, because it explains why a forwarding module
may need to preserve a caller path containing `nvngx.dll`. It does not make a
portable student faster and does not change the exact Feature 18 resource
contract required by OpenNR-VR.

The current NeuralScreen technical notes sharpen the comparison: direct NGX
evaluation is reported at about 2.90 ms for 1280x720, 4.60 ms for 1920x1080,
and 7.10 ms for 2560x1440, while the 4K full-screen path is about 16.05 ms.
The same notes report a roughly 1.3 ms non-NGX pipeline remainder when the
capture/present path is fully GPU-resident. This is a better comparison than
the older decorative-slider measurements because the work resolution is now
actually the resolution handed to the network.

The current public AMD optimization discussion is consistent with the local
findings: it recommends an isolated frame-dump CLI, per-kernel timing,
modular kernels, fusion of GEMM/activation/bias, and zero-copy DX12/HIP
interop. Those are runtime/kernel actions, not new weights or LoRAs. The
current public repositories still expose no verified portable LoRA or
fine-tuned recovered 145M checkpoint that would close this speed/quality gap.

The current [`neural-upstream` findings](https://github.com/matiasLombo/neural-upstream/blob/main/FINDINGS.md)
make the same point more strongly: a rebuilt Ada path is reported at about
3.27 ms for the neural network on an RTX 4070 Ti, and experiments with cache
operators, register/copy changes, and FP8-versus-FP16 choices did not produce
a decisive improvement. The original scaling-ratio control was also reported
to be inert. After those checks, the remaining useful levers are structural:
lower the network work resolution, skip work, or run a separately optimized
queue. This supports the reduced-resolution residual direction, but it does
not imply that our current student has learned the native residual function.

## Why the new public checkpoint matters — and what it does not prove

The public `taowen/dlss5-as-inpainting` repository is useful because it makes
the native-output distillation recipe concrete: native input/output pairs are
used to train an ordinary portable PyTorch model. That is a useful comparison
point for our training code.

It is not evidence that the checked-in portable checkpoint is a fast,
high-fidelity clone. Its shipped model is a small RGB residual network; its
optional depth/history/motion/mask arguments do not make the supplied
RGB-trained checkpoint temporally equivalent to native DLSS5. The local
recheck of that checkpoint on the retained Skyrim validation tranche found a
regression against the raw input baseline, so it remains research-only.

The distinction is important:

* distillation transfers a visual function into ordinary weights;
* NVIDIA-speed inference also depends on fused, hardware-specific kernels,
  memory layouts, Tensor Core scheduling, and the native integration path;
* a small PyTorch checkpoint does not inherit those optimized kernels.

This is consistent with the public reverse-engineering evidence: the
`neural-upstream` project reports that the native neural kernels can be
recompiled and measured in a few milliseconds on an RTX 4070 Ti without
changing the model weights, while independent graph implementations remain
much slower. That points to runtime/kernel structure, not merely checkpoint
size, as the principal speed gap.

## Local experiment

Source sequence:

`C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789063628889-1`

The replay uses frames 1–8 from the same sequence, both eyes, with a reset on
the first frame and state carried through the remaining frames. The full
resolution is 2496×2688 and the 50% native neural resolution is 1248×1344.
The native pass uses the saved exact guide resources; only the color input is
reduced for this scale experiment. Frames 1–6 are used for the small offline
fit and frames 7–8 are held out. Because the held-out frames are from the
same sequence, this is not sequence-disjoint generalization evidence.

The reduced native output is compared with the original full-resolution
native teacher by two composition strategies:

```text
naive:   upsample(small_output)
matched: full_source + upsample(small_output - small_input)
```

The matched residual is the useful baseline. On the 16 eye samples from the
eight-frame replay, its MAE was about 0.01219, versus about 0.02008 for direct
upsampling. It is materially better than the raw input, but far above the
current desired 0.0013–0.0015 drift range.

## Resolver quality on the held-out suffix

All numbers below are mean RGB MAE on four held-out eye samples: frames 7–8,
both eyes.

| Resolve branch | Held-out MAE | Change vs naive | Notes |
|---|---:|---:|---|
| Raw input identity | ~0.02237 | — | Full-resolution source without reduced neural edit |
| Matched residual baseline | 0.012524 | — | No learned correction |
| RGB student, 24 hidden / 2 pointwise layers | 0.012398 | −0.000126 | Better on all four held-out samples |
| RGB student, 4 hidden / 1 pointwise layer | 0.012378 | −0.000146 | Much smaller, still only a small gain |
| Guide-conditioned student, 24 hidden + depthwise 3×3 | 0.012376 | −0.000148 | Guides add little quality on this tranche |
| Per-pixel affine correction | **0.012056** | **−0.000468** | No spatial convolution; fitted on frames 1–6; 50% scale |

For comparison, fitting the same affine form specifically at 75% scale gave
held-out MAE 0.007914 versus 0.008055 for the 75% naive residual, a smaller
0.000141 gain. The higher scale is already much closer to the teacher before
the correction, so there is less error for a global affine map to remove.

The fused Triton implementation reproduces these held-out results within
FP16 rounding: 50% validation MAE 0.012056 versus 0.012524 naive, and 75%
validation MAE 0.007914 versus 0.008055 naive. It improves all four held-out
eye samples at both scales. The fused kernel is therefore a valid runtime
implementation of the tested affine composition, not just a timing-only
placeholder. Across frames 1–8 at 50%, its mean frame-to-frame delta was
0.004793 versus 0.004970 for naive residual and 0.005427 for the full teacher;
the fused-vs-teacher delta error was 0.003761 versus 0.003861 for naive. This
is a useful stability signal, but not a perceptual flicker or headset test.

The affine result is the strongest quality result in the initial one-sequence
pilot, but the sequence-disjoint control is now complete and did not produce
a generalization gain. A global affine fit from sequences 1 and 2 measured
0.022070 MAE on unseen sequence 4, slightly worse than the direct native
residual at 0.021967 MAE, and it was better for only 14 of 32 eye samples.
It remains a useful cheap control, not evidence of a general DLSS5
reconstruction.

The fitted feature order is `[1, rgb_r, rgb_g, rgb_b, edit_r, edit_g, edit_b]`.
The implementation is intentionally simple enough to fuse into a single
compute shader that reads the full source and the reduced neural edit without
materializing a seven-channel feature tensor.

## Runtime measurements

The steady native 50% replay measured a median of approximately 6.850 ms GPU
for both eyes and 7.576 ms wall time for frames 2–8. The first frame is
excluded from the steady-state comparison because it contains initialization
and reset costs.

The following measurements are resident-tensor measurements on the RTX 5070
Ti. They cover only the full-resolution resolve; they exclude input format
conversion, copies, the native neural pass, synchronization with the game,
and the compositor.

| Full-resolution resolve | FP16, both eyes | Relative implication |
|---|---:|---|
| Direct matched residual | 0.456 ms | Fast baseline |
| Per-pixel affine in PyTorch | 2.474 ms | Unfused reference; includes feature construction and 1×1 convolution |
| Fused affine Triton kernel, 50% scale | **0.299 ms** | One dispatch per eye; includes bilinear edit sampling and affine correction |
| Fused affine Triton kernel, 75% scale | **0.332 ms** | One dispatch per eye; slightly higher source-read/cache cost |
| RGB student, 4 hidden / 1 layer | 5.728 ms | Too much overhead for the small quality gain |
| RGB student, 24 hidden / 2 layers | 13.192 ms | Not viable on top of the reduced native pass |
| Guide-conditioned student | 21.476 ms | Clearly not viable for this route |

Approximate resident GPU sums are therefore about 7.15 ms for native 50% plus
the fused affine resolve, 7.31 ms for native 50% plus the direct residual,
9.32 ms for native 50% plus the unfused affine PyTorch resolve, 12.58 ms for
the smallest neural resolver, 20.04 ms for the larger RGB resolver, and 28.33
ms for the guided resolver. At 75%, native steady-state GPU work was about
13.15 ms for both eyes; adding the fused affine resolve was about 13.50 ms.
A small launch sweep on the 50% case found the result was stable across
reasonable configurations: block 128 / 2 warps measured 0.301 ms, block 256 /
4 warps 0.299 ms, block 512 / 2 warps 0.308 ms, and block 1024 / 8 warps
0.296 ms. The chosen 256 / 4 configuration is therefore representative rather
than a lucky outlier.
These are not end-to-end VR frame times; game rendering, copies, integration,
and compositor work must still fit in the frame budget.

The first benchmark run produced an anomalous 442 ms concurrent guided FP16
measurement. That was reproduced only in the original harness sequence. The
harness was corrected to use inference mode and fixed-shape cuDNN selection;
the stable rerun was 21.476 ms. The anomalous value is not used here.

## Existing FastStudent-v1 speed check

The repository already contained a separate low-resolution-core architecture
(`FastStudentV1`), so it was benchmarked without a checkpoint to answer the
architecture question before starting another training run. These are
isolated CUDA timings on the RTX 5070 Ti, one eye, FP16, synthetic resident
tensors; they are not quality or in-game measurements.

| FastStudent input/work size | Parameters | Steady time, one eye |
|---|---:|---:|
| 2496x2688 (full eye) | 346,072 | 33.1 ms |
| 1248x1344 (half eye) | 346,072 | 9.1 ms |
| 896x832 (approximately one-third eye) | 346,072 | 4.6 ms |
| 1248x1344, smaller 99k-parameter config | 99,176 | 3.6 ms |

The full-resolution call remains about 33 ms even when its optional learned
native-refine convolution is disabled. That ablation did not change the
measurement, which means the cost is distributed across the model's repeated
convolutions, resizes, and recurrent path. Supplying guides at native guide
resolution versus a much smaller guide tensor also changed the timing very
little. This is additional local evidence that parameter count alone is not
the runtime answer.

Calling the same student at half resolution and compositing its output back
onto a full native frame is therefore the right shape of experiment, but the
default 346k model would still be about 18.2 ms for two eyes before the
full-resolution resolve. The smaller 99k configuration is about 7.1 ms for
two eyes before resolve, which is in the interesting speed range but has not
been trained or quality-tested. The approximately one-third configuration is
about 9.1 ms for two eyes before resolve and is likewise only a timing result.

This changes the practical target: the next student should be trained to
predict a reduced-resolution residual, not a complete full-resolution RGB
frame. The full-resolution operation should remain a fused compositor of the
kind measured here, with no learned full-resolution convolution in the
critical path.

## TensorRT runtime result

TensorRT 10.13.3.9 CUDA 12 bindings were installed in the isolated
`C:\OpenNR\Tools\OpenNRTrainVenv` environment. Fixed-shape FP16 engines were
exported from the actual trained checkpoints; no engine was installed into a
game or live OpenNR deployment.

| Trained branch | Work size | TensorRT steady, one eye | Approx. two-eye neural time |
|---|---:|---:|---:|
| 346k wider student | 1248x1344 | 1.767 ms | 3.53 ms |
| 99k smaller corrected student | 1248x1344 | 1.063 ms | 2.13 ms |
| 346k wider control | 2496x2688 | 7.326 ms | 14.65 ms |

The 346k half-work engine was compared with its FP16 PyTorch checkpoint on
reset and recurrent frames. Prediction mean absolute error was about
`5.1e-6`; the 99k trained engine was about `3.1e-6`. Hidden-state differences
were on the order of `5e-5` to `8e-5`, with finite outputs. This verifies that
TensorRT is accelerating the same learned function rather than silently
changing it.

Adding the measured fused full-resolution residual resolve (~0.30 ms for both
eyes) gives rough resident-GPU sums of ~3.83 ms for the wider half-work branch
and ~2.54 ms for the smaller branch. These sums exclude capture, format
conversion, resource transitions, synchronization, game rendering, and
headset/compositor work. They are therefore a genuine neural speed result,
not an end-to-end VR frame-budget result.

## Full-eye TensorRT replay of the reduced residual route

To test the public NeuralScreen pattern against an actual retained Skyrim
sequence, the trained 346k checkpoint was run through the fixed-shape FP16
TensorRT engine on frames 1–8 of the full-eye replay, separately for both eyes.
The work surface was 1248×1344 (50% of the 2496×2688 eye), while the original
2496×2688 RGB frame remained the compositor anchor. The evaluator rebuilt the
five-channel guide bundle from the exact captured Feature 18 depth and motion
resources, created the eight-channel context from the full-eye input and
guides, reset at frame 1, and carried recurrent state through frames 2–8.

The three-way result is the most useful local answer to the new public finding:

| Full-eye branch | Mean MAE to full native teacher | Mean change vs raw input | Interpretation |
|---|---:|---:|---|
| Raw full-resolution input | 0.022156 | — | Untouched anchor |
| Native 50% residual composite | **0.012190** | **−0.009966** | The reduced-work route itself works materially better than identity |
| Current trained FastStudent composite | 0.021986 | −0.000170 | Fast, but effectively near-identity; not native-look imitation |

The student was better than the raw input on only 8 of 16 eye-frame samples,
whereas the native 50% residual composite improved all 16. The student-to-native
50% composite MAE was about 0.02043, and the student work output differed from
the recorded reduced native output by about 0.02145 MAE. This is not a small
quantization drift; it means the checkpoint is producing the wrong function at
full-eye scale. It was selected on crop-cache validation and was not trained on
this full-eye residual target, so this result diagnoses the training/target
gap rather than proving that the architecture cannot learn the route.

Because the first replay engine used a 48×48 context binding, the same replay
was repeated with a second engine using the training-time 96×96 context. The
student MAE changed only from `0.021985799` to `0.021985927`, while the native
50% residual reference stayed at `0.012190273`. TensorRT-versus-PyTorch
prediction parity on the 96×96 engine remained about `5.3e-6` mean absolute
error with finite recurrent state. The context binding size is therefore not
the explanation for the quality gap; the evidence points back to the learned
target/objective and full-eye generalization.

## Corrected reduced-native target experiment

The previous student result had an important objective mismatch: it was
selected from crop-cache training and was not explicitly trained to reproduce
the recorded reduced native neural output. A separate 99,176-parameter
`FastStudentV1` was therefore trained against the exact reduced native work
target from this retained replay. Its full-resolution output is composed as

```text
full_source + upsample(student_work - reduced_work_input)
```

The run used frames 1–6 for fitting, frames 7–8 as the held-out suffix, the
same exact five-channel guides and stateful context, 96×96 context binding,
and 200 steps. It used no new Skyrim captures. This is still one sequence, so
it is a target/objective diagnostic rather than generalization evidence.

| Corrected-target branch | Held-out frames 7–8, 4 eye samples | Full frames 1–8, 16 eye samples |
|---|---:|---:|
| Raw full-resolution input, versus full native teacher | 0.022374 | 0.022156 |
| Native 50% residual composite, versus full native teacher | **0.012524** | **0.012191** |
| 99k corrected-target student composite, versus reduced native target | 0.017828 | 0.017316 |
| 99k corrected-target student composite, versus full native teacher | 0.019251 | 0.018896 |

The corrected objective is a real improvement: on the held-out suffix it
reduces error versus the raw identity from `0.021314` to `0.017828` when both
are measured against the reduced native target, about 16.4%. Against the full
native teacher, it reduces the held-out error from `0.022374` to `0.019251`,
and on the full replay it improves all 16 eye-frame samples. It is nevertheless
still well behind the direct native 50% residual composite, and nowhere near the desired
`0.0013–0.0015` drift. This is the first evidence that the student can learn
the intended reduced-work edit at all; it is not evidence that the current
capacity, loss, or data split is sufficient.

The corresponding fixed-shape TensorRT FP16 engine preserves the learned
function and reaches the intended speed class. The clean isolated benchmark
measured `1.0488 ms` reset median and `1.0634 ms` steady median per eye, with
`1.0914 ms` steady p95 over 100 iterations. In the stateful full-eye replay,
stable frames measured about `1.05–1.10 ms` per eye for the network and about
`1.45–1.53 ms` per eye including the full-resolution residual resolve. A
serial two-eye estimate is therefore roughly `2.13 ms` for the network or
about `2.9–3.1 ms` including this resolve, before integration and compositor
costs. The first/reset timing outlier is excluded from those steady estimates.

This changes the diagnosis of the project:

* The reduced-resolution residual architecture plus an owned compiled runtime
  can be faster than the public native-NeuralScreen network numbers on this
  GPU, at least for the isolated neural portion.
* Quantizing or compiling the recovered 145.8M graph is no longer the most
  promising route to a VR-speed look approximation. The structural reduction
  already solved the latency class for a small model.
* The remaining problem is learning the right reduced native edit: target
  definition, sequence diversity, temporal loss/state training, and capacity.
  More generic kernel tuning will not turn the current near-identity output
  into native DLSS5 quality.

The corrected-target training script, checkpoint, replay result, engine, and
clean speed measurement are:

* `D:\.CODEX_Projects\OpenNR-VR\tools\train_fast_student_reduced_native_target_20260912.py`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_native50_target_h16_m32_t32_b1_20260912\best.pt`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_native50_target_h16_m32_t32_b1_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_native50_target_h16_m32_t32_b1_context96_20260912\fast_student_v1_fp16_io.engine`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_native50_target_full_eye_seq1_context96_20260912\result.json`

The engine benchmark is an isolated resident-tensor measurement, not a live
Skyrim frame-time test. No engine, checkpoint, or evaluator was installed in
the live OpenNR/MGO path.

## Sequence-disjoint replay and multi-sequence check

The retained tranche contained more usable data than the first pilot used, so
the next gate was completed without collecting new captures. A second native
50% replay was generated from sequence `seq-1789063658490-2`, and additional
replays were generated from sequences `seq-1789064251836-4` and
`seq-1789064397821-5`. Each replay used 16 contiguous frames, reset only on its
first frame, and kept the exact captured depth and motion resources. All three
native replays remained finite and the matched residual improved every one of
their 32 eye-frame samples.

| Sequence | Raw identity vs full teacher | Native 50% residual vs full teacher | Improvement | Better samples |
|---|---:|---:|---:|---:|
| First pilot sequence | 0.022156 | **0.012190** | 0.009966 | 16/16 |
| Sequence 2 | 0.031415 | **0.017993** | 0.013422 | 32/32 |
| Sequence 4 | 0.046942 | **0.021967** | 0.024974 | 32/32 |
| Sequence 5 | 0.033999 | **0.019563** | 0.014436 | 32/32 |

The native reduced route is therefore repeatable, but its absolute drift is
content-dependent. This is expected for an aggressive 50% work reduction and
is why a single-sequence student score cannot be used as a general quality
claim.

The single-sequence 99k student was then run unchanged on sequence 2. It
regressed badly: MAE `0.045319` versus identity `0.031414`, with 0/32 samples
beating identity. This confirmed that the earlier improvement on sequence 1
was not a general solution.

To test whether data diversity was the missing ingredient, a separate 99,176-
parameter student with the same corrected reduced-native target was trained on
sequence 1 frames 1–6 and sequence 2 frames 1–12. Its best checkpoint was
continued to 100 total steps, with sequence 1 frames 7–8 and sequence 2
frames 13–16 used only for in-domain held-out validation. The independent
sequence 4 was never used for fitting.

On sequence 4, the multi-sequence student produced:

```text
raw identity vs full teacher:       0.046942
multi-sequence student:             0.044083
native 50% residual reference:      0.021967
student improvement:                0.002859
student better than identity:       32/32 samples
```

This is a real generalization improvement over the single-sequence student,
but it is still only about 6.1% relative improvement over identity and remains
roughly twice the native 50% residual error. The student is learning a useful
generic correction, not the native DLSS5 edit.

On the untouched sequence 5, the same checkpoint instead produced `0.035904`
MAE versus `0.033999` for raw identity, improving only 6/32 samples. The
sequence 4 gain is therefore not yet robust across retained content. This
strengthens the diagnosis that the current 99k capacity/objective is learning
a weak generic bias rather than the native reduced-resolution edit.

## 346k capacity-control feasibility check

A bounded 346k-parameter control was attempted with sequences 1, 2, and 4 for
fitting and sequence 5 held out. The initial full 75%-of-sequence unroll
completed finite step-0 validation but ran out of memory on the first backward
pass: the 16-GB GPU reported approximately 29.3 GiB allocated while retaining
the full-eye tensors and gradient graph for all three sequences. A retry using
only four training frames per sequence completed finite step-0 validation and
one finite optimization step, but that step took about 165 seconds. It was
stopped at that point; no quality conclusion is drawn for 346k.

This was a trainer memory/throughput limitation, not evidence that the larger
student cannot learn the target. The trainer was then changed to stream one
frame at a time from CPU replay metadata, use truncated BPTT, and keep
validation separate from the training graph. That makes a larger capacity
experiment feasible, but does not by itself improve the target function.

## Streamed 346k crop/BPTT capacity check

The streamed trainer was smoke-tested and then run for a bounded ten-step
capacity check. It used the same sequence-disjoint split as the completed 99k
study: sequences 1, 2, and 4 for fitting, sequence 5 untouched for testing. The
fit portion was the first half of each training sequence (4/8 frames from
sequence 1 and 8/16 from sequences 2 and 4), with exact reduced-native targets,
512-pixel aligned work crops, 96x96 context, and four-frame truncated BPTT. The
model had 346,072 parameters. It completed with finite values in 103.4 seconds;
the best held-out work MAE occurred at step 5 (`0.036235`).

On the blind sequence-5 replay (all 16 frames, both eyes, 32 samples), the
best-step checkpoint measured:

```text
student composite vs full native teacher: 0.033910
raw identity vs full native teacher:       0.033999
native 50% residual reference:             0.019563
student improvement vs identity:           0.000089
student better than identity:              30/32 samples
```

This is a small positive blind gain, but it remains far from the direct native
50% residual and is not a robust quality result. The step-5 validation slice
was slightly better than identity (`0.033975` vs `0.034213`), while the final
step regressed (`0.035042`), again showing that early stopping and validation
cadence matter. Because the run used aligned crops and truncated BPTT, it is a
capacity/training-feasibility diagnostic rather than full-frame temporal parity.
It proves that the 346k branch can now be trained without the previous OOM or
165-second single-step failure; it does not justify more captures, a runtime
export, or promotion of the branch.

As a cheap calibration control, a seven-feature global affine resolver was fit
on the native residuals from sequences 1 and 2 and evaluated on sequence 4.
It measured `0.022070` MAE versus `0.021967` for the unmodified native 50%
residual, improving only 14/32 samples. A global color mapping does not explain
the cross-sequence gap; the missing information is spatial/content-conditioned
and likely temporal as well.

These results narrow the next engineering choice. The latency-class result is
already credible for the 99k/346k architecture family, while the quality
problem is not solved by a global affine head or by a small multi-sequence fit.
The same multi-sequence checkpoint was also evaluated on retained sequence 5:
it produced `0.035904` MAE versus `0.033999` for raw identity, improving only
6/32 samples. Sequence 4's modest gain therefore does not yet establish robust
generalization. The streamed 346k capacity control was then tested on that same
blind sequence: it reached `0.033910` versus `0.033999` for identity, while the
native 50% residual was `0.019563`. Thus the larger model is now proven
trainable, but not yet useful enough to justify a new engine or another large
capture/training spend.

The new replay, training, and control artifacts are:

* `D:\.CODEX_Projects\OpenNR-VR\out\native_sequence_scale_50_seq2_f1-16_20260912\input_manifest.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\native_sequence_scale_50_seq2_f1-16_eval_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\native_sequence_scale_50_seq4_f1-16_20260912\input_manifest.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\native_sequence_scale_50_seq4_f1-16_eval_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\native_sequence_scale_50_seq5_f1-16_20260912\input_manifest.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\native_sequence_scale_50_seq5_f1-16_eval_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_native50_target_full_eye_seq2_context96_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_native50_target_multiseq12_h16_m32_t32_b1_cont50_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_native50_target_multiseq12_test_seq4_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_native50_target_multiseq12_test_seq5_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_native50_target_multiseq124_h32_m64_t64_b2_50steps_20260912\history.jsonl`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_native50_target_multiseq124_h32_m64_t64_b2_short4f_20260912\history.jsonl`
* `D:\.CODEX_Projects\OpenNR-VR\tools\train_fast_student_reduced_native_multiseq_20260912.py`
* `D:\.CODEX_Projects\OpenNR-VR\tools\train_fast_student_reduced_native_streaming_20260912.py`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_native50_target_streaming346_crop512_bptt4_10steps_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_native50_target_streaming346_crop512_bptt4_half10_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\visual_comparison_seq5_students_20260912\frame_00000008_eye0_full_comparison.jpg`
* `D:\.CODEX_Projects\OpenNR-VR\out\visual_comparison_seq5_students_20260912\frame_00000008_eye0_face_comparison.jpg`
* `D:\.CODEX_Projects\OpenNR-VR\out\visual_comparison_seq5_students_20260912\frame_00000001_eye0_detail_comparison.jpg`
* `D:\.CODEX_Projects\OpenNR-VR\out\visual_comparison_seq5_students_20260912\frame_00000016_eye0_detail_comparison.jpg`
* `D:\.CODEX_Projects\OpenNR-VR\tools\evaluate_fast_student_reduced_native_checkpoint_20260912.py`
* `D:\.CODEX_Projects\OpenNR-VR\tools\fit_affine_scale_resolve_multiseq_20260912.py`

The 346k timing above remains about 1.78 ms per eye in steady state. A newer
clean resident benchmark of the corrected 99k engine measured 1.0488 ms on
reset, 1.0634 ms steady-state median, and 1.0914 ms steady-state p95 per eye.
Its stable integrated full-eye pass was about 1.05–1.10 ms per eye for the
network and about 1.45–1.53 ms per eye including the full-resolution residual
resolve. With batch-1 serial stereo, that is roughly 2.13 ms for neural work or
2.9–3.1 ms including this simple resolve. These numbers exclude host I/O,
input copies, resource transitions, the game render, and the SteamVR
compositor. A first integrated timing attempt interleaved full-frame CPU
readbacks and produced alternating 2–27 ms event values; that cross-stream
artifact is excluded from the speed conclusion and the harness now keeps the
sequence on the engine stream until timing is complete.

The reproducible full-eye evaluator and result are:

* `D:\.CODEX_Projects\OpenNR-VR\tools\evaluate_fast_student_trt_full_eye.py`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_full_eye_seq1_context48_rerun_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_full_eye_seq1_context96_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_full_eye_seq1_context48_rerun_20260912\previews\`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_half_trained_h32_m64_t64_b2_context96_20260912\engine_manifest.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_half_trained_h32_m64_t64_b2_context96_20260912\numerical_check.json`

The preview images are useful for visual inspection, but they are not a
headset or motion-quality acceptance test. The exact native 50% composite is
visibly much closer to the full native teacher than the current student; this
is why more generic runtime optimization should pause until the student is
trained against the correct residual target.

The earlier crop-cache-trained checkpoints were the first local result to meet
the *speed shape* of the goal with an actual learned checkpoint, but they did
not meet the quality goal: the wider 50% checkpoint's untouched test-crop MAE
was `0.021797`, and the smaller checkpoint's was `0.021591`, versus identity
`0.023105`. Both improved the static crop score by roughly 5.7% and 6.6%,
respectively, but both had a small temporal-delta regression. The corrected
reduced-native-target run above is the more relevant student result; it learns
more of the desired edit, but it is still not close to the desired
`0.0013–0.0015` teacher drift and has not been tested in a live Skyrim frame
path.

## What this means for OpenNR-VR

The public checkpoint release validates the *idea* of distilling native
outputs, but it does not make the recovered 71-block graph cheap. Our local
measurements give three separate conclusions:

1. A full-resolution learned correction is the wrong place to spend the VR
   budget. Even a tiny pointwise network costs several milliseconds and makes
   too little quality difference on the current tranche.
2. Reduced native processing plus a direct matched residual is the best speed
   baseline tested. It is fast enough to be interesting, but its static drift
   is around 0.012 rather than 0.0013–0.0015.
3. A fused affine or similarly tiny shader is worth one isolated engineering
   test. It might preserve most of the residual baseline's speed while
   recovering a small amount of the lost look. It should be treated as a
   look approximation, not as evidence of native parity.

The target of matching NVIDIA's few-millisecond runtime still requires one of
two fundamentally different outcomes:

* use the native NVIDIA runtime/kernels where the hardware permits it; or
* implement a substantially smaller network or fused low-resolution pipeline
  whose total work is designed around the VR budget from the beginning.

Quantizing the full recovered graph alone is unlikely to bridge the gap. The
profiling evidence says the work is distributed across many token-scaled
blocks; reducing representation precision can help, but it cannot remove the
large number of fused attention/MLP/data-movement stages that NVIDIA executes
as specialized kernels.

The NeuralScreen result makes the structural option more concrete for the
student/look branch: reducing *neural work resolution* is a measured lever,
whereas reducing only storage precision is not enough. It still does not
establish that our portable PyTorch model can reach the same numbers; the
local FastStudent benchmark shows that ordinary PyTorch has substantial
overhead even for a much smaller network.

## Recommended next experiment

The sequence-disjoint gate is now stronger than the original two-sequence
check. It says the current 99k student is fast enough in its compiled form but
is not yet a reliable learned replacement for the native reduced residual.
The next step is therefore a bounded retained-data capacity/generalization
study, not a large new capture purchase and not more optimization of the
recovered 145.8M graph:

1. Keep the four existing native 50% replays for sequences 1, 2, 4, and 5.
   Keep exact depth and motion, reset at sequence start, carry history within
   each sequence, and reserve sequence 5 as an untouched test set. Optional
   additional replays can be made from the remaining retained tranche later;
   no new Skyrim capture is needed now.
2. Do not repeat the same short crop run merely to accumulate steps. If one
   more offline quality run is justified, use the new streamed trainer with a
   full-frame or multiscale curriculum, longer state-aware unrolls, and the
   same sequence-disjoint test. The target remains the reduced native work
   output, composed back over the full native anchor.
3. Report work-output MAE, full-composite MAE, native-residual MAE,
   frame-to-frame delta error, and per-category results for faces, hair,
   armor, foliage, dark interiors, and bright exteriors. The student must
   beat the raw-input baseline in a blind visual review on an untouched
   sequence, show a repeatable neural look without artifacts, and remain
   temporally stable. Native-residual distance stays as a secondary diagnostic
   rather than a required pixel-match gate.
4. Keep the global affine correction as the cheap control. It is worth porting
   to the actual HLSL/CUDA path only as an optional look approximation; the
   multi-sequence result currently gives no aggregate unseen-sequence gain.
5. Export a new 346k TensorRT engine only if the larger model shows a real
   sequence-disjoint quality gain. The existing corrected 99k engine measures
   about 1.06 ms per eye in a clean resident TensorRT benchmark, so another
   engine build is not the current bottleneck.
6. Do not promote either branch to the live OpenNR runtime until exact Feature
   18 resource ownership, temporal reset behavior, stereo output, headset
   presentation, and frame-budget behavior are separately verified.

If the 99k and 346k branches remain near the current sequence-disjoint result
after one properly state-aware streamed run, stop treating this architecture as
a native residual replacement. Keep the direct native 50% residual as a fast
experimental DLSS5-look branch, then compare a still smaller/⅔-resolution
student or a different conditioned architecture. This ordering keeps any new
data request evidence-driven.

The first scale-conditioned training phases show that early stopping is
required. The 50% wider phase peaked at step 250 and then overfit; the lower
learning-rate/stronger-delta phase also peaked at step 250. The 99k phase
showed the same pattern. This is not evidence that the architecture is
finished; it is evidence that another large uninterrupted training run would
be wasteful until the temporal objective and validation cadence are adjusted.

The new reproducible artifacts are:

* `D:\.CODEX_Projects\OpenNR-VR\tools\fit_affine_scale_resolve_20260912.py`
* `D:\.CODEX_Projects\OpenNR-VR\tools\benchmark_scale_resolve_student_20260912.py`
* `D:\.CODEX_Projects\OpenNR-VR\tools\benchmark_affine_fused_triton_20260912.py`
* `D:\.CODEX_Projects\OpenNR-VR\out\affine_scale_resolve_50_seq1_f1-8_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\affine_fused_triton_50_frame1_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\affine_fused_triton_50_f1_7_8_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\affine_fused_triton_50_full_validation_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\affine_scale_resolve_75_seq1_f1-8_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\affine_fused_triton_75_frame1_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\affine_fused_triton_75_f1_7_8_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\native_sequence_scale_50_seq1_f1-8_eval_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\native_sequence_scale_75_seq1_f1-8_20260912\timings.csv`
* `D:\.CODEX_Projects\OpenNR-VR\out\scale_resolve_student_rgb_h4_l1_50_seq1_f1-8_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\scale_resolve_student_50_seq1_f1-8_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\scale_resolve_guided_student_50_seq1_f1-8_20260912\result.json`
* `D:\.CODEX_Projects\OpenNR-VR\tools\fast_student_v1.py`
* `D:\.CODEX_Projects\OpenNR-VR\tools\benchmark_fast_student.py`
* `D:\.CODEX_Projects\OpenNR-VR\tools\train_fast_student.py`
* `D:\.CODEX_Projects\OpenNR-VR\tools\compare_fast_student_trt.py`
* `D:\.CODEX_Projects\OpenNR-VR\tools\evaluate_fast_student.py`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_scale50_h32_m64_t64_b2_lr5e5_delta05_20260912\best_mae.pt`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_scale50_h32_m64_t64_b2_lr5e5_delta05_20260912\test_result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_scale50_h16_m32_t32_b1_lr5e5_delta05_20260912\best_mae.pt`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_scale50_h16_m32_t32_b1_lr5e5_delta05_20260912\test_result.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_half_trained_h32_m64_t64_b2_20260912\engine_manifest.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_half_trained_h32_m64_t64_b2_20260912\numerical_check.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_half_trained_h16_m32_t32_b1_20260912\engine_manifest.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_half_trained_h16_m32_t32_b1_20260912\numerical_check.json`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_half_trained_h32_m64_t64_b2_20260912\fast_student_v1_fp16_io.engine`
* `D:\.CODEX_Projects\OpenNR-VR\out\fast_student_trt_half_trained_h16_m32_t32_b1_20260912\fast_student_v1_fp16_io.engine`

All outputs are isolated under `out`; no live Skyrim, MGO, Feature 18, or
known-good deployment files were changed. The experiment records
`promotion=false` and `live_runtime_tested=false`; that status remains in force
for the pilot.

## Public references

* [DLSS5-NeuralScreen v1.7.0 release](https://github.com/perseval-BLR/DLSS5-NeuralScreen/releases/tag/v1.7.0)
* [DLSS5-NeuralScreen source](https://github.com/perseval-BLR/DLSS5-NeuralScreen)
* [DLSS5-NeuralScreen technical notes](https://github.com/perseval-BLR/DLSS5-NeuralScreen/blob/main/TECHNICAL.md)
* [taowen/dlss5-as-inpainting](https://github.com/taowen/dlss5-as-inpainting)
* [neural-upstream findings](https://github.com/matiasLombo/neural-upstream/blob/main/FINDINGS.md)
* [DLSS-NR-on-AMD kernel-optimization RFC](https://github.com/danielblnc/DLSS-NR-on-AMD/issues/113)
