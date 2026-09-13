# OpenNR Student v1 — trained September 4, 2026

The selected guided spatial student is trained and evaluated. On all 486 held-out native eyes (243 stereo frames), its error against the captured Feature 18 teacher is 26.70% lower than unmodified input. It is an offline research checkpoint; the measured eager-PyTorch runtime below determines the remaining VR work. Teacher agreement does not prove perceptual superiority or headset comfort.

## Delivered model

- Inference weights: `out/student_v1_20260904/OpenNR_Student_v1.pt`.
- SHA-256: `15164124092d673481321d6b945e9c7bac5f257b149479c4b86b7f58867638d9`.
- Architecture: 523,345 parameters, width 40, two gated blocks per encoder/decoder stage and three at the bottleneck; multiscale quarter-resolution compute, whole-eye context conditioning, native RGB affine/detail skip, and subpixel residual reconstruction.
- Inputs: native RGB in captured UNORM/255 representation; aligned native depth and two bounded native engine-MV features; two guide validity masks; a 96x96 whole-eye RGB/guide context.
- Output: one RGB eye at input resolution. Use once per eye. No recurrent state, optical-flow replacement, binocular fusion, or inference of missed temporal frames.
- Independently written architecture informed by multiscale gated restoration in [NAFNet](https://arxiv.org/abs/2204.04676) and low-resolution learned image transforms in [HDRNet](https://arxiv.org/abs/1707.02880). No external model weights or proprietary binaries are included.

## Data and training

The cache contains 1,538 audited eye pairs: 964 train, 88 validation and 486 test. Training combines 204 new stereo frames with 278 audited supplemental native-resolution stereo frames. Validation has 44 stereo frames, and test has 243. Each training eye has four fixed and four seeded random native 512x512 patches: 7,712 training patches. Each held-out eye has four fixed patches: 352 validation and 1,944 test. RGB targets stay at native pixel scale; guides are aligned to 128x128 compute grids. Full-frame evaluation additionally covers every pixel of all held-out eyes, outside those patches.

Supplemental data has the same teacher settings and dimensions. Two lower-resolution supplemental frames, uncommitted/orphan artifacts, failed records, guard-band sequences and duplicate records are excluded by the preparation policy. Raw captures are unchanged. The crash tail's committed frames remain usable; its orphan final frame was not reconstructed into training. Source manifests and cache row SHA-256 identities are stored in the checkpoint and `run.json`.

Both eyes and all patches stay with their sequence. The newest test process was frozen before model selection. Supplemental sessions were added to training only. Scene/location/character independence is not established; correlated scenes may occur across sessions, and patch counts are not counts of independent scenes. These are spatial samples with large host-frame gaps, insufficient for validated temporal training.

Loss is Charbonnier RGB error plus multiscale L1 and edge-gradient L1, with identical all-pixel evaluation for model and identity. Black color pixels are included, without target-dependent exclusions. Guide invalidity is explicitly masked. Motion beyond native ±0.25 or nonfinite values is invalidated; valid per-eye X/Y scales map to color pixels, then values are clipped to ±128 pixels and normalized. This is a spatial feature convention, not calibrated reprojection.

Training uses AdamW, cosine learning rate, bf16 mixed precision, finite loss/gradient checks, gradient clipping, and EMA checkpoint selection every 200 steps. Horizontal augmentation flips images, guides and context and negates MV X. Controlled 1,600-step width-40 guided/RGB runs were compared with a 1,000-step width-24 guided alternative. The validation winner was refined to step 4000; final validation MAE is 0.025977. Batch size is 8. Resume preserves weights, EMA and optimizer; the data RNG restarts deterministically rather than reproducing an uninterrupted run bit-for-bit. Test results were not used to choose or refine a checkpoint.

## Frozen test evidence

MAE is normalized RGB error; smaller is better. PSNR is computed from aggregate RGB MSE; larger is better. These values are not directly comparable with earlier POC scores that used different crops, masks and guides.

| Checkpoint | Patch MAE | Patch PSNR dB | MAE reduction vs input |
|---|---:|---:|---:|
| guided_quality | 0.026752 | 28.30 | 31.66% |
| rgb_control | 0.026907 | 28.03 | 31.27% |
| guided_fast | 0.027812 | 28.00 | 28.96% |
| selected | 0.026615 | 28.30 | 32.01% |

Unmodified patch input: MAE 0.039148, PSNR 25.21 dB. Guide gains are stronger on validation than test; the controlled guided model's test gain over RGB is small, so guide generalization is not established from the validation difference alone.

Full native test: **MAE 0.026312, PSNR 28.60 dB**, compared with input MAE 0.035898, PSNR 25.61 dB. Full-frame improvement is **26.70%**. Left/right MAE: 0.026950 / 0.025673. Separate per-eye metrics do not measure binocular consistency. Per-sequence and per-frame evidence is in `evaluation.json` and `full_test_frames.json`.

7 of 486 eyes have worse MAE than unmodified input. The worst observed regression is sequence `seq-1788572375117-7`, frame 8, left eye: MAE 0.039865 versus input 0.036639. Aggregate gains therefore do not guarantee improvements for every frame.

## Runtime evidence

Measured on NVIDIA GeForce RTX 5070 Ti, torch 2.7.1+cu128, at 2496x2688 per eye, bf16 autocast:

- Warm single eye: 29.47 ms median, 29.82 ms p95.
- Actual sequential left+right: 58.66 ms median.
- Actual batch-of-two left+right: 64.36 ms median.
- Smaller width-24 candidate: 18.45 ms per eye and 36.60 ms sequential stereo. It also exceeds the VR frame budget.
- First single-eye forward in this fresh benchmark: 401.54 ms.
- Model load plus CUDA initialization: 100.0 ms.
- Peak allocated GPU memory including batched benchmark: 1.82 GiB.

These CUDA timings include native reconstruction with GPU-resident inputs, but exclude engine interop, CPU disk loading, transfer and compositor. Offline stereo raw-data reading/preparation/upload took 411.5 ms and is not a proposed live runtime. An entire 90 Hz frame is 11.11 ms; the model must fit only the remaining part of that budget. No MGO installation or live headset acceptance is claimed.

## Reproduce and use

Use `E:/OpenNR-VR-Poc-Venv/Scripts/python.exe` from the project root. Derived cache: `C:/OpenNR/TrainingCache/student_v1` (source captures must remain available for native inference).

```powershell
python tools/test_student_v1.py --cache C:/OpenNR/TrainingCache/student_v1
python tools/test_master_dataset.py
python tools/infer_student.py --checkpoint out/student_v1_20260904/OpenNR_Student_v1.pt --cache C:/OpenNR/TrainingCache/student_v1 --row 0 --output out/student_v1_20260904/example.png
# Training reproduction must use a NEW output directory, preserving this frozen run:
python tools/run_student_experiments.py --cache C:/OpenNR/TrainingCache/student_v1 --output out/student_v1_reproduction
```

The inference checkpoint reloads through `tools/opennr_student.py`; full optimizer checkpoints, logs, and validation histories remain in experiment folders. Architecture identity initialization, arbitrary dimensions, finite gradients, cache RGB equality, safe guide bounds, square and rectangular guide geometry were checked. Full native inference succeeded for every test eye.

## Next work, in order

Visual inspection of the first, middle and last held-out stereo examples shows learned sky/tone changes and retained input geometry. The final close-up still lacks the teacher's stronger face/hair transformation. Aggregate MAE gains should not be read as successful imitation of every semantic detail.

1. Review the delivered full-eye and detail comparisons for faces, foliage, text, shadows, and teacher differences. Accept or reject the desired appearance before changing the objective.
2. Export and optimize a fixed-shape GPU runtime, profile the native reconstruction and normalization kernels, and benchmark the compact checkpoint on the same hardware. ONNX, TensorRT and Triton are not installed in the training environment; this run did not add an untested runtime dependency. Use the smaller candidate as a measured fallback, with a separate validation-selected optimization experiment. Preserve this frozen test result.
3. Integrate only after a concrete remaining-frame-time target is met; then use isolated MGO stereo A/B and crash/latency checks. Current PyTorch timing is not runtime acceptance.
4. Collect contiguous calibrated sequences for temporal stability training: known reset boundaries, native MV direction/scale, exposure/jitter and camera metadata, with substantially fewer capture drops. The existing data is useful spatial pretraining; more of the same sampled cadence will not solve temporal supervision.

The evidence supports a trained spatial distillation baseline, not a claim that the most capable possible architecture has been exhausted or that the captured teacher can be fully reproduced from these inputs.
