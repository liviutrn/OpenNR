# Semantic-parent continuation protocol and preparation checks

The active seed812 comparison saves full optimizer and RNG state. If its measured trajectory justifies more training, `tools/continue_semantic_parent_training.py` extends a completed arm to an absolute total update count without resetting optimization. The longer budget will be chosen from the paired results; no extension has started yet.

## Preserved contract

The continuation loads and verifies the saved head and trained parent together, preserves the frozen/trainable parent distinction, restores both AdamW parameter groups, and restores NumPy, Torch CPU and CUDA RNG state. It reconstructs every preceding sampled window from the original seed, checking the recorded sample SHA256, cohort draw counts and saved NumPy RNG before continuing. It keeps the existing learning rates, objective, eight-frame windows, two-frame burn-in and batch1.

Initial full validation must reproduce the predecessor checkpoint within 1e-7 for MAE, PSNR, temporal-delta and first-frame MAE. Selection remains relative to the original common-start validation, rather than treating the new phase as a fresh easier baseline. The predecessor's selected checkpoint is copied with SHA256 verification before any new candidate can replace it. A joint continuation requires the completed matched frozen-parent continuation at the same total steps, evaluation schedule, seed, data and continuation start step.

The new phase records its own source hash and the predecessor source/history/checkpoint identities. Checkpoints retain optimizer/RNG state, cumulative sample hashes and draws, the original common-start metrics and best score. A free-space reserve is checked before setup and each checkpoint write; source data is not automatically deleted by the trainer.

Each evaluated checkpoint is also preserved as `checkpoint_<step>.pt` with a SHA256 record. On the local filesystem this uses a hard link to the completed checkpoint; subsequent `last.pt` writes use atomic replacement, preserving earlier snapshots. A copy fallback is available when hard links are unsupported. This avoids losing a matched intermediate control needed for later replay or continuation.

## Verification completed so far

Three CPU property tests pass in `tools/test_semantic_continuation.py`: future sampling agrees after restoration, altered sampling/RNG state is rejected, and two-group AdamW produces bit-exact final weights when resumed versus uninterrupted execution. These tests exercise the shared restoration helpers.

The actual seed367 joint step400 checkpoint also passed a training-only sampling preflight. Its 400-window hash reproduces exactly as `8e1b3377fe85cadcbd002dceeec16b44dec360989a15aa6066db84681dcf36c7`, with draws151/64/34/66/42/43 and exact saved NumPy RNG agreement. Both optimizer groups are present at learning rates1e-4 and1e-5. Record: `out/semantic_resume_preflight_20260908.json`.

This validates the preparation and CPU restoration properties. A full-model GPU continuation has not run yet; the predecessor-replay gate remains mandatory before its first new update. The active goal still requires ordinary 1× MAE <=0.011, convincing teacher color/visual match and temporal stability.
