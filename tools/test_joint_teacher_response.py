"""CPU tests for diagnostic selection and optimistic correction bounds."""
import unittest
import torch
from diagnose_joint_teacher_response import correction_bound, ordered_picks


class ResponseTests(unittest.TestCase):
    def test_selection(self):
        self.assertEqual(ordered_picks(['a','b','c','d','e','f']), ['a','d','f'])
        self.assertEqual(ordered_picks(['a']), ['a'])

    def test_black_parent_bound(self):
        parent = torch.zeros(1,3,2,2)
        self.assertAlmostEqual(correction_bound(parent, torch.ones_like(parent))[0], .85, places=6)
        self.assertEqual(correction_bound(parent, torch.ones_like(parent))[1], 1.)
        self.assertEqual(correction_bound(parent, parent), (0.,0.))

    def test_feasible(self):
        parent = torch.full((1,3,2,2), .5)
        self.assertEqual(correction_bound(parent, parent*.4), (0.,0.))


if __name__ == '__main__':
    unittest.main()
