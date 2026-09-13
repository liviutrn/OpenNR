# Retained-model spatial-frequency error diagnostic

Motivation: bounded learning-rate continuation did not improve the retained candidate; paired history-reset effects were tiny. Quantify whether remaining error energy is predominantly broad spatial appearance or finer detail before selecting another training mechanism.

Read-only inference from verified seed352 step400. Frame32 after causal history1..32 for every207 training sequence, both eyes (414 images). No validation/test access or optimization. Orthonormal2D FFT of prediction-minus-teacher and teacher-minus-input; radial frequency bands below1/32,1/32..1/8,1/8..1/4,and above1/4 cycles/pixel. Sum error energy per band and compare against identity prediction. Check Parseval energy conservation within1e-5. Unwindowed transforms conserve the whole error but can include periodic-edge artifacts. Energy fractions refer to MSE, not additive MAE or semantic/perceptual quality. Frame32 is a fixed snapshot, not all-frame coverage.

Script tools/diagnose_retention_spectrum.py, derived from the existing spectral audit concept but using the current strict temporal loader/model. Output E:/OpenNR_Training/retention_spectral_diagnostic_20260907; live session71966. Preserve completed experiments and do not restart on stale status.

## Completed result and user visual priority

Session71966 exited zero. All414 frame32 eye images processed; Parseval relative error below1.4e-7. Below1/32 cycles/pixel accounts for84.02% of prior,75.45% of high-effect,73.88% of latest squared-error energy. This is broad spatial error dominance, not proof of a specific lighting/material cause or equivalent MAE percentages. Model error energy is lower than identity in every band, but remaining broad appearance error is substantial.

User explicitly reports insufficient highlight brightness, insufficient shadow depth, and less realistic color/skin texture. This is the next visual priority. Implemented tone_error_metrics.py and diagnose_retention_tone.py to measure signed code-value luma/RGB error on per-image teacher dark/bright quintiles and teacher-brightens/darkens masks (effect threshold0.02). Ties included; no claim of physical luminance or skin segmentation. Synthetic sign/mask/identity checks pass. Run on same causal frame32 training coverage, no weights or frozen tests changed. These measurements should precede a spatially varying tone/color experiment rather than another blind scaling trial.
