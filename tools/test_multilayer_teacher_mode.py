import copy
import unittest
import torch
from torch import nn
from stable_oversized_tone_head import StableOversizedToneHead
from teacher_mode_head import enable_teacher_mode,set_teacher_mode
from multilayer_teacher_mode import TeacherModeGroupNorm,enable_multilayer_teacher_mode,set_conditioned_teacher_mode


class MultiLayerTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(4);torch.manual_seed(359)

    def test_norm_identity_gradient_and_mode_isolation(self):
        old=nn.GroupNorm(2,4);new=TeacherModeGroupNorm(old)
        x=torch.randn(2,4,8,8)
        for dtype in (torch.float32,torch.bfloat16):
            for mode in (1,2):
                new.teacher_pass_count=mode
                self.assertTrue(torch.equal(old(x.to(dtype)),new(x.to(dtype))))
        new.teacher_pass_count=2
        new(x).square().mean().backward()
        self.assertGreater(float(new.mode_scale.grad.abs().sum()),0.)
        self.assertGreater(float(new.mode_bias.grad.abs().sum()),0.)
        with torch.no_grad():new.mode_scale.fill_(.2);new.mode_bias.fill_(.1)
        new.teacher_pass_count=1
        self.assertTrue(torch.equal(old(x),new(x)))
        new.teacher_pass_count=2
        self.assertFalse(torch.equal(old(x),new(x)))

    def test_full_head_identity_state_and_gradients(self):
        old=enable_teacher_mode(StableOversizedToneHead())
        with torch.no_grad():old.affine.weight.normal_(std=.01)
        new=enable_multilayer_teacher_mode(copy.deepcopy(old))
        self.assertEqual(sum(p.numel() for p in new.parameters())-sum(p.numel() for p in old.parameters()),22688)
        rgb=torch.rand(1,3,32,32)*.6+.2
        guides=torch.randn(1,5,8,8);context=torch.randn(1,8,8,8)
        for mode in (1,2):
            set_teacher_mode(old,mode);set_conditioned_teacher_mode(new,mode)
            with torch.no_grad():self.assertTrue(torch.equal(old(rgb,rgb,guides,context),new(rgb,rgb,guides,context)))
        set_conditioned_teacher_mode(new,2)
        new(rgb,rgb,guides,context).square().mean().backward()
        norms=[module for module in new.modules() if isinstance(module,TeacherModeGroupNorm)]
        self.assertEqual(len(norms),51)
        for norm in norms:
            for parameter in (norm.mode_scale,norm.mode_bias):
                self.assertIsNotNone(parameter.grad)
                self.assertTrue(torch.isfinite(parameter.grad).all())
                self.assertGreater(float(parameter.grad.abs().sum()),0.)
        clone=enable_multilayer_teacher_mode(StableOversizedToneHead())
        clone.load_state_dict(new.state_dict(),strict=True)
        set_conditioned_teacher_mode(clone,2)
        with torch.no_grad():self.assertTrue(torch.equal(clone(rgb,rgb,guides,context),new(rgb,rgb,guides,context)))
        with self.assertRaises(ValueError):enable_multilayer_teacher_mode(new)
        with self.assertRaises(ValueError):set_conditioned_teacher_mode(new,3)


if __name__=='__main__':unittest.main()
