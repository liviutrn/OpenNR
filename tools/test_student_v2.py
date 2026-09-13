import torch
from student_v2 import ReconstructionStudent,ReconstructionConfig,detail_loss
from perceptual_features import FeatureDistance

torch.set_num_threads(2)
m=ReconstructionStudent(ReconstructionConfig(width=8,blocks=1))
for h,w in ((128,128),(129,135),(128,144)):
    x=torch.rand(1,3,h,w);g=torch.rand(1,5,32,32);c=torch.rand(1,8,96,96);p=m(x,g,c)
    assert p.shape==x.shape and torch.equal(p,x)
loss=detail_loss(p,x*.8,x);loss.backward()
assert all(torch.isfinite(v.grad).all() for v in m.parameters() if v.grad is not None)
fast=ReconstructionStudent(ReconstructionConfig(width=8,blocks=1,scale=8))
z=fast(x,g,c);assert z.shape==x.shape and torch.equal(z,x)
detail_loss(z,x*.8,x).backward();assert all(torch.isfinite(v.grad).all() for v in fast.parameters() if v.grad is not None)
f=FeatureDistance();x=torch.rand(1,3,128,128,requires_grad=True);t=x.detach()*.8
assert f(x,x.detach()).item()<1e-8
loss=f(x,t);loss.backward();assert torch.isfinite(x.grad).all() and x.grad.abs().sum()>0
assert all(v.grad is None for v in f.parameters())
print('PASS: v2 identity, shape preservation, finite gradients, differentiable frozen feature loss')
