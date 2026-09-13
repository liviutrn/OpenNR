"""Tiny synthetic cache contract tests; never reads experimental holdouts."""
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import sha


class RendererLoaderTests(unittest.TestCase):
    def test_renderer_cache_and_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            rows=[dict(sequence_id='synthetic',eye=e,frame_id=f,history_reset=f==1,split='train')
                  for e in (0,1) for f in range(1,65)]
            (root/'rows.json').write_text(json.dumps(rows))
            shapes={'rgb':(128,2,3,2,2),'guides':(128,5,2,2),'context':(128,8,2,2),'conditioning':(128,17,2,2)}
            for name,shape in shapes.items():np.save(root/(name+'.npy'),np.zeros(shape,dtype=np.float16))
            complete={'schema':'opennr-aligned-renderer-pilot-v1','rows_sha256':sha(root/'rows.json'),
                      'array_sha256':{name:sha(root/(name+'.npy')) for name in shapes}}
            (root/'complete.json').write_text(json.dumps(complete))
            c=AlignedCohort(root,'train')
            self.assertEqual(len(c.streams),2)
            _,_,ids=c.sample_window(np.random.default_rng(1),1,8)
            self.assertEqual(c.load_window(ids)[0].shape,(1,8,3,2,2))
            with self.assertRaises(ValueError):AlignedCohort(root,'test')
            with self.assertRaises(ValueError):AlignedCohort(root,'train',use_legacy_guides=True)
            (root/'rows.json').write_text('[]')
            with self.assertRaises(ValueError):AlignedCohort(root,'train')
            for array in (c.rgb,c.guides,c.context):array._mmap.close()
            for row in rows:row['pass_count']=2
            (root/'rows.json').write_text(json.dumps(rows))
            complete['teacher_pass_count']=2
            complete['rows_sha256']=sha(root/'rows.json')
            (root/'complete.json').write_text(json.dumps(complete))
            with self.assertRaises(ValueError):AlignedCohort(root,'train')
            c2=AlignedCohort(root,'train',expected_pass_count=2)
            self.assertEqual(c2.teacher_pass_count,2)
            self.assertEqual(len(c2.sequence_ids),1)
            for array in (c2.rgb,c2.guides,c2.context):array._mmap.close()


if __name__=='__main__':unittest.main()
