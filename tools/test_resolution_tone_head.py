import unittest
import torch
from spatial_tone_head import SpatialToneHead, FrozenParentToneModel
from resolution_tone_head import ResolutionToneHead
from test_spatial_tone_head import FakeParent


class ResolutionTests(unittest.TestCase):
    def test_coarse_equivalence_after_nonzero_initialization(self):
        torch.manual_seed(357)
        old=SpatialToneHead();new=ResolutionToneHead(16)
        torch.nn.init.normal_(old.affine.weight, std=.01)
        new.load_state_dict(old.state_dict())
        inputs=(torch.rand(2,3,64,80),torch.rand(2,3,64,80),
                torch.rand(2,5,16,20),torch.rand(2,8,12,12))
        torch.testing.assert_close(old(*inputs),new(*inputs),rtol=0,atol=0)
        self.assertEqual(sum(p.numel() for p in old.parameters()),
                         sum(p.numel() for p in ResolutionToneHead(4).parameters()))

    def test_fine_identity_gradient_and_parent_state(self):
        rgb=torch.rand(2,3,64,64);g=torch.rand(2,5,16,16);c=torch.rand(2,8,12,12)
        head=ResolutionToneHead(4);parent=FakeParent()
        model=FrozenParentToneModel(parent,head).train()
        y,state=model.forward_temporal(rgb,g,c)
        torch.testing.assert_close(y,rgb*.9,rtol=0,atol=0)
        y.mean().backward()
        self.assertGreater(float(head.affine.weight.grad.abs().sum()),0)
        self.assertIsNone(parent.scale.grad)
        torch.testing.assert_close(state[1],rgb*.9)
        with torch.no_grad():head.affine.bias.fill_(100)
        y,_=model.forward_temporal(rgb,g,c)
        self.assertTrue(torch.isfinite(y).all() and ((y>=0)&(y<=1)).all())


if __name__=='__main__':
    torch.set_num_threads(1);unittest.main()
