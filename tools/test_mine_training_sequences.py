import unittest
from mine_training_sequences import rank_cohort


class MiningTests(unittest.TestCase):
    def fixture(self):
        return {'train':{'split':'train','sequence_mae':{'a':.01,'b':.03,'c':.02}},
                'training_sequences':['a','b','c'],'validation':{'sequence_mae':{'v':.02}},
                'overlay_complete_sha256':'example'}
    def test_rank_and_no_exclusion(self):
        result=rank_cohort(self.fixture())
        self.assertEqual(result['hard_sequence_ids'],['b'])
        self.assertEqual(len(result['ranked_training_mae']),3)
        self.assertAlmostEqual(result['hard_error_share'],.5)
    def test_overlap_rejected(self):
        data=self.fixture();data['validation']['sequence_mae']['a']=.01
        with self.assertRaises(ValueError):rank_cohort(data)
    def test_nonfinite_rejected(self):
        data=self.fixture();data['train']['sequence_mae']['a']=float('nan')
        with self.assertRaises(ValueError):rank_cohort(data)


if __name__=='__main__':unittest.main()
