"""Assemble the finished quality-control run without claiming goal completion."""
import hashlib
import html
import json
from pathlib import Path
import torch

root=Path(__file__).resolve().parents[1];out=root/'out/quality_phase_20260905'
status=json.loads((out/'detail_continuation/status.json').read_text());assert status['state']=='completed'
lpips=json.loads((out/'lpips_detail_final/result.json').read_text())['results']
base=json.loads((out/'native_fast_baseline/result.json').read_text())
baseline_lpips=json.loads((out/'lpips_preview/result.json').read_text())['results']
baseline_lpips=next(v['lpips'] for k,v in baseline_lpips.items() if 'fast_continuation' in k)
records=[]
for name in ('best_mae','best_feature'):
    source=out/'detail_continuation'/f'{name}.pt'
    native=json.loads((out/f'native_detail_{name}/result.json').read_text())
    score=next(v for k,v in lpips.items() if Path(k).stem==name)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest==native['checkpoint_sha256']==score['checkpoint_sha256']
    ckpt=torch.load(source,map_location='cpu',weights_only=False)
    portable=out/f'OpenNR_Quality_v2_{name}.pt'
    torch.save({k:ckpt[k] for k in ('architecture','config','model','cache','step')},portable)
    records.append(dict(label=name,checkpoint=str(source),portable=str(portable),portable_sha256=hashlib.sha256(portable.read_bytes()).hexdigest(),native_mae=native['mae'],changed_mae=native['changed_region_mae'],psnr=native['psnr'],lpips=score['lpips'],step=score['step']))
(out/'quality_control_delivery.json').write_text(json.dumps(dict(status=status,candidates=records,selection='Preserve both candidates; appearance/context work continues. No test or live acceptance.'),indent=2))
rows='\n'.join(f'| {r["label"]} | {r["step"]:,} | {r["native_mae"]:.6f} | {r["changed_mae"]:.6f} | {r["lpips"]:.6f} |' for r in records)
body=f'''# Completed scale4 quality continuation — 2026-09-05

The higher-resolution v2 quality control completed20,000 additional steps in{status['seconds']/60:.2f} minutes. Native-eye and separately evaluated LPIPS results improve over the prior fast delivery, but teacher-equivalent appearance remains unachieved. The matched context-attention experiment is the next active run; this document does not close the project goal.

All88 native validation eyes and all352 unchanged512-pixel validation patches were evaluated. AlexNet LPIPS v0.1 is evaluated on displayed clamped RGB, without patch resizing, and is not used in the SqueezeNet training objective. No new test rows were evaluated. Changed pixels are fixed by teacher-input mean RGB difference>0.05. Teacher-changed regions occupy23.92% of the native pixels.

| Candidate | Additional step | Native RGB MAE down | Changed-region MAE down | Patch LPIPS down |
|---|---:|---:|---:|---:|
| Previous fast delivery | 5,000 | {base['mae']:.6f} | {base['changed_region_mae']:.6f} | {baseline_lpips:.6f} |
{rows}

Keep the best-MAE and best-feature weights separately. "Best MAE" means selection on cached validation patches, not all native pixels: the earlier checkpoint has better patch MAE and native changed-region MAE, while the later checkpoint has better whole-eye MAE and LPIPS. This distinction is why native evaluation was added. Visual review still finds facial shadow, skin and hair differences. Do not silently use the last checkpoint, claim that feature loss proves appearance, or label either candidate as the completed replacement.

Portable inference-only candidates are `out/quality_phase_20260905/OpenNR_Quality_v2_best_mae.pt` and `OpenNR_Quality_v2_best_feature.pt`. Original optimizer-bearing checkpoints remain in `detail_continuation`. `quality_control_delivery.json` records hashes. The previous compiled fast engine has not been replaced; these new scale4 weights have not been benchmarked as newly compiled TensorRT engines.

Open `out/quality_phase_20260905/quality_control_gallery.html` for the comparisons. Columns are input, previous fast delivery, new best-MAE, new best-feature, teacher. Full-resolution metrics are in `native_detail_best_mae/result.json` and `native_detail_best_feature/result.json`; LPIPS is in `lpips_detail_final/result.json`.

The effect-strength diagnostic does not support a simple intensity boost: the model's residual RMS is about94% of the teacher's on validation, but its direction/structure agreement is weaker than on training. Further work is therefore focused on contextual reconstruction and generalization. See `docs/QUALITY_PHASE_20260905.md` for the experiment record, research sources and active-run references.
'''
(root/'docs/QUALITY_CONTROL_RESULT_20260905.md').write_text(body,encoding='utf-8')
page=['<!doctype html><meta charset="utf-8"><title>OpenNR quality control</title><style>body{background:#141820;color:#eee;font:18px system-ui;margin:24px}img{max-width:100%}</style><h1>Completed quality-control comparison</h1><p>Input / previous fast / best MAE / best feature / teacher. Validation only; teacher equivalence remains unachieved.</p>']
for pattern in ('validation_detail_*.jpg','validation_eye_*.jpg'):
    for path in sorted((out/'detail_final_comparison').glob(pattern)):
        page.append(f'<h2>{html.escape(path.stem)}</h2><img src="detail_final_comparison/{html.escape(path.name)}">')
(out/'quality_control_gallery.html').write_text('\n'.join(page),encoding='utf-8')
print(json.dumps(records,indent=2))
