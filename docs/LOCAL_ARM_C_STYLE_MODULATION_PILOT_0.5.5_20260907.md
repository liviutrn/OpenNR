# Local Arm-C style-modulation pilot — OpenNR 0.5.5 — 2026-09-07

Status: pre-registered; zero-cloud-cost local pilot on the RTX 5070 Ti.

## Question and gate

Does a zero-initialized global context-style modulation path let the selected
Arm-C capacity branch adapt its residual to lighting/material context without
giving back the prior-cohort or new-cohort MAE gain?

Keep the pilot only if its independently evaluated best checkpoint improves
both the prior and new validation cohorts relative to the exact seed-337 Arm-C
reference. A one-cohort gain, a regression on either cohort, nonfinite values,
or an OOM rejects the recipe. The frozen test split remains untouched.

## Fixed recipe

| Field | Value |
| --- | --- |
| Parent | seed-337 Arm C `best_mae.pt` |
| Capacity | width `192`, blocks `6`, extra width `96`, extra blocks `3` |
| New path | `--style-modulation`; zero-initialized global context FiLM at capacity-branch entrance/exit |
| Initialization | `--fresh-capacity-init`; inherited base/temporal parent function and fresh capacity branches as in Arm C |
| Data | prior strict cache + new clean temporal cache (`0.35`) + spatial-only all-crop cache (`0.25`) |
| Loss | Arm-C recipe unchanged: feature `.05`, VGG `.10`, tone `.10`, effect power `.10`/`4`, identity `.75`/`.05`, micro identity `1.0`/`.01`, delta `.12` |
| Rates | base `1e-7`, temporal `1e-6`, capacity `2.5e-6` |
| Steps / eval | `400`, validation every `100` |
| Batch / seed | batch `1` for local VRAM; seed `341` |
| Test | not read |

The style-modulation weights are initialized to zero by the model, so this
probe adds a controlled context-dependent degree of freedom while preserving
the Arm-C branch at initialization. It is a hypothesis test, not evidence
that renderer-derived semantics are present in the current input contract.

## Expected output

Artifacts will be retained under
`E:\OpenNR_Training\local_style_modulation_from_arm_C_0.5.5_20260907`.
Record trainer status, peak VRAM, independent prior/new validation, effect
bands, and any visual sheet. No production or MO2 installation is in scope.

## Result — 2026-09-07 UTC

The 400-step pilot completed locally in `442.13` seconds without OOM or
nonfinite values. The trainer selected step `300`, checkpoint SHA-256
`f849fcfa8dd0985f06dc59cc7c5d559631c9b5d68ae4d9fb6903a9e914112894`.

Independent local validation of that checkpoint measured:

| Candidate | Prior validation MAE | New validation MAE |
| --- | ---: | ---: |
| Seed-337 Arm C reference | `0.019690728` | `0.019369167` |
| Style-modulation pilot | `0.019704359` | `0.019328705` |

The pilot improves the new cohort by `0.000040463` but regresses the prior
cohort by `0.000013631`. It therefore fails the two-cohort gate and is
rejected as a general recipe. It is retained as evidence that context-style
modulation may help the new domain, but the current input contract is not
enough to make that gain robust. The frozen test split was not read.
