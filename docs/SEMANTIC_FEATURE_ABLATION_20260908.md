# Frozen semantic-feature conditioning: registered comparison

The native-pixel residual400-step pilot regressed against its affine control on all six ordinary cohorts. The alternative tested here is representation transfer rather than further output width or a longer version of that failed run.

## External basis and local boundary

The [official DINOv2 project](https://github.com/facebookresearch/dinov2) provides a21M-parameter ViT-S/14 visual encoder pretrained without labels. Its general feature utility motivates a hypothesis, not a claim about Skyrim teacher matching. This experiment uses the existing local source at `C:/Users/oleks/.cache/torch/hub/facebookresearch_dinov2_main` and existing `dinov2_vits14_pretrain.pth` weights. No download, rental, or runtime installation is necessary. Local Python source hashes and weight SHA256 are recorded per run; the source is loaded locally and weights are loaded strictly.

## Mechanism

Resize current input RGB to224x224, apply fixed ImageNet mean/std normalization, and obtain the final normalized384-channel patch-token map at16x16. The encoder is frozen and remains in evaluation mode. A zero-initialized384-to-64 projection injects these spatial features into the stable U-Net's quarter-resolution decoder before its existing affine output. The input is always current source RGB; no teacher pixels or teacher state enter inference.

Control: identical frozen DINOv2 architecture with deterministic random initialization. Intervention: frozen official pretrained DINOv2 weights. This isolates pretrained representation under the same conditioning path. Both keep the exact verified step5600 stable U-Net warm start and frozen causal parent. The affine-only control from the prior experiment remains an additional reference, not a replacement for the matched random-encoder control.

GPU smoke at512x512 confirms exact initial identity among the plain warm head, random encoder and pretrained encoder (max output difference0), nonzero projection gradient, and no encoder gradients even after `.train()`. Total head parameters60,558,700; trainable38,502,124. This is research capacity, not VR-budget acceptance. Full pilot memory/timing will be measured independently.

## Fixed recipe and acceptance

Use the same six ordinary1x cohorts, probabilities0.40/0.15/0.10/0.15/0.10/0.10, seed367,400 steps, LR1e-4, AdamW weight decay1e-4, window8/burn-in2/batch1, BF16, and RGB L1+.5 pooled16 RGB L1+.12 temporal-error delta as the completed native-output comparison. Both arms train the existing U-Net and new projection; both freeze the encoder and causal parent. No two-pass or frozen-test tuning.

Require exact step-zero six-cohort agreement, matching sample hashes and draw counts, and separate comparisons against common start and random control. Promotion still requires broad ordinary-cohort improvement, temporal stability, independent checkpoint replay, convincing color/visual match and the MAE target. A useful learned semantic response alone is insufficient.

Outputs: `C:/OpenNR/Training/semantic_random_control400_20260908` and `C:/OpenNR/Training/semantic_pretrained_arm400_20260908`. Do not extend this pilot automatically if its measured evidence is negative.

## Control completed; pretrained arm started

The random-encoder control completed400 steps in407.16 seconds at4.37GiB peak allocated GPU memory. It retains the common step0 checkpoint under the six-cohort gate. The pretrained arm then started from the same verified warm head with the same scientific settings. Its full six-cohort initial equality and matched sample schedule are enforced by the trainer.

The separate context-extent diagnostic had a13.1% training-subset gain but a small spatial-validation regression. Therefore that context result is not a validated reason to claim this semantic arm will help; this remains its independently registered representation-transfer hypothesis.

## Registered endpoint training-subset diagnostic

Before seeing the pretrained endpoint, register a fixed fit/response probe: first and last training sequence in each of the six cohorts, both eyes, all64frames (normally12sequences/1,536 eye frames). Compare the common warm head, completed random control, pretrained endpoint, and the same pretrained endpoint with its semantic projection temporarily disabled. No weights are changed. This is a bounded training-subset score, not full training MAE or held-out evidence. Its purpose is to distinguish an active useful feature branch from whole-head drift or an inert conditioning path. Tool: `tools/probe_semantic_training_fit.py`.

## Pretrained endpoint: promising older-cohort gains, newest-cohort regressions

The pretrained arm completed400 steps in405.43 seconds. All18 initial MAE/PSNR/temporal values match the control exactly. The six-cohort gate still retains step0.

| Ordinary cohort | Common start | Random encoder | Pretrained encoder |
|---|---:|---:|---:|
| Prior |0.019231266|0.019775736|0.018993051|
| High-effect |0.017656344|0.018167776|0.017328189|
| Older renderer |0.014859464|0.014996537|0.014350323|
| Fresh September7 |0.016249614|0.015973574|0.015375280|
| Renderer-state September8 |0.020117967|0.020677478|0.020836952|
| New19 September8 |0.029031637|0.027686544|0.027927639|

Pretrained features improve five cohorts versus common start but beat the matched random encoder on only the four earlier cohorts. The renderer-state cohort regresses from both references; the new19 improve from start but lose to random control. Temporal error also trades off: versus random control it improves on high-effect/older renderer/renderer-state and worsens on prior/freshSeptember7/new19. No promotion or0.011 claim is warranted.

Independent endpoint replay and the registered training-subset branch-response probe follow before any extension decision. The comparison supports further examination of pretrained representation, not blind continuation or an inference that all renderer/state evidence is unnecessary.

## Independent replay completed

The saved pretrained step400 checkpoint independently reproduced all six full validation-cohort metrics exactly. Checkpoint SHA256: `f5a339770261cd3c35187d10708a3ec4d01568c9580f78525269b980887bb040`. All175 encoder tensors remain exactly equal to the official pretrained weights; the learned projection has nonzero weight norm0.392899. The encoder stayed frozen as intended.

The replay also rendered48 fixed input/student/teacher/difference comparisons, with signed RGB/luminance diagnostics, under `C:/OpenNR/Training/semantic_pretrained_arm400_20260908/independent_replay/index.html`. In the new outdoor cohort, local brightening, shadow treatment and ground/stone color still visibly differ from the teacher. Exact replay verifies the reported endpoint, not teacher resemblance or runtime acceptance.

## Registered training-subset probe completed

All12 selected training sequences were evaluated in four modes, totaling1,536 eye frames per mode. No validation or test sequences entered this probe. The pretrained endpoint improves MAE on each subset against both common start and random control. Disabling its semantic projection worsens all six subset MAEs, confirming that the learned branch contributes to fitting rather than remaining inert.

| Training subset | Common start | Random | Pretrained | Pretrained branch disabled |
|---|---:|---:|---:|---:|
| Prior |0.022828921|0.022909927|0.022332501|0.022480053|
| High-effect |0.016410471|0.016661190|0.015558997|0.016509157|
| Older renderer |0.016268194|0.017027575|0.016127282|0.016471245|
| Fresh September7 |0.028570566|0.027527112|0.026181253|0.028944439|
| Renderer-state |0.018483222|0.018751872|0.018035443|0.018527749|
| New19 |0.021801474|0.021843213|0.020549135|0.021670022|

Temporal error still trades off, especially on prior/fresh/new19. This bounded fit probe does not establish generalization. Artifact: `C:/OpenNR/Training/semantic_training_fit_probe_20260908/result.json`.

## Next registered experiment: projection-only adaptation

Freeze the complete verified warm U-Net, causal parent and encoder. Train only the24,640-parameter semantic projection, contrasting random and pretrained encoders under the same recipe and deterministic sample schedule. Keep LR1e-4, seed367, six cohort probabilities and objective unchanged. Run1,200 updates with full validation at0/400/800/1200, registering this duration before either arm begins. Compare every checkpoint with common start and the matched control; do not relax temporal, visual/color or0.011 acceptance. This tests whether useful conditioning can be learned while avoiding whole-U-Net drift. It does not assume freezing will fix the validation regression.

Tool: `tools/train_semantic_projection_ablation.py`. Outputs: `C:/OpenNR/Training/semantic_projection_random1200_20260908` and `C:/OpenNR/Training/semantic_projection_pretrained1200_20260908`. This is a fresh experiment from the verified warm head, not an optimizer resume of the earlier400-step endpoints.

The projection-only control's full six-cohort step0 MAE and temporal scores exactly match the earlier common baseline. An independent tensor check is prepared in `tools/verify_semantic_projection_freeze.py` to verify that all warm U-Net and encoder tensors remain unchanged after training.

The random projection-only control completed1,200 updates in817.78 seconds at4.40GiB peak allocated memory. Its selected checkpoint remains step0. Both400 and1,200 tensor audits confirm all206 warm U-Net tensors and175 encoder tensors are unchanged. Endpoint MAEs in cohort order are0.019473961/0.017668071/0.014781554/0.016170734/0.020090584/0.026193330: four improve from common start, while prior and high-effect regress. The pretrained projection arm has begun training after exact six-cohort initial replay. A [joint-parent experiment](JOINT_PARENT_SEMANTIC_PREPARATION_20260908.md) is prepared as a possible next alternative, with no training result yet.

## Projection-only comparison completed: useful MAE gains, temporal regressions

The pretrained arm completed 1,200 updates in 810.30 seconds. All registered sample hashes and draw counts match its control. No checkpoint passed the six-cohort retention gate; the selected fallback remains step 0. The endpoint SHA256 is `a18f0753abad53ed6e2c946bb05726c0890fe3a71749d359a47861bd09563d2e`. Its tensor audit confirms exact preservation of all 206 warm U-Net tensors and 175 encoder tensors.

| Ordinary cohort | Common start MAE | Random control | Pretrained | Pretrained temporal error minus start |
|---|---:|---:|---:|---:|
| Prior |0.019231266|0.019473961|0.018890919|+0.000051097|
| High-effect |0.017656344|0.017668071|0.016756784|+0.000076191|
| Older renderer |0.014859464|0.014781554|0.014273042|+0.000062354|
| Fresh September7 |0.016249614|0.016170734|0.015905044|+0.000049465|
| Renderer-state |0.020117967|0.020090584|0.020504198|+0.000009499|
| New19 |0.029031637|0.026193330|0.024892730|+0.000069017|

Pretrained conditioning improves five MAEs against both references, including a 14.3% newest-cohort gain from start. However, renderer-state MAE regresses and temporal-delta error worsens on all six cohorts against both references. This is useful representation evidence, not temporal stability or promotion. The registered queue is independently replaying/rendering the endpoint before launching the joint-parent alternative. Exact numerical comparison: `C:/OpenNR/Training/semantic_projection_pretrained1200_20260908/endpoint_comparison.json`.

The full endpoint replay subsequently completed with exact six-cohort scores. The joint-parent alternative has started; results are pending.

## Registered feature-history diagnostic

The six temporal regressions motivate a separate bounded probe of the stateless semantic features. After the current GPU queue, evaluate the same first/last training sequences per cohort, both eyes, all 64 frames. Compare the bare projection endpoint, a zero-history identity wrapper, and fixed 25% motion-compensated semantic-feature history. No fitting, validation selection, or test access is part of this probe.

History contains only the student's own frozen-encoder features and source-RGB thumbnails. It uses the existing exact native-MV sign/scale convention, rejects invalid MV support and out-of-bounds sampling, and rejects thumbnail RGB disagreements above a fixed 0.08 threshold. This is a simple rejection heuristic, not verified complete occlusion handling or recovered NVIDIA state. First-frame reset uses current features exactly. The zero-history wrapper must reproduce bare-model scores within 1e-7 before interpreting the intervention.

Tools: `tools/semantic_feature_history.py` and `tools/probe_semantic_feature_history.py`. CPU checks pass exact zero/reset identity, valid blending, invalid-MV and photometric rejection, positive one-feature-pixel motion and border rejection. GPU effects remain unmeasured. This diagnostic addresses stability of the newly useful representation; it does not presume the 0.011 or color target is solved.

The GPU probe subsequently completed on all 12 selected training sequences. Zero-history scores exactly reproduce the bare endpoint; first-frame errors remain identical under 25% history. MAE decreases on all six subsets by approximately 0.0000005–0.0000232, and temporal error decreases by 0.0000147–0.0000555. These are small training-subset effects, not validated temporal acceptance or a reason to promote the projection endpoint. Results: `C:/OpenNR/Training/semantic_feature_history_probe_20260908/result.json`. The larger next experiment remains [paired joint-parent replication](SEMANTIC_PARENT_REPLICATION_20260908.md).

## Fixed-sample tone error remains material

The48-frame pretrained replay's pixel-weighted color summary is saved as `independent_replay/color_summary.json`. On every cohort's fixed samples, teacher-brightening regions remain underbright and teacher-darkening regions remain overbright on average. In renderer-state samples, the latter signed code-value luminance error is+0.059115 (RGB MAE0.060630 within that mask), despite whole-sample RGB MAE0.020143. In fresh-session samples, teacher-brightening regions have signed error-0.042612. These masks are teacher-defined diagnostics using the fixed0.02 effect threshold; they are not inference inputs, skin labels, physical luminance, or estimates of whole-corpus color quality.
