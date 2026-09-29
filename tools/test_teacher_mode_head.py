import unittest
import torch
from torch import nn
from teacher_mode_head import TeacherModeConv,set_teacher_mode
from teacher_mode_head import enable_teacher_mode


class ModeTests(unittest.TestCase):
    def test_identity_and_separate_mode_gradient(self):
        torch.manual_seed(1)
        original=nn.Conv2d(19,16,3,padding=1)
        mode=TeacherModeConv(original)
        x=torch.randn(2,19,8,8)
        self.assertTrue(torch.equal(original(x),mode(x)))
        mode.teacher_pass_count=2
        self.assertTrue(torch.equal(original(x),mode(x)))
        mode(x).sum().backward()
        self.assertTrue(torch.all(mode.mode_bias.grad!=0))
        with torch.no_grad():mode.mode_bias.fill_(.5)
        self.assertTrue(torch.allclose(mode(x),original(x)+.5))
        mode.teacher_pass_count=1
        self.assertTrue(torch.equal(mode(x),original(x)))

    def test_mode_guard(self):
        head=nn.Module();head.stem=nn.Sequential(nn.Conv2d(19,16,3))
        with self.assertRaises(ValueError):set_teacher_mode(head,2)
        head.stem[0]=TeacherModeConv(head.stem[0])
        with self.assertRaises(ValueError):set_teacher_mode(head,3)
        set_teacher_mode(head,2)
        self.assertEqual(head.stem[0].teacher_pass_count,2)

    def test_full_head_initial_equivalence_and_reload(self):
        from stable_oversized_tone_head import StableOversizedToneHead
        torch.set_num_threads(2)
        torch.manual_seed(2)
        head=StableOversizedToneHead().eval()
        with torch.no_grad():head.affine.weight.normal_(0,.01)
        args=(torch.rand(1,3,32,32),torch.rand(1,3,32,32),torch.rand(1,5,8,8),torch.rand(1,8,8,8))
        with torch.no_grad():before=head(*args)
        enable_teacher_mode(head)
        for mode in (1,2):
            set_teacher_mode(head,mode)
            with torch.no_grad():after=head(*args)
            self.assertTrue(torch.equal(before,after))
        clone=enable_teacher_mode(StableOversizedToneHead()).eval()
        clone.load_state_dict(head.state_dict(),strict=True)
        set_teacher_mode(clone,2)
        with torch.no_grad():self.assertTrue(torch.equal(clone(*args),before))


if __name__=='__main__':unittest.main()
