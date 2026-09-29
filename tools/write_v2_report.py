"""Source-backed v2 experiment report; all new quality evaluation is validation."""
import json,hashlib,html
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'out/student_v2_20260904'
quality=json.loads((out/'comparison/validation.json').read_text());runtime={}
for name in ('runtime_v1','runtime_v2_detail','runtime_v2_perceptual','runtime_v2_fast'):
    path=out/name/'runtime_result.json'
    if path.exists():runtime[name]=json.loads(path.read_text())
table='\n'.join(f'| {Path(name).parent.name} | {m["mae"]:.6f} | {m["psnr"]:.3f} | {m["feature_distance"]:.6f} |' for name,m in quality.items())
timings='\n'.join(f'| {name} | {r["warm_eye_median_ms"]:.3f} | {r.get("actual_sequential_stereo_median_ms",r["sequential_stereo_estimate_ms"]):.3f} | {r["numerical_check"]["mean_absolute_difference"]:.6f} | {r["numerical_check"]["passed"]} |' for name,r in runtime.items())
checkpoints={}
for name in ('detail','perceptual','diagnostic','fast'):
    if not (out/name/'best.pt').exists():continue
    p=out/name/'best.pt';checkpoints[name]=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
body=f'''# OpenNR v2 reconstruction and TensorRT experiment

This experiment responds to the visual shortfall of Student v1. It implements a less constrained reconstruction architecture, a feature-loss ablation, a small training-fit diagnostic, and an actual GPU-resident TensorRT FP16 prototype. It does not establish teacher-equivalent appearance or live VR acceptance.

The delivered choices are `fast/best.pt` with `runtime_v2_fast/student_fp16.engine` for runtime work, and `perceptual/best.pt` with `runtime_v2_perceptual/student_fp16.engine` for the strongest feature-score candidate. The fast engine's warmed actual stereo latency is about 7.65 ms; the perceptual engine is about 24.47 ms. These are inference-only measurements. Visual teacher matching remains incomplete.

## What changed

`tools/student_v2.py` preserves all RGB samples with pixel-unshuffle, replacing v1's bilinear input reduction. A 1,810,512-parameter, three-stage gated reconstruction network uses aligned native guides and whole-eye context. Its pixel-shuffled residual has no v1-style ±0.1 bound. Output is unbounded during learning and numeric evaluation; display PNGs clamp to [0,1]. Native 2496x2688 and arbitrary tensor shapes are supported by PyTorch; exported engines have fixed native dimensions.

The additional fast variant packs 8x8 pixel blocks instead of 4x4 blocks, reducing the learned spatial grid by four while preserving RGB samples in its input channels. Its stem then learns a compressed representation; lossless packing is not a claim that the whole network preserves information. The fast variant uses the same perceptual-loss weight and a separate 6,000-step training run.

The detail loss combines change-weighted Charbonnier, multiscale image gradients and coarse L1. Weighting is applied only to training; evaluation includes the same full set of RGB pixels for all models. The perceptual ablation adds 0.05 times normalized frozen ImageNet SqueezeNet feature distance at four feature stages. This is an experimental feature loss, not calibrated LPIPS or proof of semantic/VR quality. The official pretrained feature model is used during training/evaluation only and is not embedded in the student checkpoint. Source: https://docs.pytorch.org/vision/stable/_modules/torchvision/models/squeezenet.html .

## Training and diagnostic

The source captures, audited cache and sequence splits are unchanged. Each v2 candidate starts from scratch, seed73, batch4, 6000steps, cosine AdamW with initial LR0.0003, EMA and finite-gradient checks. Best checkpoints are selected by validation MAE for a matched comparison; feature scores are reported separately, not silently substituted as a selection criterion. This is a bounded architecture/loss experiment, not an exhaustive convergence or hyperparameter search.

The diagnostic deliberately fits four high-change training patches, chosen among the first 64 training-eye candidates. All four selected examples are correlated frames from the same indoor sequence. After 1,000 steps, training MAE is 0.007243 versus identity 0.064842: 88.83% reduction. This shows those examples can be fit; it does not establish face reconstruction capacity or generalization. Diagnostic weights are not deployment candidates.

## Validation results

All 352 validation patches, 88 eyes, 44 stereo frames, 4 sequences. No new test-set tuning or evaluation was performed. The earlier v1 frozen test report remains unchanged. V2 needs a new independent acceptance collection if validation-driven development continues.

| Checkpoint | RGB MAE down | PSNR dB up | Feature distance down |
|---|---:|---:|---:|
{table}

The feature evaluator is the same SqueezeNet used by the perceptual objective, so its gains are not independent perceptual confirmation. Native full-eye previews and fixed native detail crops are in `out/student_v2_20260904/comparison`. Inspect the visible face/hair/material differences rather than interpreting average metrics as teacher-equivalent appearance.

Visual inspection of the fixed female and male face crops still shows missing teacher shading and fine texture. The quarter-resolution perceptual candidate has the best feature score of the v2 candidates. The fast candidate retains similar aggregate RGB error but loses part of that feature-score gain. None is labeled visually accepted. The four validation sequences are too narrow to establish broad scene/character generalization.

## TensorRT runtime

Installed into the existing isolated Python environment: torchvision0.22.1, ONNX1.18.0 and TensorRT10.13.3.9 CUDA12, with their runtime dependencies. PyTorch remains2.7.1+cu128. No game binaries or MGO settings changed.

`tools/tensorrt_student.py` exports/checks static ONNX, builds a serialized FP16 engine with FP32 reduction preference, binds torch-owned CUDA buffers directly, executes on the torch CUDA stream, compares with PyTorch FP32 and records CUDA-event latency. There is no CPU image round-trip inside engine execution. This is **FP16, not NVFP4**. It provides the optimized reference needed before low-bit calibration/QAT. NVFP4 kernel coverage, conversion and image-quality acceptance have not been implemented or measured here.

`tools/trt_inference.py` provides a reusable `TensorRTStudent` wrapper and native-image CLI. It validates tensor shape, device, type and layout, uses a dedicated CUDA stream with producer/consumer synchronization, and retains a reusable output buffer. The caller must consume or clone that output before the next inference. The CLI was exercised on a native validation eye. This is an offline runtime building block, not a game plugin.

The fast wrapper was also tested by enqueueing left and right with output clones, then comparing both against FP32: mean errors approximately 0.0000677 and 0.0000617. The test exercises output-buffer reuse and cross-stream ordering and confirms that an incorrect input shape is rejected. See `runtime_wrapper_test.json` and `tools/test_trt_inference.py`.

| Engine | Warm eye ms | Actual sequential stereo ms | Mean error vs FP32 | Numerical tolerance pass |
|---|---:|---:|---:|---|
{timings}

These measurements use one actual validation left/right pair and GPU-resident tensors, with direct input address rebinding on a non-default CUDA stream. Per-eye numerical tolerance is predeclared mean<=0.001 and max<=0.05; both eyes are checked. Passing is a smoke check, not complete engine acceptance. Engine binary is specific to this GPU/runtime. A 90 Hz frame is 11.11 ms for the entire renderer, so measured engine time must leave room for rendering, interop and composition.

The eager v2 CUDA profile over five native forwards attributes about 28.85% of self CUDA time to depthwise convolution, 17.81% to cuDNN convolution, and substantial remaining time to elementwise multiplication/addition/subtraction and copies. This supports testing kernel fusion and memory layout before assuming NVFP4 matrix throughput will accelerate the whole network. The profiler trace and table are in `profile_detail`; profiler timings are not standalone latency measurements.

An optional channels-last PyTorch path was implemented and benchmarked for the detail model: 50.55 ms per eye and 96.70 ms for an actual sequential pair. It did not achieve the needed budget, and TensorRT is the practical runtime prototype delivered here.

## Files and reproduction

Use `E:/OpenNR-VR-Poc-Venv/Scripts/python.exe` from the project root:

```powershell
python tools/test_student_v2.py
python tools/train_v2.py --cache C:/OpenNR/TrainingCache/student_v1 --output out/v2_new_detail --steps 6000
python tools/train_v2.py --cache C:/OpenNR/TrainingCache/student_v1 --output out/v2_new_features --steps 6000 --perceptual 0.05
python tools/compare_v2.py --cache C:/OpenNR/TrainingCache/student_v1 --output out/v2_new_comparison --models out/student_v1_20260904/OpenNR_Student_v1.pt out/v2_new_detail/best.pt out/v2_new_features/best.pt
python tools/tensorrt_student.py --checkpoint out/v2_new_detail/best.pt --cache C:/OpenNR/TrainingCache/student_v1 --output out/v2_new_engine
python tools/trt_inference.py --engine out/student_v2_20260904/runtime_v2_perceptual/student_fp16.engine --cache C:/OpenNR/TrainingCache/student_v1 --row 408 --output out/v2_engine_example.png
```

Each candidate contains `best.pt`, `run.json`, `history.jsonl` and `status.json`; full console logs are under `out/v2_*.log`. V2 checkpoints contain inference weights, architecture/config, selected step and cache provenance. They do not contain optimizer state for exact resumption. Do not overwrite an experiment directory; the training command rejects existing run metadata. Source/checkpoint/feature-weight fingerprints are in `out/student_v2_20260904/provenance.json`.

Remaining acceptance work: native face/hair appearance still requires visual judgment; neither feature similarity nor training memorization establishes it. Profile and optimize the accepted architecture, calibrate supported lower precision, validate more engine inputs and true stereo transfers, then evaluate isolated game/headset delivery. Temporal supervision is still limited by sparse captures and uncalibrated history conventions.
'''
(root/'docs/STUDENT_V2_RESULT_20260904.md').write_text(body,encoding='utf-8')
gallery='<!doctype html><meta charset="utf-8"><title>OpenNR v2 validation</title><style>body{background:#161b22;color:#eee;font:16px system-ui;margin:24px}img{max-width:100%;height:auto}figure{margin:32px 0}</style><h1>OpenNR v2 validation comparisons</h1><p>Columns are labeled: input, candidate models, captured teacher. All examples are validation, not test. The pretrained feature metric is experimental and does not prove perceptual equivalence.</p>'
for path in sorted((out/'comparison').glob('*.jpg')):gallery+=f'<figure><figcaption>{html.escape(path.stem)}</figcaption><img src="comparison/{path.name}"></figure>'
(out/'gallery.html').write_text(gallery,encoding='utf-8')
from PIL import Image
source=out/'comparison/validation_detail_440.jpg'
if source.exists():
    with Image.open(source) as im:
        if im.width==3072:
            for label,columns in [('quality_face',(0,3,5)),('fast_face',(0,4,5))]:
                sheet=Image.new('RGB',(1536,im.height))
                for j,k in enumerate(columns):sheet.paste(im.crop((512*k,0,512*(k+1),im.height)),(512*j,0))
                sheet.save(out/(label+'.png'))
files=['student_v2.py','train_v2.py','perceptual_features.py','compare_v2.py','tensorrt_student.py','trt_inference.py','profile_student.py','test_student_v2.py','test_trt_inference.py','benchmark_student.py','opennr_student.py']
weights=Path.home()/'.cache/torch/hub/checkpoints/squeezenet1_1-b8a52dc0.pth'
(out/'provenance.json').write_text(json.dumps(dict(checkpoints=checkpoints,engines_sha256={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('runtime_*/*.engine')},source_sha256={f:hashlib.sha256((root/'tools'/f).read_bytes()).hexdigest() for f in files},perceptual_weights_sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),test_used=False),indent=2))
(out/'status.json').write_text(json.dumps(dict(state='completed',training='three 6000-step candidates plus 1000-step diagnostic',validation='complete; no new test evaluation',engines='four compiled FP16 engines; native stereo smoke checks passed',runtime_candidate='fast/best.pt',feature_score_candidate='perceptual/best.pt',nvfp4='not implemented',live_vr_acceptance=False),indent=2))
print('Wrote v2 report, gallery and provenance')
