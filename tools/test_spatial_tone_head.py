import unittest
import torch
from spatial_tone_head import SpatialToneHead,FrozenParentToneModel


class FakeParent(torch.nn.Module):
    def __init__(self):
        super().__init__();self.scale=torch.nn.Parameter(torch.tensor(.9))
    def forward_temporal(self,rgb,guides,context,state=None):
        base=rgb*self.scale
        return base,(rgb,base)


class ToneTests(unittest.TestCase):
    def inputs(self):
        torch.manual_seed(41)
        return torch.rand(2,3,48,64),torch.rand(2,3,48,64),torch.rand(2,5,12,16),torch.rand(2,8,8,8)

    def test_identity_and_gradient(self):
        x,b,g,c=self.inputs()
        for spatial in (True,False):
            h=SpatialToneHead(spatial=spatial)
            y=h(x,b,g,c)
            torch.testing.assert_close(y,b,rtol=0,atol=0)
            y.mean().backward()
            self.assertGreater(float(h.affine.weight.grad.abs().sum()),0)

    def test_bounded_and_channel_specific(self):
        x,b,g,c=self.inputs();h=SpatialToneHead()
        with torch.no_grad():h.affine.bias[9]=1;h.affine.bias[11]=-1
        y=h(x,b,g,c)
        self.assertTrue(torch.isfinite(y).all());self.assertTrue(((y>=0)&(y<=1)).all())
        self.assertTrue((y[:,0]>=b[:,0]).all());self.assertTrue((y[:,2]<=b[:,2]).all())
        torch.testing.assert_close(y[:,1],b[:,1])

    def test_frozen_parent_and_state(self):
        x,b,g,c=self.inputs();p=FakeParent();m=FrozenParentToneModel(p,SpatialToneHead()).train()
        y,state=m.forward_temporal(x,g,c)
        y.mean().backward()
        self.assertIsNone(p.scale.grad);self.assertFalse(p.training)
        torch.testing.assert_close(state[1],x*.9)


if __name__=='__main__':
    torch.set_num_threads(1);unittest.main()
