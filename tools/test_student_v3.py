"""Context upgrade must preserve the trained function and learn spatial context."""
import torch
from student_v2 import ReconstructionStudent,ReconstructionConfig
from student_v3 import ContextStudent

torch.set_num_threads(4)
torch.manual_seed(281)
config=ReconstructionConfig(width=16,blocks=1,scale=4)
base=ReconstructionStudent(config)
# Nonzero trained-style reconstruction head makes identity checks meaningful.
torch.nn.init.normal_(base.output.weight,std=.01)
model=ContextStudent(config);model.initialize_v2(base.state_dict())
x=torch.rand(1,3,128,160);g=torch.rand(1,5,32,40);c=torch.rand(1,8,96,96)
with torch.no_grad():
    expected=base(x,g,c);actual=model(x,g,c)
    torch.testing.assert_close(actual,expected,atol=0,rtol=0)
loss=(model(x,g,c)-torch.rand_like(x)).square().mean();loss.backward()
assert model.context_output.weight.grad.abs().sum()>0
assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
with torch.no_grad():
    model.context_output.weight.add_(-.1*model.context_output.weight.grad)
    assert (model(x,g,c)-model(x,g,c.flip(-1))).abs().max()>0
print('PASS: exact v2 initialization, finite gradients, trainable spatial context, rectangular input')
