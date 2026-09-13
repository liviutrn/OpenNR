# Matched-frame temporal-context diagnostic

Question: does resetting state at short-window boundaries materially change predictions or teacher error relative to continuous64-frame history? This follows the completed learning-rate comparison, which did not improve the retained candidate.

Use verified seed352 retained step400 checkpoint, all207 training sequences and both eyes, corrected guide overlays. For each64-frame stream run continuous history and independent eight-frame blocks. Compare identical frames only: offsets2..7 after the two warm-up frames, excluding the initial block where histories are identical. Each eye contributes42 frames,17388 eye frames total. Save full-history MAE, window-history MAE, pairwise prediction MAE and per-eye/sequence values.

This fixed block-offset diagnostic samples but does not exhaust random training-window starts. It measures inference-context sensitivity, not gradient truncation, training trajectory, or proof that longer training windows help. No optimization, validation selection, frozen tests, or runtime changes. Original artifacts remain unchanged.

Script tools/diagnose_temporal_context.py. Output E:/OpenNR_Training/temporal_context_diagnostic_20260907. Live session32141; poll without restarting. Progress includes completed eye-stream counts so long evaluation is observable.

## Completed paired replay

Session32141 exited zero. Counts reconcile to17388 matched eye frames:15456 prior,1428 high-effect,504 latest. Full/window MAE respectively: prior0.0181444756 /0.0181467242; high-effect0.0180776294 /0.0180679768; latest0.0153262069 /0.0153243145. Mean absolute prediction differences are0.0000967845 /0.0000971023 /0.0000927880. Absolute aggregate teacher-MAE differences are below0.00001 in all cohorts.

This read-only diagnostic finds little aggregate error sensitivity to the tested reset schedule after two-frame warm-up. It does not support history-reset mismatch as a large explanation for the roughly0.004-0.008 remaining MAE gap. It does not test gradient truncation or establish that longer-window training cannot help. No weights changed; no held-out success claim. Next prioritize training-error structure or missing appearance conditioning rather than allocating a long-window experiment solely on this hypothesis. Full per-stream evidence is in result.json.
