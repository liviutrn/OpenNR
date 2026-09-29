# Oversized U-Net fitting experiment

Authority: read the complete revised objective at `C:\Users\oleks\.codex\attachments\3df10bd8-bc78-4ee2-ac2f-bb9d79486ed6\goal-objective.md`. The overall goal remains held-out MAE .011 and teacher appearance. The immediate requested experiment is an oversized predictor on a tiny fixed subset trained toward convergence.

Implemented `tools/oversized_tone_head.py`:38,454,796 parameters, encoder widths16/32/64/128/256/512, full-resolution stem, half/quarter-resolution features, residual blocks, four512-channel bottleneck residual blocks, decoder skips to quarter resolution, bounded affine RGB coefficient output. Current normal inputs: sourceRGB, frozen parentRGB, aligned native guides5channels, context8channels. No teacher targets or sample identifiers are predictor inputs. The affine bounds and output grid remain comparable to the target-assisted fitting diagnostic. Model and activation size fit the local5070Ti.

Native512 Float32 GPU smoke passed exact initial identity, output bounds/finiteness, nonzero gradients at the output, full-resolution stem, and bottleneck. Peak allocated smoke memory539.5MiB excludes full trainer/optimizer/sample storage and is not runtime deployment evidence.

Data: the same twelve training images from six sequences, two eyes, causal frame32; upper-median and maximum training-error sequence per cohort. Loaders deny test access; each parent output must reproduce the prior diagnostic within1e-7. All captures and prior checkpoints remain available.

Recipe: seed358,AdamWlr3e-4,no weight decay,pureL1,Float32,round-robin twelve images,maximum8000updates,evaluation every200. ReduceLROnPlateau halves learning rate after three evaluations without absolute improvement2e-5; minimum1e-6. Plateau criterion: at least2400updates, learning rate at most1e-5, and best MAE improvement below5e-5 over the last five evaluation intervals. Report the actual near_converged flag; reaching8000 alone does not establish convergence. Save best diagnostic checkpoint plus last head/optimizer/scheduler/history for continuation. No resume CLI implemented yet; state is preserved for a verified continuation if needed.

Outputs: `E:\OpenNR_Training\tone_oversized_unet_fit_20260907` and sequential replay/gallery at `E:\OpenNR_Training\tone_oversized_unet_replay_20260907`. Model source hashes and exact image membership are checked on replay. Training and replay pending at launch.

Interpretation: <=.007 training MAE is evidence of fitting capability on this set; .008..011 is promising; a plateau around .014..016 motivates input/formulation/optimization investigation. Small-set memorization does not prove sufficient information for unseen scenes, and finite-run failure does not prove missing information. Do not mark the overall .011 goal complete from training scores. Next stages in the user's objective include stronger inputs/context, separate detail corrections, hard examples and loss design, and broad ordinary-MAE/temporal/visual evaluation as supported by results.

## Optimization failure and stabilized retry

Initial session96116 stopped deliberately after saved step2800. MAE jumped from .02293 to .09910614788532257 by step800 and remained exactly flat. The controlled-input diagnostic on last_resumable.pt found raw coefficients -1.366e15..3.129e14,100% absolute values above10,and zero affine-weight gradient. Output was constant .25 on the controlled .4RGB input. This is activation explosion/tanh saturation evidence, not a fitting limit or missing-input evidence. All original artifacts retained; the run's old status file may still say training because KeyboardInterrupt bypassed its Exception handler. Tool session exit1 and absence of matching Python processes confirmed termination.

Added `stable_oversized_tone_head.py`, inserting GroupNorm after internal convolutions while preserving the original architecture source. New parameter count38,477,484. Normalization changes the predictor and may affect absolute-brightness representation; it is a stabilization hypothesis to evaluate. Exact initial identity and five native512 optimization updates passed, finite loss .01325 on synthetic reachable brightening.

Fresh retry: `E:\OpenNR_Training\tone_stable_unet_fit_20260907`,lr1e-4,otherwise same8000-step cap/plateau policy and twelve images. Separate sequential replay at `tone_stable_unet_replay_20260907`. No result or convergence claim at launch.

## Stabilized run reaches the fitting milestone

Session80891 training reached8000updates, mean training-image MAE .005724326785032948, with best at8000. Milestones:1200 .01089713;3200 .00735893;4000 .00696187;5400 .00642398;6200 .00594632;7800 .00573560. Learning rate fell1e-4 to5e-5 at6000, then2.5e-5 at7000. This satisfies the objective's <=.007 training-image diagnostic milestone. The recorded near_converged flag remains false; step cap reached with learning rate above the plateau threshold. Exact replay is queued/running; best and last optimizer state are saved for continuation.

Interpretation: one shared input-only predictor can fit the fixed twelve-image set near the target-assisted range. The earlier .014..016 fitting results are not evidence of missing input information. This is still memorization evidence on six training sequences, not held-out MAE or proof that inputs suffice for generalization. Next: complete replay and inspect images, then continue from optimizer state toward the predefined plateau before drawing the final diagnostic conclusion. Broad training/validation remains necessary to pursue the overall .011 goal.

Replay subsequently completed in session80891, exit0. All twelve replay differences exactly0; checkpointSHA2565a92ddd9d0e8c25bb81d3a709fb46757bb857ffb1535acbe8ab128bd3b29a17c. Per-image MAE ranges .00264460...00863922, all twelve below.011; <=.007 milestone is a mean, not an all-image claim. Inspected armor image `tone_stable_unet_replay_20260907\seq-1788740617923-25-eye1.png`: fitted lighting/color is visibly closer to teacher than previous heads, with differences still remaining. Full convergence remains pending; no live process remains from session80891.

## Near-convergence continuation completed

Implemented resume into a fresh output directory with architecture/input hashes and image-set validation, exact per-image checkpoint replay before updates, optimizer/scheduler restoration, original step-dependent round-robin order, and retained best checkpoint. Resume at8000 reproduced every image exactly and restoredlr2.5e-5,scheduler epoch41; initial evaluation was not repeated into the scheduler history.

Session85649 completed exit0. Output `E:\OpenNR_Training\tone_stable_unet_converge_20260907`. Predefined near_converged criterion became true at12200,lr6.25e-6; this is an operational plateau criterion, not proof of a global optimum. Selected best step12000, mean training MAE .005437374231405556. The last five evaluation intervals improved best error by less than5e-5. All twelve individual MAEs are below.011, range .0025025182...0080701727.

Replay `E:\OpenNR_Training\tone_stable_unet_converged_replay_20260907\verification.json`: all twelve errors reproduced with zero difference. Best checkpointSHA25650a0b1bfc431d59307eae8fc6680a1252d1c9086f91731ba83461dc28eb501e4. Diagnostic milestone <=.007 training mean achieved and replay verified. The required near-convergence subset experiment is complete. The broader .011 validation and facial/temporal objectives remain open.

Next authorized work: fresh stabilized U-Net head trained across existing three training cohorts, preserving frozen parent and matched normal inference inputs, ordinary full-sequence validation and temporal metrics, and teacher/parent/candidate facial sheets. Do not initialize broad candidate from this deliberately overfit checkpoint. The twelve-image result establishes fitting capability and motivates a generalization experiment; it cannot establish sufficient input information on unseen scenes or that38M parameters are necessary.
