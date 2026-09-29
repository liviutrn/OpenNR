import unittest
import torch
from multiscale_tone_head import MultiscaleToneHead
from spatial_tone_head import FrozenParentToneModel
from test_spatial_tone_head import FakeParent


class MultiscaleTests(unittest.TestCase):
    def test_identity_gradients_and_frozen_state(self):
        torch.manual_seed(359)
        x=torch.rand(1,3,64,80);g=torch.rand(1,5,16,20);c=torch.rand(1,8,12,12)
        h=MultiscaleToneHead();p=FakeParent();m=FrozenParentToneModel(p,h).train()
        y,state=m.forward_temporal(x,g,c)
        torch.testing.assert_close(y,x*.9,rtol=0,atol=0)
        y.mean().backward();self.assertGreater(float(h.affine.weight.grad.abs().sum()),0)
        self.assertIsNone(p.scale.grad);torch.testing.assert_close(state[1],x*.9)
        with torch.no_grad():h.affine.weight.normal_(std=.01)
        h.zero_grad();h(x,x*.9,g,c).mean().backward()
        for branch in (h.local,h.coarse,h.global_features):
            self.assertGreater(sum(float(p.grad.abs().sum()) for p in branch.parameters()),0)
        with torch.no_grad():h.affine.bias.fill_(100)
        y=h(x,x*.9,g,c);self.assertTrue(torch.isfinite(y).all() and ((y>=0)&(y<=1)).all())


if __name__=='__main__':
    torch.set_num_threads(1);unittest.main()
