"""CPU graph checks only; not a training run or native-resolution acceptance."""
import argparse
from pathlib import Path
import torch
from joint_parent_tone_model import JointParentToneModel
from semantic_tone_head import load_semantic_warm_head
from spatial_tone_head import FrozenParentToneModel
from train_capacity_temporal_student import _load_parent
from prepare_conditioning_pilot import save


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--warm-head', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    torch.set_num_threads(4)
    torch.manual_seed(367)
    head, warm = load_semantic_warm_head(a.warm_head, True, device='cpu')
    parent, *_ = _load_parent(Path(warm['run']['parent']), device='cpu')
    rgb = torch.rand(1, 3, 128, 128)
    guides = torch.rand(1, 5, 32, 32)
    context = torch.rand(1, 8, 24, 24)
    target = torch.rand_like(rgb)
    reference = FrozenParentToneModel(parent, head).eval()
    with torch.no_grad():
        expected, expected_state = reference.forward_temporal(rgb, guides, context)
    model = JointParentToneModel(parent, head).eval()
    actual, state = model.forward_temporal(rgb, guides, context)
    difference = float((actual.detach() - expected).abs().max())
    if difference != 0:
        raise ValueError('Joint wrapper changes initial output')
    state_difference = max(float((x.detach() - y).abs().max()) for x, y in zip(state, expected_state))
    if state_difference != 0:
        raise ValueError('Joint wrapper changes initial recurrent state')
    # A second causal frame tests gradient propagation through the hidden state.
    output, _ = model.forward_temporal(rgb, guides, context, state)
    (output - target).abs().mean().backward()
    groups = {}
    for name, module in [('parent', parent), ('head', head), ('encoder', head.encoder)]:
        grads = [p.grad for p in module.parameters() if p.grad is not None]
        groups[name] = {'tensors_with_gradient': len(grads),
                        'gradient_l1': sum(float(g.abs().sum()) for g in grads),
                        'finite': all(bool(torch.isfinite(g).all()) for g in grads)}
    if not groups['parent']['gradient_l1'] or not groups['head']['gradient_l1']:
        raise ValueError('A trainable branch receives no gradient')
    if groups['encoder']['tensors_with_gradient'] or not all(g['finite'] for g in groups.values()):
        raise ValueError('Frozen encoder or finite-gradient check failed')
    save(a.output, {'scope': __doc__, 'input_size': 128, 'precision': 'CPU FP32',
                    'initial_max_difference': difference, 'initial_state_max_difference': state_difference,
                    'gradients': groups, 'test_data_used': False})
    print(groups)


if __name__ == '__main__':
    main()
