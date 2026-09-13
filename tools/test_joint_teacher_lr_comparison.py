import copy
import unittest
from compare_joint_teacher_lr import compare


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        labels = ['prior','high_effect','renderer_pilot','fresh_session','two_pass']
        self.control = dict(learning_rate=1e-4, trainer_source_sha256='control',
                            test_used=False, cohort_labels=labels, teacher_pass_counts=[1,1,1,1,2])
        self.arm = dict(self.control, learning_rate=3e-4, trainer_source_sha256='arm')
        self.history = [dict(step=0, validation={label:dict(mae=.02,psnr=30.,temporal_delta_mae=.01) for label in labels},
                             sample_schedule_sha256='same', baseline_sample_schedule_sha256='same',
                             hard_draws=0, cohort_draws={label:0 for label in labels})]

    def test_valid_baseline(self):
        result = compare(self.control,self.arm,self.history,copy.deepcopy(self.history))
        self.assertEqual(result['baseline_difference']['prior']['mae'],0.)
        self.assertFalse(result['paired'][0]['arm_all_cohort_mae_eligible'])

    def test_reject_bad_pair(self):
        for field,value in [('sample_schedule_sha256','different'),('hard_draws',1)]:
            changed = copy.deepcopy(self.history)
            changed[0][field] = value
            with self.assertRaises(ValueError):compare(self.control,self.arm,self.history,changed)

    def test_reject_invalid_metrics(self):
        for value in [float('nan'),.03]:
            changed = copy.deepcopy(self.history)
            changed[0]['validation']['prior']['mae'] = value
            with self.assertRaises(ValueError):compare(self.control,self.arm,self.history,changed)

    def test_reject_confound(self):
        with self.assertRaises(ValueError):compare(self.control,dict(self.arm,seed=123),self.history,self.history)


if __name__ == '__main__':unittest.main()
