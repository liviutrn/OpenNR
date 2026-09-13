"""CPU full-model loss/gradient comparison; no CUDA speed claim."""
import argparse
import copy
from pathlib import Path
import torch
from joint_parent_tone_model import JointParentToneModel
from prepare_conditioning_pilot import save
from semantic_tone_head import load_semantic_warm_head
from semantic_window_batching import sequential_window_loss, batched_head_window_loss
from spatial_tone_head import FrozenParentToneModel
from train_capacity_temporal_student import _load_parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--warm-head', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    torch.set_num_threads(4)
    torch.manual_seed(367)
    head, warm = load_semantic_warm_head(a.warm_head, True, device='cpu')
    parent, *_ = _load_parent(Path(warm['run']['parent']), device='cpu')
    # Nonzero semantic projection ensures encoder-feature batching is exercised.
    with torch.no_grad():
        head.semantic_projection.weight.normal_(std=.001)
    inputs = (torch.rand(1, 8, 3, 128, 128), torch.rand(1, 8, 3, 128, 128),
              torch.rand(1, 8, 5, 32, 32), torch.rand(1, 8, 8, 24, 24))
    result = {'scope': __doc__, 'precision': 'CPU FP32', 'input_size': 128, 'window': 8,
              'burn_in': 2, 'test_data_used': False, 'modes': {}}
    for name, wrapper in [('frozen_parent', FrozenParentToneModel), ('joint_parent', JointParentToneModel)]:
        reference = wrapper(copy.deepcopy(parent), copy.deepcopy(head)).train()
        candidate = wrapper(copy.deepcopy(parent), copy.deepcopy(head)).train()
        sequential = sequential_window_loss(reference, *inputs, amp=False)
        sequential.backward()
        batched = batched_head_window_loss(candidate, *inputs, amp=False)
        batched.backward()
        maximum, numerator, denominator, count = 0., 0., 0., 0
        for (key, left), (other, right) in zip(reference.named_parameters(), candidate.named_parameters()):
            if key != other or (left.grad is None) != (right.grad is None):
                raise ValueError('Gradient ownership changed: ' + key)
            if left.grad is not None:
                difference = left.grad - right.grad
                maximum = max(maximum, float(difference.abs().max()))
                numerator += float(difference.double().square().sum())
                denominator += float(left.grad.double().square().sum())
                count += 1
        entry = {'sequential_loss': float(sequential.detach()), 'batched_loss': float(batched.detach()),
                 'loss_absolute_difference': abs(float(sequential.detach() - batched.detach())),
                 'gradient_max_absolute_difference': maximum,
                 'gradient_relative_l2_difference': (numerator / max(denominator, 1e-30))**.5,
                 'gradient_tensors': count}
        result['modes'][name] = entry
        save(a.output, result)
        if entry['loss_absolute_difference'] > 1e-6 or entry['gradient_relative_l2_difference'] > 1e-4:
            raise ValueError('Batched head changed CPU training math: ' + str(entry))
        del reference, candidate, sequential, batched
    print(result)


if __name__ == '__main__':
    main()
