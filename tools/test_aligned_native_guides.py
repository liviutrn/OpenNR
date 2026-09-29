import unittest
import numpy as np
import torch
from aligned_native_guides import native_box,sample_aligned
from aligned_cohort import AlignedCohort
from build_raw_crop_cache import _guide_tensor


class NativeGuideTests(unittest.TestCase):
    def test_analytic_pixel_centers(self):
        g={'source_rect':{'width':1664,'height':1792},'crop_rect':{'x':576,'y':640},'width':512,'height':512}
        c={'source_rect':{'width':2496,'height':2688},'crop_rect':{'x':992,'y':1088,'width':512,'height':512}}
        row={'artifacts':{'depth':g,'motion_vectors':g,'teacher':c}}
        x=np.broadcast_to(np.arange(512,dtype=np.float32)[None,:,None]/512,(512,512,1)).copy()
        mv=np.concatenate((x,-x),-1)
        mask=np.ones((512,512),bool)
        out=sample_aligned(row,x,mask,mv,mask,128).astype(float)
        expected=(256/3+(np.arange(128)+.5)*8/3-.5)/512
        np.testing.assert_allclose(out[0,0],expected,atol=3e-4)
        np.testing.assert_allclose(out[1],-out[2])
        np.testing.assert_equal(out[3:],1)
        np.testing.assert_array_equal(_guide_tensor(row,x,mask,mv,mask,128),out.astype(np.float16))
        legacy=_guide_tensor(row,x,mask,mv,mask,128,legacy_alignment=True)
        old_expected=((np.arange(128)+.5)*4-.5)/512
        np.testing.assert_allclose(legacy[0,0],old_expected,atol=3e-4)
        self.assertFalse(np.array_equal(legacy,out))

    def test_identity_mapping_matches_legacy(self):
        g={'source_rect':{'width':512,'height':512},'crop_rect':{'x':0,'y':0,'width':512,'height':512},'width':512,'height':512}
        row={'artifacts':{'depth':g,'motion_vectors':g,'teacher':g}}
        rng=np.random.default_rng(7)
        depth=rng.random((512,512,1),dtype=np.float32)
        motion=rng.random((512,512,2),dtype=np.float32)-.5
        valid=rng.random((512,512))>.1
        for size in (96,128):
            np.testing.assert_array_equal(_guide_tensor(row,depth,valid,motion,valid,size),
                _guide_tensor(row,depth,valid,motion,valid,size,legacy_alignment=True))

    def test_invalid_samples_masked(self):
        g={'source_rect':{'width':512,'height':512},'crop_rect':{'x':0,'y':0},'width':512,'height':512}
        c={**g,'crop_rect':{'x':0,'y':0,'width':512,'height':512}}
        row={'artifacts':{'depth':g,'motion_vectors':g,'teacher':c}}
        x=np.ones((512,512,1),np.float32)
        valid=np.zeros((512,512),bool)
        np.testing.assert_equal(sample_aligned(row,x,valid,np.repeat(x,2,axis=2),valid,128),0)
        c['crop_rect']['x']=1
        with self.assertRaises(ValueError): native_box(g,c)

    def test_frozen_test_denied_before_io(self):
        with self.assertRaises(ValueError): AlignedCohort('nonexistent','test')


if __name__=='__main__':
    torch.set_num_threads(1)
    unittest.main()
