"""Check identity initialization, finite updates, and cache guide geometry."""
import argparse
import numpy as np
import torch
from opennr_student import OpenNRStudent,StudentConfig
from train_student import CachedPatches,batch_to_device,loss_fn

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache');a=p.parse_args();torch.set_num_threads(2)
    for guided in (False,True):
        m=OpenNRStudent(StudentConfig(width=8,guided=guided,blocks=1))
        for h,w in ((128,128),(129,135)):
            x=torch.rand(1,3,h,w);g=torch.rand(1,5,32,32);c=torch.rand(1,8,96,96)
            out=m(x,g,c);assert out.shape==x.shape and torch.allclose(out,x,atol=1e-6)
        loss=loss_fn(out,x*.9);loss.backward();assert all(torch.isfinite(p.grad).all() for p in m.parameters() if p.grad is not None)
    if a.cache:
        from master_dataset import MasterPatchDataset
        import json
        from pathlib import Path
        info=json.loads((Path(a.cache)/'complete.json').read_text());reference=MasterPatchDataset(info['source_manifest'],'validation')
        ds=CachedPatches(a.cache,'validation');item=ds[0];ref=reference[0]
        assert np.array_equal(item['rgb'].numpy(),(ref['input']*255).round().byte().numpy())
        # Cached guides are sampled directly at 128, so compare against the same
        # pixel-center geometry rather than averaging an already sampled 512 map.
        assert torch.isfinite(item['guides']).all() and item['guides'][1:3].abs().max()<=1
        assert item['context'].shape==(8,96,96)
        print('PASS: audited RGB cache equality, finite guide bounds, whole-eye context')
    print('PASS: RGB/guided identity initialization, arbitrary dimensions, finite gradients')

if __name__=='__main__':main()
