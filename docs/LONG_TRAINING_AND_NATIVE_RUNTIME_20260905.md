# Longer training and native GPU runtime — 2026-09-05

The small student is feasible as a faster GPU backend: four matched offline stereo replays now run through actual D3D12 shared textures, CUDA preprocessing, TensorRT and graphics output. This is a measured offline speed milestone. It is not a drop-in NVIDIA DLL, a live Skyrim replacement, or teacher-equivalent visual quality.

## Delivered implementation

- `tools/train_long_student.py`: 30,000 additional steps, deterministic epoch sampling, checkpointed raw and EMA weights, optimizer and RNG state, separate best MAE and best feature selection, finite loss/gradient checks and resumable schedule validation.
- `native/teacher_bench`: isolated D3D12 Feature 18 benchmark reusing the existing unmodified Runtime.cpp and authenticated NVIDIA 310.8.0.0 DLL, plus a shared D3D12/CUDA texture and fence bridge. No MGO installation files were changed.
- `tools/native_preprocess.cu` and `.py`: GPU color conversion, native-guide validity masks and resampling, whole-eye context and RGBA output packing. No CPU image round-trip during the measured student pipeline.
- `tools/benchmark_d3d12_student.py`: actual left/right graphics interop with byte-exact input and output validation. `prepare_teacher_bench.py` selects the first recorded stereo pair from each validation sequence. `analyze_native_replay.py` checks nontrivial teacher output, warm timings and visual evidence.
- `tools/tensorrt_student.py`: selected checkpoint export with left/right FP32-reference checks; failed conversion tolerances now fail the command instead of merely recording a false flag.

## Training and selection

The continuation completed 30,000 additional steps in 21.31 minutes. Batch 4 over 7,712 cached training patches is 15.56 additional epoch equivalents. The preceding 6,000-step run was approximately 3.11 epochs. These are small models learning from preprocessed 512-pixel patches, so useful experiments need not take hours. Running longer is not itself evidence of improvement.

Initialization uses the prior fast model's EMA weights with a new optimizer because the older checkpoint had no optimizer state. The new checkpoints support continuation with saved optimizer/RNG state, but CUDA algorithm nondeterminism prevents a promise of bit-exact reruns. Original captures, crash exclusions, cache and sequence splits are unchanged. No new test-set tuning or evaluation occurred.

Validation covers 352 patches, 88 eyes, 44 stereo frames and four sequences:

| Candidate | RGB MAE, lower | PSNR dB, higher | Feature distance, lower |
|---|---:|---:|---:|
| fast/best | 0.024622 | 29.076 | 0.121142 |
| fast_continuation/best_mae | 0.023735 | 29.296 | 0.113941 |
| fast_continuation/best_feature | 0.025141 | 28.696 | 0.103794 |

The best MAE checkpoint is the default delivery. The best feature checkpoint is preserved separately: its improved feature score trades off pixel accuracy. The frozen feature network is also part of the training objective, so this score is not independent visual acceptance. Faces, hair, local shadows and material detail remain visibly different from the teacher. Longer training did not solve these gaps.

## Matched native stereo replay

RTX 5070 Ti, 2496×2688 per eye, authentic 1664×1792 depth/motion guides, 100% model resolution, one Feature 18 pass, recorded tuning 2/2/2, skin -1, auto mask enabled, UI correction disabled. Each row has 20 warm-up pairs and 100 measured pairs. Teacher and student execute sequentially after training/export has stopped; the final series runs student before teacher. The earlier baseline series ran teacher before student. Contended smoke timings are excluded.

| Validation sequence index | NVIDIA stereo wall ms | NVIDIA stereo GPU ms | Student stereo wall ms | Student wall p95 ms | Wall speed ratio |
|---|---:|---:|---:|---:|---:|
| 0 | 24.184 | 23.316 | 8.042 | 8.076 | 3.01x |
| 1 | 24.384 | 23.447 | 8.040 | 8.082 | 3.03x |
| 2 | 24.423 | 23.582 | 8.035 | 8.084 | 3.04x |
| 3 | 24.157 | 23.337 | 8.040 | 8.079 | 3.00x |

Wall timing is synchronized completion of each stereo pair. The student includes GPU texture/buffer copies, RGB/guide/context preparation, TensorRT, output packing and shared-fence handoff back to D3D12. The teacher includes its native command submission and synchronized completion. CUDA event scope and NVIDIA GPU timestamp scope differ, so the headline ratio uses wall-to-wall. Both exclude initial disk upload, Skyrim rendering and compositor work. Warm figures do not include engine creation or first-frame latency.

Each of four pairs has exact-byte checks for both eyes' color/depth/motion input and both returned graphics outputs. Teacher output is neither empty nor pass-through, and native replay is visibly consistent with the captured teacher. The replay repeats a static pair with recorded motion, not a valid moving sequence; native and captured teacher histories differ. These tests establish a native-resource execution path and speed feasibility, not temporal quality or a scene-distribution benchmark.

The chosen TensorRT engine uses FP16 tactics, FP32 reductions where preferred and FP32 I/O. It is **not NVFP4**. Against PyTorch FP32, the mean absolute conversion differences were 0.00008111 (left) and 0.00007376 (right); both passed the pre-existing mean ≤0.001 and maximum ≤0.05 thresholds. GPU preprocessing checks separately passed: RGB max error 5.96e-8, guides 4.29e-5, context 0.00416, and downstream prediction mean difference 0.0000318 on the reference eye. Context is approximately, not bit-exactly, equivalent to cached PIL BOX/FP16 preparation.

## Delivery and next engineering step

Selected weights: `out/student_long_20260905/fast_continuation/best_mae.pt`.

Selected engine: `out/student_long_20260905/runtime_best_mae/student_fp16.engine`.

Alternative appearance candidate: `out/student_long_20260905/fast_continuation/best_feature.pt`.

Hashes and full measurements: `out/student_long_20260905/delivery.json`. Visual comparison: `out/student_long_20260905/gallery.html`. Native replay evidence: `out/native_final_20260905/sequence_0/comparison` through `sequence_3/comparison`.

The speed stopping condition is satisfied for this explicitly scoped offline native-resource benchmark; visual-equivalence and live-game acceptance remain open. The model cannot replace `nvngx_dlssnr.dll` by renaming a file. Integration needs an explicit student backend at the owned renderer boundary, with stable shared-resource lifetime, adapter identity checks, per-eye routing, history/reset behavior, resizing and device-loss fallback. The current bridge owns its own D3D12 device and is exercised from Python; it is not the finished C++ in-game backend.

For quality, the useful next experiment is more scene-diverse supervision and a larger receptive field or carefully validated face/detail objective. The data is spatial-only; do not invent contiguous temporal history from sparse captures. New independent acceptance sequences are needed before trusting further validation-driven gains. NVFP4 is a later quantization experiment with calibration and image-error checks, not a switch that makes this FP16 engine four-bit. An approximately 8 ms stereo effect also consumes much of an 11.11 ms 90 Hz frame budget before game rendering, so offline speed superiority does not guarantee acceptable VR frame time.

## Context quality candidate and explicit FP8 follow-up

The later context-v3 face/VGG continuation is documented in `docs/QUALITY_PHASE_20260905.md`. Its balanced best-MAE export has 1,988,496 parameters and an exact FP16 TensorRT build, but the actual D3D12 path measures 25.39 ms stereo because the larger context model is materially slower than the earlier fast student. Its best-feature A/B engine measures 25.41 ms stereo. Both pass left/right numerical and byte-level checks; neither is live Skyrim accepted.

An explicit FP8 Q/DQ calibration experiment was added with `tools/quantize_fp8.py` and `tools/build_trt_onnx.py`. Full Conv+MatMul FP8 engines built from 16- and 64-eye training-only calibration sets but failed parity and were slower. A MatMul-only FP8 control passes parity and D3D12 byte checks but measures 25.22 ms stereo, within timing noise of FP16. Keep FP16 as the fallback and treat all FP8 artifacts as experimental until a future model or graph structure produces a measured speed win without quality loss.

The dynamic native loader now supports four-pixel-aligned crops larger than 512
through `--patch-size`, with an explicit batch size and the same audited guide,
face-mask and worker contracts. A controlled 1024-pixel continuation from the
balanced face/VGG/face-loss checkpoint was stopped at step 1,850 after validation
at steps 500, 1,000 and 1,500 remained worse than its step-0 initialization:
native MAE 0.0236385, 0.0235819 and 0.0238675 versus 0.0234398, with the
training feature distance also worsening. The run and last checkpoint remain
under `out/quality_phase_20260905/context_face_vgg_face_loss_1024`; the 512-pixel
candidate remains selected. This rejects larger crops as an unvalidated quality
improvement for the current architecture and data.
