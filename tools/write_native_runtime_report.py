"""Build a reproducible report from completed long training and native replay artifacts."""
import hashlib
import html
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / 'out/student_long_20260905'
quality = json.loads((out / 'comparison/validation.json').read_text())
run = json.loads((out / 'fast_continuation/run.json').read_text())
status = json.loads((out / 'fast_continuation/status.json').read_text())
assert status['state'] == 'completed'
runtime = json.loads((out / 'runtime_best_mae/runtime_result.json').read_text())
assert runtime['numerical_check']['passed'] and runtime['right_eye_numerical_check']['passed']
replays = [json.loads((root / f'out/native_final_20260905/sequence_{i}/comparison/comparison.json').read_text()) for i in range(4)]
for r in replays:
    assert r['student']['state'] == 'passed' and not r['student']['contended_smoke']
    assert r['student']['output_exact_bytes'] and all(c['exact_bytes'] for c in r['student']['input_copy_checks'])
quality_rows = '\n'.join(f'| {Path(p).parent.name}/{Path(p).stem} | {m["mae"]:.6f} | {m["psnr"]:.3f} | {m["feature_distance"]:.6f} |' for p, m in quality.items())
speed_rows = '\n'.join(f'| {i} | {r["teacher"]["pair_wall_ms"]["median"]:.3f} | {r["teacher"]["pair_gpu_ms"]["median"]:.3f} | {r["student"]["wall_median_ms"]:.3f} | {r["student"]["wall_p95_ms"]:.3f} | {r["wall_speedup"]:.2f}x |' for i, r in enumerate(replays))
artifacts = {}
for rel in ('fast_continuation/best_mae.pt', 'fast_continuation/best_feature.pt', 'fast_continuation/last.pt', 'runtime_best_mae/student_fp16.engine'):
    path = out / rel
    artifacts[rel] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
(out / 'delivery.json').write_text(json.dumps({'status': status, 'run': run, 'artifacts': artifacts, 'replays': replays}, indent=2))
body = f'''# Longer training and native GPU runtime — 2026-09-05

The small student is feasible as a faster GPU backend: four matched offline stereo replays now run through actual D3D12 shared textures, CUDA preprocessing, TensorRT and graphics output. This is a measured offline speed milestone. It is not a drop-in NVIDIA DLL, a live Skyrim replacement, or teacher-equivalent visual quality.

## Delivered implementation

- `tools/train_long_student.py`: 30,000 additional steps, deterministic epoch sampling, checkpointed raw and EMA weights, optimizer and RNG state, separate best MAE and best feature selection, finite loss/gradient checks and resumable schedule validation.
- `native/teacher_bench`: isolated D3D12 Feature 18 benchmark reusing the existing unmodified Runtime.cpp and authenticated NVIDIA 310.8.0.0 DLL, plus a shared D3D12/CUDA texture and fence bridge. No MGO installation files were changed.
- `tools/native_preprocess.cu` and `.py`: GPU color conversion, native-guide validity masks and resampling, whole-eye context and RGBA output packing. No CPU image round-trip during the measured student pipeline.
- `tools/benchmark_d3d12_student.py`: actual left/right graphics interop with byte-exact input and output validation. `prepare_teacher_bench.py` selects the first recorded stereo pair from each validation sequence. `analyze_native_replay.py` checks nontrivial teacher output, warm timings and visual evidence.
- `tools/tensorrt_student.py`: selected checkpoint export with left/right FP32-reference checks; failed conversion tolerances now fail the command instead of merely recording a false flag.

## Training and selection

The continuation completed {status['step']:,} additional steps in {status['seconds']/60:.2f} minutes. Batch 4 over {run['training_patches']:,} cached training patches is {run['additional_epoch_equivalents']:.2f} additional epoch equivalents. The preceding 6,000-step run was approximately 3.11 epochs. These are small models learning from preprocessed 512-pixel patches, so useful experiments need not take hours. Running longer is not itself evidence of improvement.

Initialization uses the prior fast model's EMA weights with a new optimizer because the older checkpoint had no optimizer state. The new checkpoints support continuation with saved optimizer/RNG state, but CUDA algorithm nondeterminism prevents a promise of bit-exact reruns. Original captures, crash exclusions, cache and sequence splits are unchanged. No new test-set tuning or evaluation occurred.

Validation covers 352 patches, 88 eyes, 44 stereo frames and four sequences:

| Candidate | RGB MAE, lower | PSNR dB, higher | Feature distance, lower |
|---|---:|---:|---:|
{quality_rows}

The best MAE checkpoint is the default delivery. The best feature checkpoint is preserved separately: its improved feature score trades off pixel accuracy. The frozen feature network is also part of the training objective, so this score is not independent visual acceptance. Faces, hair, local shadows and material detail remain visibly different from the teacher. Longer training did not solve these gaps.

## Matched native stereo replay

RTX 5070 Ti, 2496×2688 per eye, authentic 1664×1792 depth/motion guides, 100% model resolution, one Feature 18 pass, recorded tuning 2/2/2, skin -1, auto mask enabled, UI correction disabled. Each row has 20 warm-up pairs and 100 measured pairs. Teacher and student execute sequentially after training/export has stopped; the final series runs student before teacher. The earlier baseline series ran teacher before student. Contended smoke timings are excluded.

| Validation sequence index | NVIDIA stereo wall ms | NVIDIA stereo GPU ms | Student stereo wall ms | Student wall p95 ms | Wall speed ratio |
|---|---:|---:|---:|---:|---:|
{speed_rows}

Wall timing is synchronized completion of each stereo pair. The student includes GPU texture/buffer copies, RGB/guide/context preparation, TensorRT, output packing and shared-fence handoff back to D3D12. The teacher includes its native command submission and synchronized completion. CUDA event scope and NVIDIA GPU timestamp scope differ, so the headline ratio uses wall-to-wall. Both exclude initial disk upload, Skyrim rendering and compositor work. Warm figures do not include engine creation or first-frame latency.

Each of four pairs has exact-byte checks for both eyes' color/depth/motion input and both returned graphics outputs. Teacher output is neither empty nor pass-through, and native replay is visibly consistent with the captured teacher. The replay repeats a static pair with recorded motion, not a valid moving sequence; native and captured teacher histories differ. These tests establish a native-resource execution path and speed feasibility, not temporal quality or a scene-distribution benchmark.

The chosen TensorRT engine uses FP16 tactics, FP32 reductions where preferred and FP32 I/O. It is **not NVFP4**. Against PyTorch FP32, the mean absolute conversion differences were {runtime['numerical_check']['mean_absolute_difference']:.8f} (left) and {runtime['right_eye_numerical_check']['mean_absolute_difference']:.8f} (right); both passed the pre-existing mean ≤0.001 and maximum ≤0.05 thresholds. GPU preprocessing checks separately passed: RGB max error 5.96e-8, guides 4.29e-5, context 0.00416, and downstream prediction mean difference 0.0000318 on the reference eye. Context is approximately, not bit-exactly, equivalent to cached PIL BOX/FP16 preparation.

## Delivery and next engineering step

Selected weights: `out/student_long_20260905/fast_continuation/best_mae.pt`.

Selected engine: `out/student_long_20260905/runtime_best_mae/student_fp16.engine`.

Alternative appearance candidate: `out/student_long_20260905/fast_continuation/best_feature.pt`.

Hashes and full measurements: `out/student_long_20260905/delivery.json`. Visual comparison: `out/student_long_20260905/gallery.html`. Native replay evidence: `out/native_final_20260905/sequence_0/comparison` through `sequence_3/comparison`.

The speed stopping condition is satisfied for this explicitly scoped offline native-resource benchmark; visual-equivalence and live-game acceptance remain open. The model cannot replace `nvngx_dlssnr.dll` by renaming a file. Integration needs an explicit student backend at the owned renderer boundary, with stable shared-resource lifetime, adapter identity checks, per-eye routing, history/reset behavior, resizing and device-loss fallback. The current bridge owns its own D3D12 device and is exercised from Python; it is not the finished C++ in-game backend.

For quality, the useful next experiment is more scene-diverse supervision and a larger receptive field or carefully validated face/detail objective. The data is spatial-only; do not invent contiguous temporal history from sparse captures. New independent acceptance sequences are needed before trusting further validation-driven gains. NVFP4 is a later quantization experiment with calibration and image-error checks, not a switch that makes this FP16 engine four-bit. An approximately 8 ms stereo effect also consumes much of an 11.11 ms 90 Hz frame budget before game rendering, so offline speed superiority does not guarantee acceptable VR frame time.
'''
(root / 'docs/LONG_TRAINING_AND_NATIVE_RUNTIME_20260905.md').write_text(body, encoding='utf-8')
gallery = ['<!doctype html><meta charset="utf-8"><title>OpenNR longer training evidence</title><style>body{background:#121820;color:#eee;font:17px system-ui;margin:28px}img{max-width:100%;height:auto}a{color:#8bd1ff}</style><h1>OpenNR longer training evidence</h1><p>Columns: input, previous fast, best MAE, best feature, captured teacher. Validation only. Teacher-equivalent quality is not achieved.</p>']
for path in sorted((out / 'comparison').glob('validation_detail_*.jpg')):
    gallery.append(f'<h2>{html.escape(path.stem)}</h2><img src="comparison/{html.escape(path.name)}">')
gallery.append('<h2>Complete-eye comparisons</h2>')
for path in sorted((out / 'comparison').glob('validation_eye_*.jpg')):
    gallery.append(f'<img src="comparison/{html.escape(path.name)}">')
(out / 'gallery.html').write_text('\n'.join(gallery), encoding='utf-8')
print('Report, gallery and delivery manifest written.')
