# Joint causal-parent and semantic-head training: verified pilot result

The 400-update joint candidate independently improves MAE and temporal-delta error on all six ordinary validation cohorts against the verified common start. It beats the matched frozen-parent control on four MAEs and all six temporal errors. It remains above the 0.011 target, retains visible teacher color/shading differences, and is not promoted. A [new-seed paired replication](SEMANTIC_PARENT_REPLICATION_20260908.md) is now running.

| Cohort | Common-start MAE | Frozen-parent control | Joint-parent MAE | Joint temporal error minus start |
|---|---:|---:|---:|---:|
| Prior |0.019231266|0.018993051|0.017920465|-0.000105607|
| High-effect |0.017656344|0.017328189|0.016532684|-0.000076270|
| Older renderer |0.014859464|0.014350323|0.014176818|-0.000220294|
| Fresh September7 |0.016249614|0.015375280|0.015512909|-0.000054299|
| Renderer-state |0.020117967|0.020836952|0.020089761|-0.000170350|
| New19 |0.029031637|0.027927639|0.028102639|-0.000023278|

The fresh-session and new19 MAEs lose to the matched control by 0.0001376 and 0.0001750 respectively. The renderer-state gain against common start is only 0.0000282, so seed replication is especially important. This is a useful joint-training result, not a universal win over the control or evidence that every remaining error comes from frozen state.

All 18 independent MAE/PSNR/temporal replay differences are exactly zero. Endpoint SHA256: `278293934f5b41650c5a5c2c52ea82a325b125e5ad6a1f420bdd1e75e5931c63`. All 304 parent tensors changed; all 175 encoder tensors remain exactly equal to the pretrained weights. All model tensors are finite, and optimizer plus NumPy/Torch/CUDA RNG states are saved. The full run completed in 478.68 seconds at 9.92 GiB peak allocated memory. Artifacts and 48 fixed visual comparisons are under `C:/OpenNR/Training/semantic_joint_parent400_20260908/independent_replay`; the tensor audit is `tensor_verification.json` in the run directory.

The remaining sections preserve the preregistration and execution record.

The first pretrained semantic-feature pilot improves five ordinary cohorts from the common warm model, but regresses on renderer-state validation. Its registered training-subset probe shows useful learned features on all six subsets. The projection-only comparison is still running to test whether freezing the U-Net avoids this tradeoff.

Source inspection confirms a separate untested restriction: `FrozenParentToneModel.forward_temporal` executes the entire causal parent under `no_grad`, so the output objective cannot adapt its temporal representation. The prepared alternative removes that optimization restriction while preserving the existing parent-owned recurrent state and the same inference computation. Corrected head pixels are still not fed back. It adds no teacher pixels, optical flow, new renderer resources or runtime changes.

## Fixed comparison, if selected after the projection-only result

- Reuse the completed `C:/OpenNR/Training/semantic_pretrained_arm400_20260908` frozen-parent run as the matched control. This is a reused control, not independent replication.
- Start from the exact verified broad5600 head and seed352 causal parent, not the unpromoted semantic endpoint. Keep the pretrained DINOv2 encoder frozen.
- Same six ordinary cohorts, sampling probabilities, seed367,400 steps, head LR1e-4, AdamW weight decay1e-4, BF16, eight-frame windows/two burn-in frames/batch1, and the same L1/pooled/temporal objective.
- Enable gradients for all causal-parent weights at LR1e-5. Clip head and parent gradient norms separately at1, retaining the control's head clipping behavior.
- Enforce full six-cohort initial identity and identical sampled windows/draws. Compare every endpoint against both common start and frozen-parent control, including temporal error.
- Save trained parent weights, head weights, optimizer and RNG states together. The distinct checkpoint architecture must be loaded by the joint-parent verifier so replay cannot silently substitute the original parent.

At preregistration, training, memory fit and independent replay were unverified. Their completed results are recorded above; the ordinary 1× 0.011/temporal/visual/color target is unchanged.

## Preparation checks

`tools/smoke_joint_parent_tone.py` passed CPU FP32 checks at128x128: exact initial prediction and recurrent-state equality, finite gradients in304 parent tensors and208 head tensors, and zero encoder gradients. This verifies graph connectivity only; it does not establish512x512 GPU memory fit or model quality. Record: `out/joint_parent_cpu_smoke.json`.

Prepared implementation: `tools/joint_parent_tone_model.py`, `tools/train_semantic_joint_parent.py`, and `tools/verify_semantic_joint_parent.py`. The training and replay tools compile. Existing running trainers and checkpoint source files remain unchanged.

## Registered follow-up decision

After the projection-only pretrained arm completes, independently verify its selected checkpoint's frozen tensors, replay all six validation cohorts and render the fixed comparison gallery. If any registered checkpoint improves all six MAEs against common start, assess that candidate before changing direction. If none does, run the400-update joint-parent alternative above, then independently replay/render its endpoint. This is a new optimization mechanism, not an extension of the failed projection-only recipe. The one-off local queue is `tools/run_semantic_followup_20260908.ps1`; it stops on failed verification or training. Runtime and capture settings remain unchanged.

## Selected and training

The projection-only arm produced no eligible checkpoint and its endpoint independently replayed exactly, so the registered queue selected this alternative. `C:/OpenNR/Training/semantic_joint_parent400_20260908` passed exact six-cohort initial replay and has completed optimizer updates at 512×512. Trainable counts are 3,480,979 parent parameters and 38,502,124 head parameters; the encoder remains frozen. Peak allocated GPU memory through update 150 is 9.92 GiB on the local 16 GiB GPU. This establishes actual memory fit and training execution, not quality improvement. The final matched comparison and independent replay are pending.
