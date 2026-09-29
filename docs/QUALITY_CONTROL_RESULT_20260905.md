# Completed scale4 quality continuation — 2026-09-05

The higher-resolution v2 quality control completed20,000 additional steps in17.84 minutes. Native-eye and separately evaluated LPIPS results improve over the prior fast delivery, but teacher-equivalent appearance remains unachieved. The matched context-attention experiment is the next active run; this document does not close the project goal.

All88 native validation eyes and all352 unchanged512-pixel validation patches were evaluated. AlexNet LPIPS v0.1 is evaluated on displayed clamped RGB, without patch resizing, and is not used in the SqueezeNet training objective. No new test rows were evaluated. Changed pixels are fixed by teacher-input mean RGB difference>0.05. Teacher-changed regions occupy23.92% of the native pixels.

| Candidate | Additional step | Native RGB MAE down | Changed-region MAE down | Patch LPIPS down |
|---|---:|---:|---:|---:|
| Previous fast delivery | 5,000 | 0.023873 | 0.035828 | 0.096115 |
| best_mae | 8,000 | 0.022968 | 0.034237 | 0.076899 |
| best_feature | 18,000 | 0.022253 | 0.035114 | 0.074342 |

Keep the best-MAE and best-feature weights separately. "Best MAE" means selection on cached validation patches, not all native pixels: the earlier checkpoint has better patch MAE and native changed-region MAE, while the later checkpoint has better whole-eye MAE and LPIPS. This distinction is why native evaluation was added. Visual review still finds facial shadow, skin and hair differences. Do not silently use the last checkpoint, claim that feature loss proves appearance, or label either candidate as the completed replacement.

Portable inference-only candidates are `out/quality_phase_20260905/OpenNR_Quality_v2_best_mae.pt` and `OpenNR_Quality_v2_best_feature.pt`. Original optimizer-bearing checkpoints remain in `detail_continuation`. `quality_control_delivery.json` records hashes. The previous compiled fast engine has not been replaced; these new scale4 weights have not been benchmarked as newly compiled TensorRT engines.

Open `out/quality_phase_20260905/quality_control_gallery.html` for the comparisons. Columns are input, previous fast delivery, new best-MAE, new best-feature, teacher. Full-resolution metrics are in `native_detail_best_mae/result.json` and `native_detail_best_feature/result.json`; LPIPS is in `lpips_detail_final/result.json`.

The effect-strength diagnostic does not support a simple intensity boost: the model's residual RMS is about94% of the teacher's on validation, but its direction/structure agreement is weaker than on training. Further work is therefore focused on contextual reconstruction and generalization. See `docs/QUALITY_PHASE_20260905.md` for the experiment record, research sources and active-run references.
