"""Causal feature-history probe using the existing exact native-MV convention."""
import torch
from torch import nn
from torch.nn import functional as F
from warp_temporal_student import MotionWarpTemporalStyleContextStudent


def blend_history(current, previous, current_rgb, previous_rgb, guides, image_size, alpha):
    if not 0 <= alpha <= 1:
        raise ValueError('History blend must be in [0,1]')
    if previous is None or alpha == 0:
        return current
    grid = MotionWarpTemporalStyleContextStudent._motion_grid(guides.float(), current.shape[-2:], image_size)
    warped = F.grid_sample(previous.float(), grid, mode='bilinear', padding_mode='border', align_corners=False)
    warped_rgb = F.grid_sample(previous_rgb.float(), grid, mode='bilinear', padding_mode='border', align_corners=False)
    h, w = current.shape[-2:]
    inside = ((grid[..., 0].abs() <= 1 - 1 / w) & (grid[..., 1].abs() <= 1 - 1 / h))[:, None]
    valid = F.interpolate(guides[:, 4:5].float(), size=(h, w), mode='bilinear', align_corners=False) > .999
    photometric = (current_rgb.float() - warped_rgb).abs().mean(1, keepdim=True) <= .08
    weight = float(alpha) * (inside & valid & photometric).float()
    return (current.float() + weight * (warped - current.float())).to(current.dtype)


class SemanticFeatureHistoryModel(nn.Module):
    """Parent state is unchanged; only this head's own feature history is added."""
    def __init__(self, base, alpha):
        super().__init__()
        self.base = base
        self.alpha = alpha
        self._handle = base.head.semantic_projection.register_forward_pre_hook(self._filter)

    def _filter(self, module, inputs):
        current = inputs[0]
        self._current_rgb = F.adaptive_avg_pool2d(self._rgb.float(), current.shape[-2:])
        filtered = blend_history(current, self._previous, self._current_rgb, self._previous_rgb,
                                 self._guides, self._rgb.shape[-2:], self.alpha)
        self._next_features = filtered.detach()
        return (filtered,)

    @torch.no_grad()
    def forward_temporal(self, rgb, guides, context, state=None):
        parent_state, self._previous, self._previous_rgb = (None, None, None) if state is None else state
        self._rgb, self._guides = rgb, guides
        prediction, parent_state = self.base.forward_temporal(rgb, guides, context, parent_state)
        return prediction, (parent_state, self._next_features, self._current_rgb.detach())

    def close(self):
        self._handle.remove()


def self_test():
    current = torch.ones(1, 3, 16, 16)
    previous = torch.zeros_like(current)
    rgb = torch.zeros_like(current)
    guides = torch.zeros(1, 5, 16, 16)
    guides[:, 4] = 1
    assert blend_history(current, previous, rgb, rgb, guides, (512, 512), 0) is current
    assert blend_history(current, None, rgb, None, guides, (512, 512), .25) is current
    assert torch.equal(blend_history(current, previous, rgb, rgb, guides, (512, 512), .25), current * .75)
    invalid = guides.clone()
    invalid[:, 4] = 0
    assert torch.equal(blend_history(current, previous, rgb, rgb, invalid, (512, 512), .25), current)
    assert torch.equal(blend_history(current, previous, rgb + 1, rgb, guides, (512, 512), .25), current)
    ramp = torch.arange(16).float()[None, None, None, :].expand_as(current).clone()
    guides[:, 1] = .25  # 32 color pixels /128 = one feature pixel at16/512.
    shifted = blend_history(current, ramp, rgb, rgb, guides, (512, 512), 1)
    assert torch.equal(shifted[..., :-1], ramp[..., 1:])
    assert torch.equal(shifted[..., -1], current[..., -1])
    print('PASS: identity, reset, valid blend, invalid-MV/photometric rejection, positive motion and border rejection')


if __name__ == '__main__':
    self_test()
