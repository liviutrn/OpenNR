"""Actual CUDA VGG loss, identity and input-gradient test with frozen weights."""
import json
from pathlib import Path
import torch
from vgg_appearance_loss import VGGAppearanceLoss

torch.set_num_threads(4);torch.manual_seed(912)
metric=VGGAppearanceLoss().cuda().eval()
pred=torch.rand(1,3,128,128,device='cuda',requires_grad=True);target=torch.rand_like(pred)
with torch.no_grad():identity=float(metric(target,target))
loss=metric(pred,target);loss.backward()
assert abs(identity)<1e-7 and torch.isfinite(loss) and loss>0
assert pred.grad is not None and torch.isfinite(pred.grad).all() and pred.grad.abs().sum()>0
assert all(not p.requires_grad and p.grad is None for p in metric.parameters())
result=dict(state='passed',identity=identity,loss=float(loss.detach()),finite_nonzero_input_gradient=True,weights_frozen=True,provenance=metric.provenance)
Path('out/quality_phase_20260905/vgg_loss_validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
