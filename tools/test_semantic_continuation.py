"""Continuation properties: replayed schedule and uninterrupted optimizer trajectory."""
import copy
import unittest
import numpy as np
import torch
from continue_semantic_parent_training import replay_schedule, restore_sampling, restore_optimizer_rng


class FakeCohort:
    def __init__(self, offset):
        self.offset = offset

    def sample_window(self, rng, batch, window):
        stream = int(rng.integers(0, 7))
        start = int(rng.integers(0, 65 - window))
        return str(stream), 0, (self.offset + stream * 64 + np.arange(start, start + window))[None]


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def fixture(self):
        datasets = [FakeCohort(0), FakeCohort(1000)]
        run = {'probabilities': [.7, .3], 'seed': 812, 'cohort_labels': ['a', 'b']}
        rng, digest, draws = replay_schedule(datasets, run['probabilities'], run['seed'], 17, run['cohort_labels'])
        payload = {'run': run, 'step': 17, 'numpy_rng_state': copy.deepcopy(rng.bit_generator.state)}
        history = [{'step': 17, 'sample_sha256': digest.hexdigest(), 'draws': dict(draws)}]
        return datasets, payload, history, rng, digest, draws

    def test_sampling_future_matches_uninterrupted_rng(self):
        datasets, payload, history, rng, digest, draws = self.fixture()
        restored, rdigest, rdraws = restore_sampling(payload, history, datasets)
        self.assertEqual(digest.hexdigest(), rdigest.hexdigest())
        self.assertEqual(draws, rdraws)
        self.assertTrue(np.array_equal(rng.integers(0, 100000, 100), restored.integers(0, 100000, 100)))

    def test_schedule_and_rng_tampering_rejected(self):
        datasets, payload, history, *_ = self.fixture()
        altered = copy.deepcopy(history)
        altered[0]['draws']['a'] += 1
        with self.assertRaisesRegex(ValueError, 'schedule'):
            restore_sampling(payload, altered, datasets)
        altered = copy.deepcopy(payload)
        altered['numpy_rng_state']['state']['state'] += 1
        with self.assertRaisesRegex(ValueError, 'NumPy'):
            restore_sampling(altered, history, datasets)

    def test_two_group_adamw_resume_is_bit_exact(self):
        def build():
            parent, head = torch.nn.Linear(3, 3), torch.nn.Linear(3, 2)
            optimizer = torch.optim.AdamW([{'params': head.parameters(), 'lr': 1e-4},
                                           {'params': parent.parameters(), 'lr': 1e-5}], weight_decay=1e-4)
            return parent, head, optimizer

        def advance(parent, head, optimizer, rng, count):
            for _ in range(count):
                x = torch.randn(4, 3) * float(rng.uniform(.5, 1.5))
                target = torch.randn(4, 2)
                optimizer.zero_grad(set_to_none=True)
                (head(parent(x)) - target).square().mean().backward()
                torch.nn.utils.clip_grad_norm_(head.parameters(), 1)
                torch.nn.utils.clip_grad_norm_(parent.parameters(), 1)
                optimizer.step()

        torch.manual_seed(731)
        rng = np.random.default_rng(812)
        parent, head, optimizer = build()
        advance(parent, head, optimizer, rng, 3)
        payload = {'parent': copy.deepcopy(parent.state_dict()), 'head': copy.deepcopy(head.state_dict()),
                   'optimizer': copy.deepcopy(optimizer.state_dict()), 'torch_rng_state': torch.get_rng_state(),
                   'numpy_rng_state': copy.deepcopy(rng.bit_generator.state)}
        advance(parent, head, optimizer, rng, 4)
        rp, rh, ro = build()  # Construction deliberately consumes random numbers.
        rp.load_state_dict(payload['parent'])
        rh.load_state_dict(payload['head'])
        restore_optimizer_rng(ro, payload, restore_cuda=False)
        rrng = np.random.default_rng(0)
        rrng.bit_generator.state = payload['numpy_rng_state']
        advance(rp, rh, ro, rrng, 4)
        for left, right in zip(list(parent.parameters()) + list(head.parameters()), list(rp.parameters()) + list(rh.parameters())):
            self.assertTrue(torch.equal(left, right))
        self.assertTrue(all(int(state['step']) == 7 for state in ro.state.values()))


if __name__ == '__main__':
    unittest.main()
