import unittest
import numpy as np
import torch
from audit_conditioning_content import align
from prepare_conditioning_pilot import features
from train_conditioning_pilot import RendererRefiner, evaluate


class ConditioningPilotTests(unittest.TestCase):
    def test_coordinate_mapping_and_coverage(self):
        x=np.stack(np.meshgrid(np.arange(512),np.arange(512)),axis=-1).astype(float)
        a={'source_rect':{'width':1664,'height':1792},'crop_rect':{'x':576,'y':640},'width':512,'height':512}
        t={'source_rect':{'width':2496,'height':2688},'crop_rect':{'x':992,'y':1088},'width':512,'height':512}
        y,m=align(x,a,t)
        self.assertTrue(m['covered'])
        np.testing.assert_allclose(m['scale'],[2/3,2/3])
        np.testing.assert_allclose(m['offset'],[256/3,256/3])
        self.assertAlmostEqual(float(y[256,256,0]),255.83333,places=3)
        t['crop_rect']['x']=0
        self.assertFalse(align(x,a,t)[1]['covered'])

    def test_decoded_normal_and_fixed_hdr(self):
        x=np.full((4,4,4),.5)
        y=features(x,'gbuffer_normal_roughness')
        np.testing.assert_allclose(np.linalg.norm(y[...,:3],axis=-1),1)
        np.testing.assert_allclose(y[...,3],.5)
        y=features(np.array([[[0.,1.,49.5]]]),'gbuffer_specular')
        np.testing.assert_allclose(y[0,0],[0,.5,49.5/50.5])

    def test_parent_preservation_control_and_gradients(self):
        torch.manual_seed(347)
        m=RendererRefiner()
        rgb=torch.rand(2,3,32,32)
        parent=torch.rand_like(rgb)
        g=torch.rand(2,5,8,8)
        c=torch.rand(2,17,8,8)
        self.assertTrue(torch.equal(m(rgb,parent,g,c),parent))
        self.assertTrue(torch.equal(m(rgb,parent,g,None),parent))
        with torch.no_grad(): m.head.weight.fill_(.001)
        self.assertTrue(torch.equal(m(rgb,parent,g,c,True),m(rgb,parent,g,c*0,False)))
        self.assertFalse(torch.equal(m(rgb,parent,g,c),m(rgb,parent,g,c*0)))
        out=m(rgb,parent,g,c)
        out.abs().mean().backward()
        self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all() for p in m.parameters()))

    @unittest.skipUnless(torch.cuda.is_available(), 'CUDA unavailable')
    def test_evaluator_metrics_and_sequence_reset(self):
        class FakeCache:
            streams={('validation','a',0):list(range(64)),
                     ('validation','b',0):list(range(64,128))}
            def batch(self,ids):
                rgb=torch.ones(len(ids),3,512,512,device='cuda')
                parent=torch.full_like(rgb,.25 if ids[0]<64 else .75)
                return rgb,torch.zeros_like(rgb),None,None,parent
        metric=evaluate(None,FakeCache(),'validation')
        self.assertAlmostEqual(metric['mae'],.5)
        self.assertAlmostEqual(metric['identity_mae'],1.)
        self.assertEqual(metric['temporal_delta_mae'],0.)
        self.assertEqual(metric['eye_frames'],128)

    @unittest.skipUnless(torch.cuda.is_available(), 'CUDA unavailable')
    def test_full_size_bf16_training_smoke(self):
        m=RendererRefiner().cuda()
        rgb=torch.rand(4,3,512,512,device='cuda')
        parent=torch.rand_like(rgb)
        g=torch.rand(4,5,128,128,device='cuda')
        c=torch.rand(4,17,128,128,device='cuda')
        optimizer=torch.optim.AdamW(m.parameters(),lr=1e-4)
        with torch.autocast('cuda',dtype=torch.bfloat16):
            out=m(rgb,parent,g,c)
            loss=(out-rgb).abs().mean()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(),1.,error_if_nonfinite=True)
        optimizer.step()
        self.assertTrue(torch.equal(m(rgb,parent,g,None),parent))
        self.assertTrue(torch.isfinite(loss))
        print('Refiner parameters:',sum(p.numel() for p in m.parameters()))
        print('Smoke peak allocated GiB:',torch.cuda.max_memory_allocated()/2**30)


if __name__=='__main__':
    torch.set_num_threads(1)
    unittest.main()
