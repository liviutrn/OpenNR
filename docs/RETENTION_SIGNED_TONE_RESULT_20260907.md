# Signed tone diagnosis: user highlight/shadow feedback supported

Read-only diagnostic session16217 completed successfully. Source E:/OpenNR_Training/retention_tone_diagnostic_20260907/result.json;414 training eye images, frame32 after causal history. Signed code-value luma error is prediction minus teacher; positive means too bright, negative too dim. Pixel-weighted region means below. These are not physical luminance or held-out metrics, and no skin segmentation is used.

| Cohort | Teacher darkest quintile | Teacher brightest quintile | Teacher brightens input >0.02 | Teacher darkens input >0.02 |
|---|---:|---:|---:|---:|
| Prior | +0.00393320 | -0.00696071 | -0.02198630 | +0.02521873 |
| High-effect | +0.00694104 | -0.00461619 | -0.01326433 | +0.01911733 |
| Latest | +0.00480975 | -0.00245076 | -0.01273207 | +0.02687976 |

The per-image sign is also widespread: teacher-brightening regions are underbright in358/368 prior,32/34 high-effect,11/12 latest images. Teacher-darkening regions are overbright in310/343 eligible prior,31/34 high-effect,11/12 latest images. Twenty-five prior images have no qualifying darkening pixels and are excluded from that denominator. Quintile ties are included, so counts need not equal exactly20%. Region masks overlap and must not be summed as disjoint error contributions.

This supports the user's observation of compressed tonal change. It does not mean every bright/dark area has the same error or that skin color is solved. Teacher-effect-defined masks are diagnostic labels, not inference inputs. New correction models must predict from available input/model/context only. Preserve signed RGB and per-image records for color analysis; global averages can cancel scene-specific biases.

Next implementation target: identity-initialized spatially varying tone/color correction trained on existing training splits, compared against a matched continuation/control, with original and retained baselines, all-cohort validation, temporal metrics and explicit highlight/shadow/color visual inspection. No global brightness fix, teacher leakage, automatic deployment, or claim of target0.011. Existing candidates and frozen tests unchanged.
