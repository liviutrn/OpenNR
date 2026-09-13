# OpenNR-VR model iteration update — v65 full-resolution auxiliary oversampling — 2026-09-06

## Outcome

The v65 probe tested whether the existing full-resolution master stream was
being under-sampled by the current mixed spatial sampler. It initialized from
the all-data v61 checkpoint and increased the full-resolution auxiliary stream
to 50 percent of training steps for a bounded 500-step continuation. The
strict combined validation split selected step 200; later checkpoints
regressed, so the final step was not selected.

This is a small positive result, not a teacher match. The best v65 checkpoint
is retained as a minor all-data research candidate, but it is not installed
into SkyrimVR and does not close the requested MAE `0.011` target.

## Exact experiment

- Parent checkpoint:
  `E:\OpenNR_Training\fresh_combined_adapted_base_v61_all_nontest_0.5.5_20260906\last.pt`
- Parent SHA-256:
  `2fa1c311a88ffecf4c3d7bab51b4ac225cdb32a4a052607c335268b755816067`
- Output:
  `E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906`
- Selected checkpoint:
  `E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt`
- Selected checkpoint SHA-256:
  `5672252b438669169d8b2fed9ffb16f20768270f01d79dc924f32b9318fbc3e3`
- Strict training cache:
  `E:\OpenNR_RawCropCache_StrictCombinedFresh_0.5.5_20260906`
- Spatial source used by the probe:
  `E:\OpenNR_FullResMasterSpatialAux_0.5.5_20260906`
- Training steps: 500; selected step: 200
- Window/burn-in/batch: 8 / 2 / 2
- Full-resolution spatial probability: 0.50
- The strict test rows were not loaded for training or validation selection.

The full-resolution source contains 1,024 training patches. v61 included that
source among its spatial caches, but its proportional multi-source sampler and
`spatial_prob=0.15` gave it only a small fraction of total updates. v65
isolated the effect of increasing that exposure without changing the model
capacity or the native RGB/depth/motion-vector contract.

## Validation history

| Step | Validation MAE | First-frame feature distance | Temporal-delta MAE |
| ---: | ---: | ---: | ---: |
| 0 | 0.018200018 | 0.089216219 | 0.009243512 |
| 100 | 0.018174894 | 0.089208438 | 0.009243330 |
| 200 | **0.018163776** | 0.089245100 | 0.009243549 |
| 300 | 0.018166093 | 0.089332364 | 0.009243176 |
| 400 | 0.018186274 | 0.089426779 | 0.009243189 |
| 500 | 0.018201767 | 0.089528510 | 0.009242981 |

The improvement from the probe's own step-0 state to step 200 is only
`0.000036242` MAE, approximately 0.20 percent relative. The curve peaks
early and then reverses, which is consistent with a modest regularization or
sampling benefit rather than a missing-capacity solution.

## Frozen transfer measurements

The v65 step-200 checkpoint was selected using validation only and then
measured once on the frozen test splits:

| Cohort | v61 baseline | v65 full-res oversampling | Difference |
| --- | ---: | ---: | ---: |
| Fresh, 26 sequences / 3,328 frames | 0.014976055833 | **0.014935002232** | -0.000041053601 |
| Historical, 15 sequences / 1,920 frames | 0.025628328013 | 0.025628855343 | +0.000000527330 |
| Combined, 41 sequences / 5,248 frames | 0.018873231286 | **0.018847387516** | -0.000025843770 |

The combined change is a 0.137 percent relative improvement. The historical
cohort is effectively unchanged, so the result is retained but does not justify
promoting v65 as a qualitatively different model. The direct evidence is in:

- `D:\.CODEX_Projects\OpenNR-VR\out\v65_fullres_aux_combined_test_best_mae_0.5.5_20260906\result.json`
- `D:\.CODEX_Projects\OpenNR-VR\out\v65_fullres_aux_fresh_test_best_mae_0.5.5_20260906\result.json`
- `D:\.CODEX_Projects\OpenNR-VR\out\v65_fullres_aux_historical_test_best_mae_0.5.5_20260906\result.json`
- `D:\.CODEX_Projects\OpenNR-VR\out\fresh_test_v61_v65_fullres_gallery_0.5.5_20260906\gallery.json`

The visual gallery shows v61 and v65 are nearly indistinguishable. Both retain
the character and scene structure, but both remain less warm/dark in local
facial tone and weaker in fine material and shadow detail than the Feature 18
teacher. No obvious new flicker or invented geometry was introduced.

## Corpus accounting

The strict raw root contains 213 sequence directories. The 77 records before
the fresh-session time boundary are not an unexamined data opportunity:

- 73 are represented in the accepted historical strict cache;
- the remaining four are the known eye-specific all-zero-motion cases:
  `seq-1788671404795-48`, `seq-1788671414977-49`,
  `seq-1788671421797-50`, and `seq-1788671425120-51`;
- the five fresh content exclusions remain spatial-only;
- the one wrong-frame-count tail and four metadata rejects remain preserved.

The v61 run already consumed the clean combined strict source, the merged
spatial sources, the full-resolution master auxiliary source, and the
spatial-only quarantine under their explicit role boundaries. No raw data was
deleted or silently admitted to temporal loss for this probe.

## Decision and next gate

Full-resolution oversampling is a useful low-cost refinement, but it is not the
main path to `0.011`. The next high-value action remains a new independent game
capture cohort with varied scenes, lighting, materials, camera motion, and
teacher controls. Preserve exact 64-frame bursts, initial `[true, true]` reset,
contiguous frame/host/sample IDs, both eyes, native Feature 18 motion vectors,
and depth. Keep the new cohort's test sequences untouched until model selection
is complete.

The current public NVIDIA description says DLSS 5 is a one-step pixel-space
generative model conditioned on the current rendered frame, engine motion
vectors, carried temporal state, and artistic-direction values, with
renderer-derived scene attributes used for consistency supervision. Our cache
still lacks verified albedo, normals, illumination, material/object/light
semantics, semantic masks, and the exact carried teacher history. Those are
the most valuable target/conditioning additions if the Skyrim renderer path
can expose them with auditable shape, coordinate-space, range, reset, and hash
metadata. A larger GPU should follow that data/representation work, not
replace it.

## Scope boundary

These results are offline crop-space spatial/streaming evidence. They do not
prove live Feature 18 replacement, temporal history equivalence, stereo
comfort, headset image quality, VR frame-time, or runtime activation.

