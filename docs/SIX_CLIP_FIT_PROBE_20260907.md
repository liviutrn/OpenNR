# Concentrated training-only fitting probe

Purpose: determine whether the existing retained architecture can materially reduce error on a fixed six-clip training subset. This does not measure held-out performance or establish that 0.011 is broadly achievable.

Selection is deterministic from the completed training-only error report: upper-median error and maximum-error sequence in each of prior/high-effect/latest cohorts. All64 frames and both eyes are retained. No validation or test sequence enters optimization. The source fit report and selected checkpoint are hash checked; selected IDs are saved in run.json.

Fixed recipe: seed354,600 steps, all existing weights train, round-robin cohort sampling with random clip/eye/window, window8 burn-in2, AdamW1e-5 with no weight decay, pure L1, no augmentation or EMA. Full causal training-subset evaluations at0/200/400/600. This changes several optimization conditions together to test fitting ability, not causally identify any single cause. Failure is not proof of a capacity ceiling; success is not generalization evidence.

Output E:/OpenNR_Training/retention_six_clip_fit_probe_20260907. Script tools/train_retention_fit_probe.py. Live execution session47618; poll without restarting. The final checkpoint is explicitly diagnostic_only.pt, not a production candidate. Original models, all captures, and all split identities remain unchanged. No Runpod or runtime/public-build modifications.

## Completed result

Session47618 exited zero,600 steps in206.06 seconds. Initial prior/high-effect/latest subset MAE0.031558757 /0.021203759 /0.016988476; final0.019115455 /0.013005703 /0.012798348. Concentrated fitting improved every subset substantially, but none averaged0.011. This is not a capacity ceiling or generalization result. Preserve diagnostic_only.pt separately and do not initialize broad candidate training from it.

Next: matched full-training-set learning-rate comparison from verified retained seed352 checkpoint, not this probe. The probe changed multiple conditions and therefore only motivates the hypothesis; it does not prove learning rate caused the gains.
