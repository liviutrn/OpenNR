# Training-window batching experiment

The active semantic model's parent owns all recurrent state. Its U-Net/DINO head is stateless and its corrected pixels are not fed back to the parent. Therefore the parent's eight causal steps can remain sequential while the six supervised head evaluations are batched. The last burn-in head output is still evaluated separately for the temporal-error objective. No frame, target or temporal-loss term is removed.

## CPU graph verification

`tools/check_semantic_window_batching.py` compares the actual full model in CPU FP32 at128×128, with eight frames, two burn-in frames and a nonzero semantic projection. Both frozen-parent and joint-parent modes produce exactly equal losses. Relative gradient L2 differences are3.04e-7 and9.97e-8 respectively, with unchanged gradient ownership across208/512 tensors. Record: `out/semantic_window_batching_cpu.json`. This supports mathematical equivalence for the tested graph; it is not a CUDA timing or BF16 result.

The implementation explicitly requires the known stateless semantic-head graph. It must not silently batch a future stateful head. Existing active trainers and checkpoint sources are unchanged.

## Registered GPU check

After the active training/replay queue, `tools/benchmark_semantic_window_batching.py` will use the verified seed367 joint checkpoint and one fixed eight-frame window from the first prior training sequence, left eye, indices24–31. No validation or test examples are used. Measure both frozen and trainable parent modes.

First compare BF16 loss and gradients before any optimizer update. The numerical screening thresholds are absolute loss difference <=1e-5 and relative gradient L2 difference <=0.01; passing these permits consideration, not a claim of bit-exact training. Then measure complete forward/backward/clipping/AdamW training-window time in sequential/batched/batched/sequential blocks, with checkpoint weights and optimizer reset before each block, two warmups and five measured windows per block. Record individual times, median speedup and peak allocated memory.

These are training throughput measurements, not per-eye inference, stereo, runtime integration or VR-budget acceptance. Batching will not be introduced into the ongoing paired run. A future use must record the floating-point execution change and apply it consistently to both arms.
# Completed GPU screen

On RTX5070Ti, the ABBA benchmark passed the predefined BF16 numerical screen for both modes. Frozen-parent median full update time fell from345.46ms to197.46ms (1.750x); joint-parent from525.75ms to379.66ms (1.385x). Joint peak allocation fell from9.923GiB to9.414GiB. Gradient relative-L2 differences were0.0018315 frozen and0.0009388 joint; loss absolute difference was1.30e-8. This is approximate numerical agreement, not a bit-identical training trajectory. It measures one training window and excludes validation/data-loading overhead; it is not inference or VR timing. Evidence: `C:/OpenNR/Training/semantic_window_batching_benchmark_20260908/result.json`.

The paired update1200-to4000 continuation retains sequential execution to isolate duration. Batching remains a measured option for a separately recorded experiment.
