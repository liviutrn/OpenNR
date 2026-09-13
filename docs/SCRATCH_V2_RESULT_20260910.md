# Scratch-v2 versus protected-best finetune — result — 2026-09-10

## Decision

Scratch-v2 did not improve on finetuning the existing learned representation.
Under the same 3,200-update curriculum, the matched finetune arm was:

- **24.8% better** than scratch-v2 on ordinary renderer-pilot validation MAE;
- **11.7% better** on the unweighted old-six cohort mean;
- still well above the project target of ordinary 1× MAE `<= 0.007`;
- not a promotion candidate because the broad MAE and broad temporal gates were
  not both satisfied.

This closes the current scratch-initialization question. More random restarts
or a longer blind scratch run are not justified by the evidence. The learned
initialization remains materially valuable.

## Controls and provenance

Protected overall-best checkpoint:

`C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`

Protected SHA-256:

`40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`

Protected parent SHA-256:

`2024593e3ebacb576c2848d0176bc0d8a16bbc35e1250f0dda519937778c5f60`

The immutable 18-sequence cache, clean7 cache, invalid `seq8` stream, all
previous checkpoints, and all six protected training/validation cohort
manifests remained controls. The primary scratch-v2 corpus contained exactly
the six cohorts recorded by the protected checkpoint. Clean7 was not mixed
into this parity run because the paired 5% recovery test had already failed to
show a benefit.

## Experiment design

The primary output root is:

`C:\OpenNR\Training\semantic_scratch_v2_vs_finetune_20260910`

Runner:

`D:\.CODEX_Projects\OpenNR-VR\tools\train_semantic_scratch_v2_vs_finetune.py`

Plan:

`D:\.CODEX_Projects\OpenNR-VR\docs\SCRATCH_V2_PLAN_20260910.md`

Both arms used:

- the exact recorded `context_v7_capacity_temporal` graph;
- frozen pretrained DINOv2 features;
- six sequence-disjoint old cohorts, with no test rows read;
- seed `909`, contiguous temporal windows of length `8`, burn-in `2`, batch `1`;
- pixel-only per-frame L1, AdamW weight decay `1e-4`, gradient clipping `1.0`;
- nominal head/parent learning rates `1e-4` / `1e-5`;
- a 200-update warm-up from 20% of nominal rates followed by cosine decay to
  20% of nominal rates;
- the exact same serialized sample-window schedule.

The schedule digest is:

`dc0bfb5917bbbd3fd4a2f05809fb61d43b0ee4f7e3272b97888e558a8043380e`

Its three stages were:

| Stage | Updates | Cohort probabilities in `[prior, high_effect, renderer_pilot, fresh_session, renderer_state, new_pairs]` |
|---|---:|---|
| Broad acquisition | 1–1,600 | `[0.40, 0.15, 0.10, 0.15, 0.10, 0.10]` |
| Target-balanced | 1,601–2,400 | `[0.30, 0.15, 0.20, 0.15, 0.15, 0.05]` |
| Broad restoration | 2,401–3,200 | `[0.35, 0.15, 0.15, 0.15, 0.15, 0.05]` |

The 400-update calibration completed first with finite loss and approximately
9.92 GiB peak CUDA allocation. The primary run then completed both arms at
3,200 updates without nonfinite values or memory failure.

## Matched trajectory

The values below are validation metrics. The old-six mean is the unweighted
mean of the six primary cohorts. The protected reference ordinary value is
approximately `0.013283985`; the project target is `0.007000000`.

| Step | Scratch renderer MAE | Finetune renderer MAE | Scratch old-six mean | Finetune old-six mean |
|---:|---:|---:|---:|---:|
| 0 | 0.032923446 | 0.013283985 | 0.028786223 | 0.017770087 |
| 400 | 0.024278851 | 0.014749819 | 0.023487265 | 0.018799530 |
| 800 | 0.018751768 | 0.012737018 | 0.020559194 | 0.017526675 |
| 1,200 | 0.018165980 | 0.012482423 | 0.020687220 | 0.017939691 |
| 1,600 | 0.016747769 | 0.012893520 | 0.020358733 | 0.017506274 |
| 2,000 | 0.016374298 | 0.011832370 | 0.020016548 | 0.017373701 |
| 2,400 | 0.016105795 | **0.011729875** | 0.019815280 | 0.017217151 |
| 2,800 | 0.016046598 | 0.011869463 | 0.019781134 | **0.017183601** |
| 3,200 | **0.015965142** | 0.012004774 | **0.019546636** | 0.017254557 |

Scratch improved continuously from its identity-safe initialization, but it did
not catch the learned initialization. The finetune arm's best narrow ordinary
number in this run was `0.011729875` at step 2,400, and its final value was
`0.012004774` after the restoration stage. The step-2,400 checkpoint is about
0.92% better than the earlier renderer-focus candidate's `0.011838914`, but it
is not a promotion: at that point `renderer_state` MAE was `0.020286691`
versus the protected `0.019688752`, and `prior` temporal delta was
`0.008505436` versus the protected `0.008317676`. The final restoration stage
traded a small amount of narrow ordinary performance for a more favorable
broad profile, but still did not pass the broad gates.

## Final validation and gate diagnosis

Final step-3,200 values by cohort:

| Cohort | Scratch MAE | Finetune MAE | Protected MAE | Finetune temporal delta |
|---|---:|---:|---:|---:|
| prior | 0.018606979 | 0.018445039 | 0.019004597 | 0.008411688 |
| high_effect | 0.016855901 | 0.014575699 | 0.015705697 | 0.007394959 |
| renderer_pilot | 0.015965142 | **0.012004774** | 0.013283715 | **0.009296845** |
| fresh_session | 0.015176398 | 0.014045161 | 0.014562632 | 0.005270593 |
| renderer_state | 0.019648337 | 0.019520332 | 0.019688752 | 0.007349884 |
| new_pairs | 0.031027056 | 0.024936339 | 0.024374998 | 0.010741368 |

The finetune arm improved five of six old-cohort MAEs relative to the
protected reference. The broad MAE gate still fails because `new_pairs`
regressed from `0.024374998` to `0.024936339`. The broad temporal gate fails
because `prior` temporal delta increased from `0.008317676` to `0.008411688`,
despite the renderer-pilot temporal improvement. This is exactly the kind of
narrow/broad tradeoff the staged restoration phase was intended to expose.

The final finetune renderer-pilot temporal delta was `0.009296845`; scratch
ended at `0.011119240`. The final finetune eye MAEs on renderer-pilot were
left `0.012947693` and right `0.011061856`; scratch ended at left
`0.018964919` and right `0.012965366`. Visual teacher resemblance, color
matching, stereo artifacts, live Skyrim behavior, and VR-budget acceptance
were not measured in this experiment, so they remain unverified.

## Final artifacts

Scratch-v2 checkpoint:

`C:\OpenNR\Training\semantic_scratch_v2_vs_finetune_20260910\scratch_v2\checkpoint_3200.pt`

SHA-256:

`5aaf2405496ebaf9adf622873a2fa7bcc6d4e9154b7abb22108bfdfb9ecd6a91`

Matched finetune checkpoint:

`C:\OpenNR\Training\semantic_scratch_v2_vs_finetune_20260910\finetune_v2\checkpoint_3200.pt`

SHA-256:

`4eb394cf7bd06d1e5e414ad1c9ef5c46f67d40d5b19515c00d667803e108b584`

The recorded narrow-best intermediate finetune checkpoint is retained at:

`C:\OpenNR\Training\semantic_scratch_v2_vs_finetune_20260910\finetune_v2\checkpoint_2400.pt`

Its checkpoint SHA-256 is
`c499889a889408d259db07451e19db5ee7ff41b6bc08de6e3a7ae148ef252109`.
Its `0.011729875` ordinary value is from the paired training validation
history; the independent replay pass below was run on the final 3,200-step
checkpoints.

Independent batch-1 replays both passed exactly:

- finetune replay: `replay_match = true`, `max_abs_difference = 0.0`;
- scratch replay: `replay_match = true`, `max_abs_difference = 0.0`.

Replay directories:

- `C:\OpenNR\Training\semantic_scratch_v2_vs_finetune_20260910\replay\finetune_v2_checkpoint_3200_replay.json`
- `C:\OpenNR\Training\semantic_scratch_v2_vs_finetune_20260910\replay\scratch_v2_checkpoint_3200_replay.json`

The primary experiment reports `test_used = false` throughout.

## Storage and next action

The primary result root occupies approximately `10.42 GiB`; the separate 400
step calibration occupies approximately `2.69 GiB`. C: has approximately
`147.3 GiB` free, still above the `100 GiB` cleanup guard. No files were
deleted, and no cleanup is justified yet. Runpod was not used because the
local graph fit under 10 GiB.

Decision:

1. keep the protected overall-best checkpoint immutable;
2. keep the v2 finetune as an experimental, non-promoted artifact;
3. stop expanding random scratch runs;
4. do not extend the v2 finetune blindly—the remaining gap to `0.007` is
   `0.005004774` at the final v2 checkpoint;
5. prioritize new sequence- and scene-disjoint native-guide full-eye temporal
   supervision or a separately validated target/objective change, then compare
   that against the protected best with a matched finetune control.
