"""Check the loss ablation preserves the original combined objective."""
import unittest
import torch
from torch.nn import functional as F
from train_spatial_tone import frame_objective


class ObjectiveTests(unittest.TestCase):
    def test_combined_value_and_gradient(self):
        torch.manual_seed(357)
        error=torch.randn(1,3,32,32,requires_grad=True)
        previous=torch.randn_like(error,requires_grad=True)
        expected=error.abs().mean()+.5*F.avg_pool2d(error,16).abs().mean()+.12*(error-previous).abs().mean()
        actual=frame_objective(error,previous)
        self.assertTrue(torch.equal(actual,expected))
        actual_grad=torch.autograd.grad(actual,(error,previous),retain_graph=True)
        expected_grad=torch.autograd.grad(expected,(error,previous))
        for a,b in zip(actual_grad,expected_grad):self.assertTrue(torch.equal(a,b))

    def test_pixel_only_no_previous_dependency(self):
        error=torch.randn(1,3,32,32,requires_grad=True)
        previous=torch.randn_like(error,requires_grad=True)
        actual=frame_objective(error,previous,True)
        self.assertTrue(torch.equal(actual,error.abs().mean()))
        gradient,previous_gradient=torch.autograd.grad(actual,(error,previous),allow_unused=True)
        self.assertTrue(torch.equal(gradient,error.sign()/error.numel()))
        self.assertIsNone(previous_gradient)


if __name__=='__main__':unittest.main()
