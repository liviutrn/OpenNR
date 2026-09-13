# Multiscale predictor fitting probe

Implemented and launched locally after six tone-head unit tests passed. Uses the same twelve training images and frozen verified parent as the shared local-head fitting probe. No validation/test access, no cloud spend, no game changes, no promotion.

Question: can a predictor combining quarter-resolution local features, 1/32-resolution spatial features, and crop-global pooled features learn the required corrections better than the local-only predictor? It retains the same bounded RGB affine output at a quarter-resolution coefficient grid. This changes architecture and parameter count together, so it is not a parameter-matched causal isolation of context. No coordinates, image identifiers, or teacher targets enter the predictor. Teacher is used only for L1 loss. Crop-global does not mean full original rendered frame.

Recipe: seed358,1200updates,lr1e-3,AdamW without weight decay,one image/update round-robin,Float32 head,static causal frame32 parent outputs. No temporal loss. The previous local-only probe reached mean training MAE .021219986646125715; direct target-assisted fits were much closer but are not student performance. Same number of updates/images, not equal compute or initialization weights across architectures.

Code: `tools/multiscale_tone_head.py`, `tools/train_tone_fit_probe.py`. Tests cover exact identity initialization, finite bounded outputs, nonzero gradients through all feature branches after opening the output layer, frozen parent gradients and unchanged parent feedback. Original head modules remain unchanged, preserving checkpoint replay compatibility.

Training output: `E:\OpenNR_Training\tone_multiscale_fit_probe_20260907`. Sequential replay/image output: `E:\OpenNR_Training\tone_multiscale_fit_replay_20260907`. Completion, actual result, and visual inspection pending. Diagnostic checkpoint only; a low training-set MAE does not establish held-out .011 or visual/VR acceptance.

## Result

Session98207 completed successfully. Mean training-image MAE fell from .024267285130918026 at step0 to .016411535907536745 at step1200. Replay session38308-style checks were run through the probe's verify path; all twelve per-image replay differences were exactly0.0, with checkpoint SHA25636f7dd16bc53dd425a9ee29ff3f7fad8f5a8ed2ffd2ae7e0aa93c9b0017f3769. The multiscale predictor improves over the local-only probe's .021219986646125715, but remains above .011 on the same training images. It is evidence for a more capable predictor hypothesis, not held-out evidence.

Inspected `E:\OpenNR_Training\tone_multiscale_fit_replay_20260907\seq-1788740617923-25-eye1.png`; the training fit changes color/shading toward the teacher but still does not reproduce it fully. It is labeled TRAINING FIT ONLY. Next broad experiment, if run, must use a fresh architecture-aware trainer, all three train/validation cohorts, test denied, checkpoint replay, and visual sheets; this diagnostic checkpoint is not an initialization candidate or deployment artifact.
