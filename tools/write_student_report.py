"""Render the model card and a local visual gallery from completed evidence."""
import json,hashlib,html
from pathlib import Path

root=Path(__file__).resolve().parents[1];out=root/'out/student_v1_20260904'
e=json.loads((out/'evaluation.json').read_text());b=json.loads((out/'benchmark.json').read_text());p=json.loads((out/'pipeline_status.json').read_text());run=json.loads((out/'refined/run.json').read_text())
table='\n'.join(f'| {k} | {v["mae"]:.6f} | {v["psnr"]:.2f} | {v["improvement_pct"]:.2f}% |' for k,v in e['patch_test'].items())
f=e['full_test'];s=e['patch_test']['selected']
fast=json.loads((out/'benchmark_fast.json').read_text())
frames=json.loads((out/'full_test_frames.json').read_text());regressions=sum(r['mae']>r['identity_mae'] for r in frames)
card=f'''# OpenNR Student v1 — trained September 4, 2026

The selected guided spatial student is trained and evaluated. On all {f['eyes']} held-out native eyes ({f['stereo_frames']} stereo frames), its error against the captured Feature 18 teacher is {f['improvement_pct']:.2f}% lower than unmodified input. It is an offline research checkpoint; the measured eager-PyTorch runtime below determines the remaining VR work. Teacher agreement does not prove perceptual superiority or headset comfort.

## Delivered model

- Inference weights: `out/student_v1_20260904/OpenNR_Student_v1.pt`.
- SHA-256: `{e['checkpoint_sha256']}`.
- Architecture: {s['parameters']:,} parameters, width 40, two gated blocks per encoder/decoder stage and three at the bottleneck; multiscale quarter-resolution compute, whole-eye context conditioning, native RGB affine/detail skip, and subpixel residual reconstruction.
- Inputs: native RGB in captured UNORM/255 representation; aligned native depth and two bounded native engine-MV features; two guide validity masks; a 96x96 whole-eye RGB/guide context.
- Output: one RGB eye at input resolution. Use once per eye. No recurrent state, optical-flow replacement, binocular fusion, or inference of missed temporal frames.
- Independently written architecture informed by multiscale gated restoration in [NAFNet](https://arxiv.org/abs/2204.04676) and low-resolution learned image transforms in [HDRNet](https://arxiv.org/abs/1707.02880). No external model weights or proprietary binaries are included.

## Data and training

The cache contains 1,538 audited eye pairs: 964 train, 88 validation and 486 test. Training combines 204 new stereo frames with 278 audited supplemental native-resolution stereo frames. Validation has 44 stereo frames, and test has 243. Each training eye has four fixed and four seeded random native 512x512 patches: 7,712 training patches. Each held-out eye has four fixed patches: 352 validation and 1,944 test. RGB targets stay at native pixel scale; guides are aligned to 128x128 compute grids. Full-frame evaluation additionally covers every pixel of all held-out eyes, outside those patches.

Supplemental data has the same teacher settings and dimensions. Two lower-resolution supplemental frames, uncommitted/orphan artifacts, failed records, guard-band sequences and duplicate records are excluded by the preparation policy. Raw captures are unchanged. The crash tail's committed frames remain usable; its orphan final frame was not reconstructed into training. Source manifests and cache row SHA-256 identities are stored in the checkpoint and `run.json`.

Both eyes and all patches stay with their sequence. The newest test process was frozen before model selection. Supplemental sessions were added to training only. Scene/location/character independence is not established; correlated scenes may occur across sessions, and patch counts are not counts of independent scenes. These are spatial samples with large host-frame gaps, insufficient for validated temporal training.

Loss is Charbonnier RGB error plus multiscale L1 and edge-gradient L1, with identical all-pixel evaluation for model and identity. Black color pixels are included, without target-dependent exclusions. Guide invalidity is explicitly masked. Motion beyond native ±0.25 or nonfinite values is invalidated; valid per-eye X/Y scales map to color pixels, then values are clipped to ±128 pixels and normalized. This is a spatial feature convention, not calibrated reprojection.

Training uses AdamW, cosine learning rate, bf16 mixed precision, finite loss/gradient checks, gradient clipping, and EMA checkpoint selection every 200 steps. Horizontal augmentation flips images, guides and context and negates MV X. Controlled 1,600-step width-40 guided/RGB runs were compared with a 1,000-step width-24 guided alternative. The validation winner was refined to step {s['step']}; final validation MAE is {p['best_validation_mae']:.6f}. Batch size is 8. Resume preserves weights, EMA and optimizer; the data RNG restarts deterministically rather than reproducing an uninterrupted run bit-for-bit. Test results were not used to choose or refine a checkpoint.

## Frozen test evidence

MAE is normalized RGB error; smaller is better. PSNR is computed from aggregate RGB MSE; larger is better. These values are not directly comparable with earlier POC scores that used different crops, masks and guides.

| Checkpoint | Patch MAE | Patch PSNR dB | MAE reduction vs input |
|---|---:|---:|---:|
{table}

Unmodified patch input: MAE {s['identity_mae']:.6f}, PSNR {s['identity_psnr']:.2f} dB. Guide gains are stronger on validation than test; the controlled guided model's test gain over RGB is small, so guide generalization is not established from the validation difference alone.

Full native test: **MAE {f['mae']:.6f}, PSNR {f['psnr']:.2f} dB**, compared with input MAE {f['identity_mae']:.6f}, PSNR {f['identity_psnr']:.2f} dB. Full-frame improvement is **{f['improvement_pct']:.2f}%**. Left/right MAE: {f['eye_mae']['0']:.6f} / {f['eye_mae']['1']:.6f}. Separate per-eye metrics do not measure binocular consistency. Per-sequence and per-frame evidence is in `evaluation.json` and `full_test_frames.json`.

{regressions} of {f['eyes']} eyes have worse MAE than unmodified input. The worst observed regression is sequence `seq-1788572375117-7`, frame 8, left eye: MAE 0.039865 versus input 0.036639. Aggregate gains therefore do not guarantee improvements for every frame.

## Runtime evidence

Measured on {b['gpu']}, torch {b['torch']}, at 2496x2688 per eye, bf16 autocast:

- Warm single eye: {b['per_eye']['warm_median_ms']:.2f} ms median, {b['per_eye']['warm_p95_ms']:.2f} ms p95.
- Actual sequential left+right: {b['sequential_stereo']['warm_median_ms']:.2f} ms median.
- Actual batch-of-two left+right: {b['batched_stereo']['warm_median_ms']:.2f} ms median.
- Smaller width-24 candidate: {fast['per_eye']['warm_median_ms']:.2f} ms per eye and {fast['sequential_stereo']['warm_median_ms']:.2f} ms sequential stereo. It also exceeds the VR frame budget.
- First single-eye forward in this fresh benchmark: {b['per_eye']['first_ms']:.2f} ms.
- Model load plus CUDA initialization: {b['model_load_with_cuda_init_ms']:.1f} ms.
- Peak allocated GPU memory including batched benchmark: {b['peak_allocated_gib']:.2f} GiB.

These CUDA timings include native reconstruction with GPU-resident inputs, but exclude engine interop, CPU disk loading, transfer and compositor. Offline stereo raw-data reading/preparation/upload took {b['offline_stereo_read_prepare_upload_ms']:.1f} ms and is not a proposed live runtime. An entire 90 Hz frame is 11.11 ms; the model must fit only the remaining part of that budget. No MGO installation or live headset acceptance is claimed.

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
'''
(root/'docs/STUDENT_V1_RESULT_20260904.md').write_text(card,encoding='utf-8')
images=sorted((out/'previews').glob('*_comparison.jpg'))
gallery='<!doctype html><meta charset="utf-8"><title>OpenNR Student v1 comparisons</title><style>body{background:#14181e;color:#eee;font:16px system-ui;margin:24px}img{width:100%;max-width:1440px}figure{margin:24px 0}a{color:#83bbff}</style><h1>OpenNR Student v1 — held-out native eyes</h1><p>Input / trained student / Feature 18 teacher. Display previews are resized; linked predictions retain 2496 × 2688 native pixels. Examples are the first, middle and last held-out stereo frames, chosen independently of scores.</p>'
for path in images:
    tag=path.name.replace('_comparison.jpg','');gallery+=f'<figure><figcaption>{html.escape(tag)} · <a href="previews/{tag}_prediction.png">Native prediction</a></figcaption><img src="previews/{path.name}"></figure>'
(out/'gallery.html').write_text(gallery,encoding='utf-8')
sources={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in (root/'tools').glob('*student*.py')}
(out/'source_hashes.json').write_text(json.dumps(sources,indent=2))
print('Wrote model card, gallery and source hashes')
