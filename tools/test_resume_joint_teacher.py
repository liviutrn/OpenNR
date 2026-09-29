import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import torch
from prepare_conditioning_pilot import save,sha
from resume_joint_teacher import restore_resume


class FakeCache:
    def sample_window(self,rng,batch,window):
        start=int(rng.integers(57));return [],[],np.arange(start,start+window,dtype=np.int64)[None]


class ResumeTests(unittest.TestCase):
    def test_restore_optimizer_and_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';output=root/'output';source.mkdir();output.mkdir()
            head=torch.nn.Linear(2,1);opt=torch.optim.AdamW(head.parameters(),lr=1e-4,weight_decay=1e-4)
            head(torch.ones(1,2)).sum().backward();opt.step();opt.zero_grad()
            run=dict(architecture='stable_unet_teacher_mode',steps=400,seed=359,probabilities=[1.],
                     cohort_labels=['synthetic'],learning_rate=1e-4,trainer_source_sha256='old')
            metrics={'synthetic':dict(mae=.02,psnr=30.,temporal_delta_mae=.01)}
            rng=np.random.default_rng(359);digest=hashlib.sha256();cache=FakeCache()
            for step in range(400):
                j=int(rng.choice(1,p=[1.]));_,_,ids=cache.sample_window(rng,1,8)
                digest.update(np.asarray([j],dtype='<i8').tobytes());digest.update(ids.astype('<i8').tobytes())
            history=[dict(step=0,validation=metrics),dict(step=400,validation=metrics,
                sample_schedule_sha256=digest.hexdigest(),baseline_sample_schedule_sha256=digest.hexdigest(),cohort_draws={'synthetic':400})]
            payload=dict(run=run,step=400,head=head.state_dict(),optimizer=opt.state_dict(),history=history,
                         numpy_rng_state=rng.bit_generator.state,torch_rng_state=torch.get_rng_state(),
                         cuda_rng_state=[],hard_rng_state=np.random.default_rng(10359).bit_generator.state)
            for name in ('last.pt','last_resumable.pt','best_all_cohorts.pt'):torch.save(payload,source/name)
            save(source/'history.json',history);save(source/'status.json',dict(state='complete',best_score=1.))
            save(source/'final_checkpoint_verification.json',dict(test_used=False,step=400,sha256=sha(source/'last.pt'),cohorts={'synthetic':dict(metrics=metrics['synthetic'])}))
            restored=torch.nn.Linear(2,1);restored_opt=torch.optim.AdamW(restored.parameters(),lr=1e-4,weight_decay=1e-4)
            restored_rng=np.random.default_rng(359)
            with patch('torch.cuda.set_rng_state_all'):
                result=restore_resume(source,output,dict(run,steps=800,trainer_source_sha256='new'),restored,restored_opt,[cache],restored_rng,hashlib.sha256(),hashlib.sha256())
            self.assertEqual(result[0],400)
            self.assertEqual(restored_rng.bit_generator.state,rng.bit_generator.state)
            # A further CPU optimizer update must be bit-identical, including moments.
            for model,optimizer in ((head,opt),(restored,restored_opt)):
                model(torch.ones(1,2)).sum().backward();optimizer.step()
            for left,right in zip(head.parameters(),restored.parameters()):self.assertTrue(torch.equal(left,right))
            with patch('torch.cuda.set_rng_state_all'):
                with self.assertRaisesRegex(ValueError,'change recipe'):
                    restore_resume(source,output,dict(run,steps=800,learning_rate=3e-4),restored,restored_opt,[cache],np.random.default_rng(359),hashlib.sha256(),hashlib.sha256())


if __name__=='__main__':unittest.main()
