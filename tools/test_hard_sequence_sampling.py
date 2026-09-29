import unittest
from types import SimpleNamespace
import numpy as np
from hard_sequence_sampling import replace_sequences


class SamplingTests(unittest.TestCase):
    def test_preserves_eye_start_and_uniform_branch(self):
        cache=SimpleNamespace(streams={('hard',0):np.arange(64)+100,('hard',1):np.arange(64)+200})
        ids=np.arange(8)[None]+3
        original=ids.copy()
        result,count=replace_sequences(cache,[('easy',1)],[3],ids,['hard'],np.random.default_rng(1),1)
        np.testing.assert_array_equal(result,np.arange(203,211)[None])
        np.testing.assert_array_equal(ids,original)
        self.assertEqual(count,1)
        result,count=replace_sequences(cache,[('easy',1)],[3],ids,['hard'],np.random.default_rng(1),0)
        np.testing.assert_array_equal(result,original);self.assertEqual(count,0)


if __name__=='__main__':unittest.main()
