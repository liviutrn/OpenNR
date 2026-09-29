# Native internal-scale and residual composition study

Date: 2026-09-12  
Status: offline research evidence only; `promotion=false`

## Question

Can the speed technique exposed by recent public DLSS-NR proxy projects help
OpenNR: evaluate the neural path at a reduced internal resolution, then keep
the original full-resolution render as an anchor and transfer only the neural
edit back to it?

This is distinct from ordinary upsampling. For a reduced native result `N` and
reduced input `I`, the two tested reconstructions are:

```text
direct       = upsample(N)
matched      = full_resolution_input + upsample(N - I)
```

The second form is a matched residual resolve. It is an offline replay of
stored native outputs; this tool did not call the NVIDIA DLL and did not alter
the Skyrim/MGO installation.

## Inputs and provenance

- Source sequence: `C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789063628889-1`
- Frame: `1`, both eyes
- Full color shape: `2496 x 2688`
- Native guide shape used by the source study: `1664 x 1792`
- Reduced native inputs/outputs: `out/native_teacher_resolution_study_20260912/`
- Native timing source: the registered `native_feature18_resolution_only`
  study, whose `pair_*` timings cover both eyes
- Full-resolution comparison target: the original saved native Feature 18
  teacher output for the same frame and eye
- Color representation: stored packed RGBA8, RGB normalized to `[0, 1]`
- Resize/resolve: PyTorch bilinear interpolation with `align_corners=False`

The study's original scope is a network-cost measurement: it excludes the
renderer downsample and full-eye resolve passes. The residual timings below
are likewise only the offline upsample/add/clamp portion, not a complete game
integration cost.

## Result

The residual branch is consistently better than directly enlarging the small
native output. It preserves the high-frequency information already present in
the full-resolution source instead of asking the low-resolution neural result
to recreate every pixel.

| Internal scale | Network shape | Area | Native pair GPU ms | Native pair wall ms | Offline resolve ms / eye | Direct MAE vs full native | Matched residual MAE | Residual minus direct |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100% | 2496 x 2688 | 1.000 | 23.148 | 24.066 | 1.472 | 0.00000 | 0.00000 | ~0.00000 |
| 90% | 2246 x 2419 | 0.810 | 19.331 | 20.150 | 1.087 | 0.01254 | 0.00824 | -0.00430 |
| 85% | 2122 x 2285 | 0.722 | 17.459 | 18.119 | 1.063 | 0.01291 | 0.00841 | -0.00451 |
| 75% | 1872 x 2016 | 0.563 | 13.642 | 14.380 | 1.019 | 0.01401 | 0.00924 | -0.00477 |
| 50% | 1248 x 1344 | 0.250 | 6.936 | 7.587 | 1.233 | 0.02103 | 0.01330 | -0.00773 |
| 33% | 824 x 887 | 0.109 | 4.691 | 5.390 | 0.890 | 0.02920 | 0.01922 | -0.00998 |

For reference, the full-resolution source itself is `0.02137` MAE from the
full native teacher on this two-eye frame. The 33% residual branch therefore
still improves the source slightly, while the direct 33% image is worse than
the source. This is a useful demonstration of the anchor's value, not evidence
that 33% is visually acceptable for VR.

The native pair wall time alone falls by approximately `1.67x` at 75%, `3.17x`
at 50%, and `4.46x` at 33% relative to the 100% native network study. Adding
two copies of the measured offline resolve as a rough stereo proxy gives about
`16.42 ms` at 75%, `10.05 ms` at 50%, and `7.17 ms` at 33%. Those sums are
directional only: downsample, resource transitions, queue overlap, and the
actual compositor are not represented.

## Interpretation for OpenNR

This validates the central structural idea behind the new public speed leads:

1. The expensive network should not process the entire final-resolution image
   if the target quality can be recovered from a lower-resolution edit.
2. A full-resolution source anchor is important. Directly upsampling the neural
   image loses too much native detail, especially at 50% and below.
3. The naive residual resolve is not sufficient for the current quality goal.
   Even the 75% branch is `0.00924` MAE on this single frame, well above the
   current approximately `0.0013–0.0015` drift tolerance discussed for the
   recovered path.
4. A trained residual/resolve network is the plausible next step. It would
   receive the full-resolution source, the low-resolution neural result/edit,
   and the native guides, and learn where the low-resolution edit should be
   trusted or suppressed. It must be trained and evaluated on held-out,
   sequence-disjoint full-eye data; it cannot be judged from this one frame.
5. The public tiny portable checkpoint is not the right teacher for this
   experiment by itself. Its current retained-sequence recheck regressed
   against the input, so a low-resolution version of that weak checkpoint would
   mostly measure the resolve trick rather than a useful DLSS5 approximation.

The most promising owned-runtime design is therefore:

```text
full-resolution RGB + exact Feature 18 guides
                 |
                 +--> reduced-resolution neural student / recovered path
                 |          |
                 |          +--> low-resolution edit
                 |
                 +--> full-resolution guided residual resolve
                            |
                            +--> final RGB
```

The resolve should be shallow and fused in the final runtime. It should not
become a second full-resolution neural network, or it will give back the saved
time. At the first implementation stage, compare a fixed 75% and 50% branch;
33% is useful as a lower-bound stress point but is already visibly risky.

## Relation to current public evidence

The official NVIDIA DLSS5 description says inference is conditioned on the
current rendered frame, engine motion vectors, carried temporal state, and
artistic direction, under a strict per-frame budget. That supports retaining
the exact guide/state contract while changing only internal neural resolution.

The public `neural-upstream` result is evidence that native kernel engineering
can reduce a reconstructed network to millisecond scale, but it does so by
rebuilding NVIDIA's fused PTX/SASS execution path. It does not show that the
ordinary PyTorch 71-block graph will reach the same cost through quantization
alone.

The public `DLSSNR-Cost-Scaler` and `dlss5-anywhere` projects expose the more
portable structural lever: lower internal processing scale, then a full-size
correction/resolve. Their reported controls are useful implementation leads,
but their own proxy behavior and quality claims are not native OpenNR
acceptance evidence.

## Reproduction artifacts

- Evaluator: [`evaluate_native_scale_residual_curve_20260912.py`](../tools/evaluate_native_scale_residual_curve_20260912.py)
- Result JSON: [`result.json`](../out/native_scale_residual_curve_20260912/result.json)
- 75% visual sheet: [`eye0_scale075.jpg`](../out/native_scale_residual_curve_20260912/previews/eye0_scale075.jpg)
- 50% error sheet: [`eye0_scale050_diff_x8.jpg`](../out/native_scale_residual_curve_20260912/previews/eye0_scale050_diff_x8.jpg)
- Native source study summary: [`summary.json`](../out/native_teacher_resolution_study_20260912/summary.json)

## Decision

**Pursue as an offline architecture experiment, not as a runtime promotion.**

This is the first speed route that has both a credible external precedent and
a local native-teacher demonstration. It is worth spending a small, bounded
training/evaluation tranche on a learned residual resolve at 75% and 50%,
provided we keep the current native teacher, exact guides, full-eye temporal
captures, and existing known-good runtime path unchanged.

Do not collect a large new dataset yet. First use the retained full-eye frames
to train a minimal 75%/50% two-branch prototype and test it on frozen,
sequence-disjoint scenes. If the learned resolve cannot move 75% substantially
toward the existing full-resolution teacher, more raw data is likely to be
more valuable than further quantizing the full recovered network.

This study does not establish temporal stability, stereo consistency, VR frame
budget, headset quality, or live deployment acceptance.
