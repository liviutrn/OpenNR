# Fresh strict-capture audit and distilled-model iteration — 2026-09-06

## Outcome

The fresh strict capture is now organized into separate temporal-safe and
spatial-only sources. The latest selected research candidate is v65, a
full-resolution auxiliary-oversampling continuation from the all-data v61
checkpoint. v61 remains the parent baseline and v60 remains the
historical-leaning fallback; v56 is the best historical-test anchor in the
post-gate/power-loss line, and v62 is retained as a fresh-cohort specialist
only because its stronger micro-identity term regressed the historical cohort.

The selected all-data candidate is visually stable in the sampled A/B sheets
and reduces both fresh- and historical-test error below their identity
baselines. It is still a crop-space offline result, not a live SkyrimVR/runtime
acceptance result, and it does not meet the requested MAE `0.011` target on the
combined corpus: v65 is `0.0188473875` on the direct combined-test pass, or
71.3% above target. The improvement over v61 is only `0.0000258438` MAE
(0.137% relative), so this is a minor refinement rather than a new quality
regime.

The v46-v65 recipe choices were made after inspecting earlier frozen-test
results, with the v49-v65 changes guided by effect-band and cross-cohort
diagnostics. The test rows were never loaded into training, but these later
candidates are therefore test-informed diagnostics rather than unbiased
holdout-selected models. Their untouched test measurements are kept for
transfer evidence; a new independent capture is needed for a clean future
selection gate.

A lower-learning-rate continuation, v48, was started from v47 and stopped at
the first validation gate because it did not improve whole-frame MAE. Its
partial run is retained as a negative control and was not evaluated on the
frozen test sets.

The v63 style-modulation probe and v64 preserved-parent extra-capacity probe
did not produce meaningful validation gains. The v65 full-resolution
oversampling probe was the only later branch to earn a frozen-test measurement:
its best validation checkpoint was step 200, and it improved the combined test
slightly while leaving the historical cohort effectively unchanged. Full
details and hashes are recorded in
`docs/MODEL_ITERATION_UPDATE_V65_FULLRES_OVERSAMPLE_20260906.md`.

## Data scope and quality decision

The source root was audited at:

`E:\OpenNR_Captures_StrictTemporal_0.5.5_20260906`

The raw validator reported 213 sequence directories. A stricter selection
layer then required all of the following:

- exactly 64 complete frames;
- the first frame's strict history reset `[true, true]`;
- no mid-clip reset;
- a sequence inside the new-session time window;
- metadata accepted by the temporal audit.

The metadata audit marked 209 of 213 sequences ready. Four were rejected:

- `seq-1788703463197-12`: mid-clip reset and host gap;
- `seq-1788703529242-14`: one-frame incomplete sequence;
- `seq-1788705040269-36`: mid-clip reset and host gap;
- `seq-1788705174934-53`: mid-clip reset and host gap.

The exact-frame-count correction also removed the preserved older 40-frame tail
`seq-1788671650398-78`, which the lower-level metadata validator had otherwise
classified as ready. The raw sequence and all rejected evidence remain
preserved; they were not silently deleted.

The authoritative audit artifacts are:

- `D:\.CODEX_Projects\OpenNR-VR\out\temporal_audit_strict_new_20260906.json`
- `D:\.CODEX_Projects\OpenNR-VR\out\strict_temporal_candidate_manifest_fresh_clean_0.5.5_20260906.json`
- `D:\.CODEX_Projects\OpenNR-VR\out\fresh_raw_crop_content_audit_0.5.5_20260906.json`

### Content audit

The exact fresh metadata-qualified set contained 131 sequences, 8,384 frames,
and 16,768 eye rows. Raw motion content was then checked rather than assuming
that structurally valid metadata implied valid temporal supervision:

- 186 eye rows contained all-zero motion payloads;
- 32 eye rows contained invalid motion pixels/components;
- the invalid-motion scan identified 2,197,901 invalid motion pixels across
  those rows;
- five sequences were quarantined from recurrent temporal training because the
  zero-motion evidence was accompanied by a measurable teacher effect or the
  invalid fraction was severe;
- isolated invalid motion was retained only where the cache's existing mask
  contract can safely exclude the invalid components.

The five temporal exclusions are:

`seq-1788703275267-1`, `seq-1788703290536-2`,
`seq-1788703370562-6`, `seq-1788703755270-41`,
`seq-1788704612911-24`.

The content audit showed why they are unsafe for recurrent loss: for example,
the first two contain long all-zero-motion intervals while the paired RGB and
teacher change. Those sequences remain useful as provenance and spatial-only
data, but their motion must not be taught as if it were valid.

## Organized caches and split boundary

The clean fresh temporal cache is:

`G:\OpenNR_ColdStorage\OpenNR_RawCropCache_FreshTemporalClean_0.5.5_20260906`

This historical derived cache was moved to G: cold storage after full
verification. It remains provenance/recovery data, not a new capture. The
active self-contained combined cache remains on E:.

It contains 126 sequences, 8,064 frames, and 16,128 eye rows. Its sequence split
is 80 train / 20 validation / 26 test, with row identity SHA-256:

`29d862c1387de4b7abcf93d69481f5ada1d0155f1cdf80feb6732f3c26612170`

The five quarantined content cases that were not admitted to temporal training
are retained as spatial-only auxiliary sequences. That cache is:

`E:\OpenNR_SpatialAux_ContentExcluded_0.5.5_20260906`

It contains 5 sequences, 320 frames, and 640 eye rows, and is explicitly marked
`training_role=spatial_only_auxiliary` and
`temporal_training_allowed=false`.

The combined strict cache is:

`E:\OpenNR_RawCropCache_StrictCombinedFresh_0.5.5_20260906`

It combines the historical 73 clean strict sequences with the 126 clean fresh
sequences: 199 sequences, 12,736 frames, and 25,472 eye rows. The preserved
sequence split is 126 train / 32 validation / 41 test sequences, consisting of
46+80 train, 12+20 validation, and 15+26 test from the two source cohorts.
Its row identity SHA-256 is:

`4de6ee08b09f76a8e4d65c632b87aded3958e72c4a71f96272237ad84059c1b1`

The fresh clean cache, combined cache, and five-sequence spatial-only cache all
passed `tools\test_raw_crop_cache.py` under the pinned training environment.
The old historical test rows and new fresh test rows were never loaded into
training. The all-source spatial cache and the quarantined spatial auxiliary
cache were supplied to the spatial branch only, so the available audited data
was used without allowing invalid motion to contaminate temporal supervision.
The v46-v50 recipe choices
did inspect frozen-test diagnostics, so those candidates are marked
test-informed even though the test arrays remained training-excluded.

## Controlled model iterations

All fresh-data candidates used the same combined strict cache and the same
spatial sources. The lineage was:

| Candidate | Controlled change | Combined validation MAE | Fresh clean test MAE | Historical strict test MAE |
| --- | --- | ---: | ---: | ---: |
| v45 | Extra capacity probe; identity term off | 0.020164503 | 0.020235778 | 0.025794559 |
| v46 | Add identity-preservation loss, weight 0.10 | 0.019873639 | 0.019726244 | 0.025671088 |
| v47 | Same as v46, identity weight 0.20 | **0.019562422** | 0.019128518 | **0.025603099** |
| v48 | Lower-LR continuation from v47; stopped at step 250 | 0.019563216 | Not evaluated | Not evaluated |
| v49 | Selective identity weight 0.50, threshold 0.025 | **0.019337622** | **0.018471095** | 0.025778990 |
| v50 | Balanced selective identity weight 0.35, threshold 0.025 | 0.019378305 | 0.018699686 | 0.025667569 |
| v51 | Fixed fit over all non-test data from v49; lower LR | Not applicable | **0.017972419** | 0.025734033 |
| v52 | Zero-initialized capacity residual gates; identity 0.75 / 0.05 | Not applicable | 0.017342570 | 0.025894382 |
| v53 | Add zero-initialized final correction gate on top of v52 | Not applicable | 0.016865149 | 0.025903303 |
| v54 | Width 192/8 + extra 96/4 feasibility probe; interrupted after step 1 | Not applicable | Not comparable | Not comparable |
| v55 | Signed effect power loss, weight 0.05, power 3 | Not applicable | 0.016605387 | 0.025436262 |
| v56 | Stronger signed effect power loss, weight 0.10, power 3 | Not applicable | 0.016434519 | **0.025174186** |
| v57 | Add micro-identity loss, weight 1.0, threshold 0.01 | Not applicable | 0.015878748 | 0.025458129 |
| v58 | Stronger micro-identity loss, weight 2.0, threshold 0.01 | Not applicable | 0.015375616 | 0.025740261 |
| v59 | Rebalance micro-identity to 1.0 from v58 | Not applicable | 0.015178698 | 0.025609950 |
| v60 | Power-4 effect loss from v59; weight 0.10 | Not applicable | 0.015069618 | 0.025566168 |
| v61 | Modestly increase base/temporal learning rates from v60 | Not applicable | **0.014976056** | 0.025628328 |
| v62 | Micro-identity 2.0 from v61; fresh-specialist ablation | Not applicable | **0.014883446** | 0.026214667 |
| v63 | Zero-initialized global style modulation from v61 | 0.018181246 at best validation checkpoint | 0.014922954 | 0.025679153 |
| v64 | Zero-output extra capacity branch with inherited parent frozen | No meaningful validation gain; rejected before test | Not evaluated | Not evaluated |
| v65 | Oversample the 1,024-patch full-resolution master auxiliary source | **0.018163776** at step 200 | **0.014935002** | 0.025628855 |

The fresh test identity baseline is `0.018592362`, and the historical identity
baseline is `0.040083710`. v65 reaches `0.014935002` fresh MAE (19.67% below
fresh identity) and `0.025628855` historical MAE (36.06% below historical
identity). Its fresh-test MAE is still 1.358 times the requested `0.011`
target, while the frame-weighted two-cohort result is 1.713 times target, so
the target remains open.

The post-v51 changes were all fixed-budget, all-non-test fits initialized from
the preceding candidate. v52's residual gates and v53's final gate produced
successive fresh gains. v55/v56's signed effect power loss improved both
cohorts, with v56 remaining the historical-test anchor. v57/v58/v59 then
reduced fresh error further while trading against historical transfer. Power 4
in v60 slightly improved both cohorts relative to v59. The higher base/temporal
rates in v61 improved fresh transfer and the weighted score, but v60 remains
slightly better on the historical temporal-delta metric. v62's stronger
micro-identity term produced the lowest fresh score yet, but its historical
regression makes it a specialist rather than an all-data candidate.

Temporal-delta MAE for v61 is `0.009534396` on the fresh clean test and
`0.010851585` on the historical strict test; v60 is `0.009593164` and
`0.010828933`, respectively. The frame-weighted two-cohort test score is now:

| Candidate | Fresh test | Historical test | Frame-weighted two-cohort MAE |
| --- | ---: | ---: | ---: |
| v47 | 0.019128518 | 0.025603099 | 0.021497267 |
| v49 | **0.018471095** | 0.025778990 | **0.021144715** |
| v50 | 0.018699686 | **0.025667569** | 0.021248911 |
| v51 | 0.017972419 | 0.025734033 | 0.020812034 |
| v52 | 0.017342570 | 0.025894382 | 0.020471282 |
| v53 | 0.016865149 | 0.025903303 | 0.020171791 |
| v55 | 0.016605387 | 0.025436262 | 0.019836195 |
| v56 | 0.016434519 | **0.025174186** | 0.019631958 |
| v57 | 0.015878748 | 0.025458129 | 0.019383400 |
| v58 | 0.015375616 | 0.025740261 | 0.019167559 |
| v59 | 0.015178698 | 0.025609950 | 0.018995010 |
| v60 | 0.015069618 | 0.025566168 | 0.018909819 |
| v61 | **0.014976056** | 0.025628328 | **0.018873229** |
| v62 | **0.014883446** | 0.026214667 | 0.019029015 |

This makes v61 the current all-usable-data/fresh-data-weighted candidate, v62
the best fresh-cohort specialist, v60 the historical-leaning fallback, and v56
the best historical-test anchor in this iteration line. None of v51-v62 has an
independent validation score because each fixed fit intentionally consumed the
validation split; their test scores are final-fit transfer measurements, not
clean selection scores.

The v54 wide-capacity feasibility branch is explicitly rejected. Its
`192x8 + 96x4` capacity graph took approximately 221.45 seconds for step 1,
reached an allocator peak of approximately 17.08 GiB on the available 16 GiB
class GPU, and was interrupted before it could establish a useful training
trajectory. Its shape-expanded initialization also skipped incompatible
learned capacity tensors, so its step-0 score is not a reproduction of v53 and
is not included in the ranking. Its preserved status is
`E:\OpenNR_Training\fresh_combined_wide_final_gate_v54_all_nontest_0.5.5_20260906\status.json`.

### Selected checkpoint

The current all-usable-data/fresh-data-weighted offline checkpoint is:

`E:\OpenNR_Training\fresh_combined_adapted_base_v61_all_nontest_0.5.5_20260906\last.pt`

Checkpoint SHA-256:

`2fa1c311a88ffecf4c3d7bab51b4ac225cdb32a4a052607c335268b755816067`

The v61 run completed at step 1000 in 408.40 seconds with no non-finite loss
or gradient. It is a fixed final fit initialized from v60, uses 316 training
streams (158 non-test sequences, both eyes), three spatial sources, and
explicitly reports `fit_all_nontest=true`, `test_used=false`, and no validation
selection. Its practical 2,936,659-parameter recipe is width `128`, six
capacity blocks, an extra `64x3` capacity branch, zero-initialized residual and
final gates at scale `0.8`, an 8-frame window, two-frame burn-in, batch 2,
spatial probability `0.15`, signed effect power loss weight `0.10` with power
`4`, identity weight `0.75` at threshold `0.05`, micro-identity weight `1.0`
at threshold `0.01`, and learning rates `1e-7 / 1e-6 / 2.5e-6` for base /
temporal / capacity groups.

The historical-leaning v60 fallback is
`E:\OpenNR_Training\fresh_combined_power4_v60_all_nontest_0.5.5_20260906\last.pt`
with SHA-256
`5d20b04e9a92c3ef8e712c39dcb34aa7776ebd5bafafd8afcfe05b71cf341401`.
The fresh-specialist v62 is
`E:\OpenNR_Training\fresh_combined_micro2_v62_all_nontest_0.5.5_20260906\last.pt`
with SHA-256
`84df990fa045d1f7911877b37f56a6afc833224e28b0f9f425650b8a2a44dab8`.
The post-gate historical-test anchor v56 is
`E:\OpenNR_Training\fresh_combined_power_effect_strong_v56_all_nontest_0.5.5_20260906\last.pt`
with SHA-256
`6b4799e2b982fbedd590282b044481546817910c961881e668f6df8832ea1ab7`.

The earlier v49 validation-selected/fresh-cohort fallback is
`E:\OpenNR_Training\fresh_combined_identity_selective_v49_probe_0.5.5_20260906\best_mae.pt`
with SHA-256
`d22d7caa53988082b6af2b3b2e7ecae3d61c2dcdca2fb24366aa424c711babb3`.
The v49 run completed at step 750 in 442.95 seconds with no non-finite loss or
gradient. The v50 balanced fallback is
`E:\OpenNR_Training\fresh_combined_identity_balanced_v50_probe_0.5.5_20260906\best_mae.pt`
with SHA-256
`82e193bb8ec3114c2492a9614754062aabc031787c67eb1078788b89d48f4181`.

## Frozen evaluation and effect-band artifacts

The v45-v62 parity evaluations are saved separately so the ranking can be
reproduced without relying on console output:

- v45 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v45_fresh_test_best_mae_0.5.5_20260906\result.json`
- v45 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v45_historical_test_best_mae_0.5.5_20260906\result.json`
- v46 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v46_fresh_test_best_mae_0.5.5_20260906\result.json`
- v46 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v46_historical_test_best_mae_0.5.5_20260906\result.json`
- v47 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v47_fresh_test_best_mae_0.5.5_20260906\result.json`
- v47 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v47_historical_test_best_mae_0.5.5_20260906\result.json`
- v49 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v49_fresh_test_best_mae_0.5.5_20260906\result.json`
- v49 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v49_historical_test_best_mae_0.5.5_20260906\result.json`
- v50 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v50_fresh_test_best_mae_0.5.5_20260906\result.json`
- v50 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v50_historical_test_best_mae_0.5.5_20260906\result.json`
- v51 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v51_fresh_test_last_0.5.5_20260906\result.json`
- v51 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v51_historical_test_last_0.5.5_20260906\result.json`
- v52 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v52_fresh_test_last_0.5.5_20260906\result.json`
- v52 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v52_historical_test_last_0.5.5_20260906\result.json`
- v53 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v53_fresh_test_last_0.5.5_20260906\result.json`
- v53 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v53_historical_test_last_0.5.5_20260906\result.json`
- v55 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v55_fresh_test_last_0.5.5_20260906\result.json`
- v55 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v55_historical_test_last_0.5.5_20260906\result.json`
- v56 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v56_fresh_test_last_0.5.5_20260906\result.json`
- v56 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v56_historical_test_last_0.5.5_20260906\result.json`
- v57 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v57_fresh_test_last_0.5.5_20260906\result.json`
- v57 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v57_historical_test_last_0.5.5_20260906\result.json`
- v58 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v58_fresh_test_last_0.5.5_20260906\result.json`
- v58 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v58_historical_test_last_0.5.5_20260906\result.json`
- v59 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v59_fresh_test_last_0.5.5_20260906\result.json`
- v59 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v59_historical_test_last_0.5.5_20260906\result.json`
- v60 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v60_fresh_test_last_0.5.5_20260906\result.json`
- v60 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v60_historical_test_last_0.5.5_20260906\result.json`
- v61 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v61_fresh_test_last_0.5.5_20260906\result.json`
- v61 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v61_historical_test_last_0.5.5_20260906\result.json`
- v62 fresh test: `D:\.CODEX_Projects\OpenNR-VR\out\v62_fresh_test_last_0.5.5_20260906\result.json`
- v62 historical test: `D:\.CODEX_Projects\OpenNR-VR\out\v62_historical_test_last_0.5.5_20260906\result.json`
- v61 direct combined test: `D:\.CODEX_Projects\OpenNR-VR\out\v61_combined_test_last_0.5.5_20260906\result.json`

The effect-band evaluator is a read-only diagnostic at
`D:\.CODEX_Projects\OpenNR-VR\out\v47_fresh_test_effect_bins_0.5.5_20260906`,
`D:\.CODEX_Projects\OpenNR-VR\out\v47_historical_test_effect_bins_0.5.5_20260906`,
`D:\.CODEX_Projects\OpenNR-VR\out\v49_fresh_test_effect_bins_0.5.5_20260906`,
`D:\.CODEX_Projects\OpenNR-VR\out\v49_historical_test_effect_bins_0.5.5_20260906`,
`D:\.CODEX_Projects\OpenNR-VR\out\v51_fresh_test_effect_bins_0.5.5_20260906`,
`D:\.CODEX_Projects\OpenNR-VR\out\v51_historical_test_effect_bins_0.5.5_20260906`,
and `D:\.CODEX_Projects\OpenNR-VR\out\v47_combined_validation_effect_bins_0.5.5_20260906`.
It confirms that the `0.0-0.025` teacher-effect range is the dominant
overcorrection region, while `>=0.025` is where the student earns most of its
teacher-match gain.

The latest effect-band artifacts are:

- v59 combined test: `D:\.CODEX_Projects\OpenNR-VR\out\v59_effect_bins_test_0.5.5_20260906\result.json`
- v60 combined test: `D:\.CODEX_Projects\OpenNR-VR\out\v60_effect_bins_test_0.5.5_20260906\result.json`
- v61 combined test: `D:\.CODEX_Projects\OpenNR-VR\out\v61_effect_bins_test_0.5.5_20260906\result.json`
- v62 was not promoted to an effect-band run because its historical-test MAE
  already rejected it as an all-data candidate.

The v61 combined test band readout is:

| Teacher-input effect band | Combined pixel share | v61 student MAE | Identity MAE | v61 effect MAE |
| --- | ---: | ---: | ---: | ---: |
| `0.0-0.01` | 36.25% | 0.006630 | 0.004883 | 0.006020 |
| `0.01-0.025` | 30.22% | 0.014824 | 0.016652 | 0.013693 |
| `0.025-0.05` | 19.45% | 0.024937 | 0.035626 | 0.022681 |
| `0.05-0.1` | 9.90% | 0.043178 | 0.069262 | 0.040548 |
| `>0.1` | 4.17% | 0.068630 | 0.140559 | 0.078225 |

The low-effect band remains the only band where v61 is worse than simply
passing the input through; the stronger-effect bands are substantially better
than identity but still carry enough absolute error to keep whole-frame MAE
well above `0.011`. v60 and v61 therefore represent a small recipe tradeoff,
not a solved teacher match.

For comparison, the earlier v51 band readout makes the same error
concentration explicit:

| Teacher-input effect band | Fresh pixel share | Fresh student vs identity MAE | Historical pixel share | Historical student vs identity MAE |
| --- | ---: | ---: | ---: | ---: |
| `0.0-0.01` | 44.51% | 0.009620 vs 0.004757 | 21.94% | 0.010068 vs 0.005324 |
| `0.01-0.025` | 31.65% | 0.019200 vs 0.016403 | 27.75% | 0.018272 vs 0.017143 |
| `0.025-0.05` | 17.02% | 0.025975 vs 0.035246 | 23.66% | 0.026504 vs 0.036100 |
| `0.05-0.1` | 5.71% | 0.040239 vs 0.066409 | 17.18% | 0.040158 vs 0.070905 |
| `>0.1` | 1.12% | 0.080291 vs 0.133758 | 9.46% | 0.055822 vs 0.141950 |

Thus the gate and effect-loss line is correcting the larger teacher-directed
effects, including the historical cohort, but it still over-corrects much of
the low-effect background. The v61 table shows that this remains true after
the v52-v61 changes. That low-effect region is one remaining path toward
`0.011`; it should be addressed with a clean conditional residual/gating
experiment and new independent scenes, not by simply extending the same-corpus
cooldown.

Each evaluation is explicit-reset streaming crop-space inference. None is a
headset, compositor, stereo-delivery, route-selection, TensorRT-parity, or
frame-time acceptance result.

## Visual validation

The matched sequential sheets are preserved in:

- v45 versus v46, fresh validation:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_validation_v45_v46_gallery_0.5.5_20260906`
- v45 versus v46, fresh test:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_test_v45_v46_gallery_0.5.5_20260906`
- v46 versus v47, fresh validation:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_validation_v46_v47_gallery_0.5.5_20260906`
- v46 versus v47, fresh test:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_test_v46_v47_gallery_0.5.5_20260906`
- v47 versus v49, fresh validation:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_validation_v47_v49_gallery_0.5.5_20260906`
- v47 versus v49, fresh test:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_test_v47_v49_gallery_0.5.5_20260906`
- v49 versus v50, fresh validation:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_validation_v49_v50_gallery_0.5.5_20260906`
- v49 versus v50, fresh test:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_test_v49_v50_gallery_0.5.5_20260906`
- v49 versus v51, fresh validation:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_validation_v49_v51_gallery_0.5.5_20260906`
- v49 versus v51, fresh test:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_test_v49_v51_gallery_0.5.5_20260906`
- v51 versus v58, fresh test:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_test_v51_v58_gallery_0.5.5_20260906`
- v51 versus v59, fresh test:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_test_v51_v59_gallery_0.5.5_20260906`
- v59 versus v60, fresh test:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_test_v59_v60_gallery_0.5.5_20260906`
- v60 versus v61, fresh test:
  `D:\.CODEX_Projects\OpenNR-VR\out\fresh_test_v60_v61_gallery_0.5.5_20260906`
- v60 versus v61, historical test:
  `D:\.CODEX_Projects\OpenNR-VR\out\historical_test_v60_v61_gallery_0.5.5_20260906`

The sheets show Input, the prior student, the candidate, and the Feature 18
teacher at frames 1, 32, and 64 for both eyes. In the sampled dark and
low-effect scenes, the v51-v58-v61 line remains visually stable; v60 and v61
are difficult to distinguish without pixel inspection, with no obvious flicker,
invented structure, or washout. The historical v60-v61 sheets likewise show a
small change rather than a visible failure. In higher-effect scenes the
students retain the teacher-directed correction without obvious temporal drift.
The teacher still shows the persistent broader gap: warmer/redder local tone,
stronger facial shadow and contrast structure, and richer material detail. The
visual evidence supports v61 as the current all-non-test/fresh-data-weighted
offline candidate, not a claim of full teacher resemblance.

## Decision and next step

Promote v61 as the current all-usable-data/fresh-data-weighted offline research
candidate. Keep v62 as the fresh-cohort specialist, v60 as the
historical-leaning fallback, and v56 as the post-gate historical-test anchor.
Keep v51 and the earlier v45-v50 checkpoints for reproducible comparisons. Do
not install v61, v62, v60, or v56 into the active SkyrimVR/MO2 profile yet;
runtime acceptance remains a separate controlled gate.

The data result changes the priority of the next iteration. More identical
same-scene optimization is now demonstrably diminishing-return: v51-v61 moved
the weighted score from `0.020812034` to `0.018873229`, while v62 showed that a
stronger identity penalty can improve fresh scenes and simultaneously harm the
older cohort. The next high-value training change should be driven by more
independent strict captures that vary lighting, material, camera motion, and
temporal behavior while preserving exact Feature 18 guide binding, both-eye
pairing, and the initial `[true, true]` reset. The existing five spatial-only
quarantine sequences can continue to regularize appearance, but must remain out
of temporal loss.

If no new captures are available, another same-corpus cooldown is low value.
The v54 width expansion was infeasible on the available GPU, and v55-v62 only
shaped the existing error distribution; none approached the target on the
combined corpus. For a clean future selection gate, reserve a new capture
cohort before measuring candidate rankings. Reaching `0.011` will likely
require additional teacher coverage plus a materially better conditional
input/target representation, not only more capacity or longer training on this
corpus.

### Research-informed data requirement

The latest official NVIDIA DLSS 5 description says the runtime model is
conditioned on the current rendered frame, engine motion vectors, carried
temporal state, and artistic-direction values, with renderer-derived scene
attributes used for consistency supervision. NVIDIA's accompanying product
description specifically calls out surface albedo, detailed lighting, surface
normals, object/material/light semantics, Structure Intensity, Tone Intensity,
and semantic masking. The current OpenNR cache contract has RGB, depth, native
motion vectors, and context, but no verified albedo, normals, material/light
semantics, or teacher history tensor. This mismatch is the most credible
explanation for the persistent visual gap in local tone, facial shadow, and
material detail.

The next capture protocol should therefore preserve the current strict RGB/depth/
native-MV contract and add auditable renderer-derived conditionings if the game
path can expose them: albedo, normals, lighting or illumination features,
material/object masks, artistic controls, and the exact carried history state.
Each added tensor must be recorded with shape, coordinate space, sign/range,
reset behavior, and a per-sequence hash before it is allowed into training.
Optical flow remains unsuitable as a substitute for native motion vectors.

This direction is consistent with NVIDIA's September 2026 DLSS 5 research
release ([ADLR DLSS 5](https://research.nvidia.com/labs/adlr/DLSS5/)) and its
developer-facing explanation of renderer-grounded conditioning and controls
([3D-Guided Neural Rendering](https://www.nvidia.com/en-eu/geforce/news/dlss-5-3d-guided-neural-rendering/)).
The July 2026 NVIDIA compact-neural-network work also supports treating
optimization variance, loss choices, and input parameterization as separate
axes rather than assuming a larger single model will solve the gap
([Taming optimization variance](https://research.nvidia.com/labs/rtr/publication/bitterli2026taming/)).
The public NGX definitions still enumerate Feature 18 as reserved
([NVIDIA DLSS SDK definitions](https://github.com/NVIDIA/DLSS/blob/main/include/nvsdk_ngx_defs.h));
there is no public teacher checkpoint or training recipe to substitute for the
captured teacher path.

The v48 negative-control run is preserved at
`E:\OpenNR_Training\fresh_combined_identity_cooldown_v48_probe_0.5.5_20260906`;
its status is `early_stopped`, and its best checkpoint is the unchanged v47
initialization at step 0.

## Next-grid cohort and follow-up training — 2026-09-06

The next capture step was executed as a 105-sequence four-crop grid pilot at
the exact Feature 18 RGB/depth/native-motion contract. Structural and crop
temporal validation passed for all 105 sequences. A conservative all-crop
content audit excluded 13 motion-anomalous sequences from recurrent loss,
leaving 92 clean temporal sequences; all 105 remain available as a labeled
spatial-only auxiliary source. The crop-aware cache builder and temporal-loader
role guard were updated so duplicate crop rows cannot be mistaken for one
temporal stream.

The new data was trained in three controlled same-width probes, one all-data
fixed fit, and one bounded width-160 arm. None improved the v65 parent. The
best v65 parent measured `0.021573284` on the merged 60-sequence held-out test;
the completed all-non-test v71 fit measured `0.021731749`, so it was rejected.
The new-grid test specifically measured `0.027438652` for v65 and
`0.027926762` for v71. The detailed cache, hash, visual, and early-stop record
is now [NEXT_GRID_TRAINING_RESULT_0.5.5_20260906.md](D:/.CODEX_Projects/OpenNR-VR/docs/NEXT_GRID_TRAINING_RESULT_0.5.5_20260906.md).

This result changes the next priority from same-recipe training to a
conditioning/target iteration: preserve the exact native guide contract,
capture deliberate high-effect and independent environments, and expose
auditable renderer-derived albedo/normal/illumination/material/semantic/history
conditionings if the renderer boundary allows it. The target remains open and
no candidate is installed in the live runtime.

## Latest-cache width confirmation and local loss probes — 2026-09-07

Using the latest strict caches, a three-arm width ablation tested capacity
branches `128/6 + 64/3`, `160/6 + 80/3`, and `192/6 + 96/3` from the v65
parent under identical data, sampling, loss, initialization, and 1,000-step
budgets. Independent evaluation showed all three arms beating v65 on both the
prior and new validation cohorts. Arm C was best at `0.019690728` prior and
`0.019369167` new, versus v65 at `0.019805003` and `0.019977055`; its frozen
merged-test MAE was `0.021328798` versus v65 `0.021427386`. This is a real but
modest transfer gain, not a new quality regime or evidence that the `0.011`
target is close. The extreme-effect tail was slightly stronger in Arm A, while
all arms retained a low-effect identity regression.

Two zero-cloud-cost continuation probes on the RTX 5070 Ti did not identify a
replacement recipe. Adding `--effect-high-frequency-weight 0.05` improved the
new validation cohort but slightly worsened the prior cohort, and doubling
`--micro-identity-weight` from `1.0` to `2.0` degraded both cohorts from its
Arm C starting point. A third probe that held the recipe fixed but halved all
learning rates likewise kept step 0 as its best checkpoint; its final
step-400 values were `0.0197196` prior and `0.0193749` new. The complete
evidence and paths are recorded in
[RUNPOD_LATEST_CACHE_WIDTH_ABLATION_0.5.5_20260907.md](D:/.CODEX_Projects/OpenNR-VR/docs/RUNPOD_LATEST_CACHE_WIDTH_ABLATION_0.5.5_20260907.md).

The pre-registered different-seed confirmation then ran on a secure RTX 5090
with the immutable old, new, and spatial caches. After exact byte/hash
verification, a 50-step calibration passed at `17.60 GiB` peak allocated VRAM;
the full seed-338 run completed without OOM or nonfinite values. Independent
validation of its step-500 best checkpoint measured `0.019714982` prior and
`0.019330343` new. It beats v65 on both cohorts, but does not beat seed-337
Arm C on both (`0.019690728` prior, `0.019369167` new), so seed-337 Arm C
remains selected and no additional capacity-only cloud run is justified.
The low-effect identity regression persists (`0.007083` / `0.007556` student
MAE versus `0.004619` / `0.004720` identity MAE in prior/new cohorts). The
seed-338 artifacts and matched visual sheet are retained in
`E:\OpenNR_Training\runpod_arm_C_seed338_confirmation_0.5.5_20260907`; the
temporary Pod was deleted after SHA-256-verified recovery and no test data was
read for selection.

A zero-cloud local follow-up then tested the existing zero-initialized
context-style modulation path on Arm C for 400 steps. Its independent best
checkpoint measured `0.019704359` prior and `0.019328705` new, improving the
new cohort but regressing the prior cohort relative to Arm C. It is rejected
by the two-cohort rule; the next credible improvement still requires better
renderer-derived conditioning or a new capture/data representation rather
than another capacity-only variant.
