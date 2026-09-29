"""Equivalent training graph with sequential parent and batched stateless head."""
from contextlib import nullcontext
import torch
from joint_parent_tone_model import JointParentToneModel
from semantic_tone_head import SemanticToneHead
from spatial_tone_head import FrozenParentToneModel
from train_spatial_tone import frame_objective


def precision_context(rgb, amp):
    return torch.autocast('cuda', dtype=torch.bfloat16) if amp else nullcontext()


def sequential_window_loss(model, rgb, target, guides, context, burn_in=2, amp=True):
    state = previous = None
    losses = []
    for frame in range(rgb.shape[1]):
        with torch.set_grad_enabled(frame >= burn_in), precision_context(rgb, amp):
            pred, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
            error = pred.float() - target[:, frame]
            if frame >= burn_in:
                losses.append(frame_objective(error, previous))
            previous = error if frame >= burn_in else error.detach()
    return torch.stack(losses).mean()


def batched_head_window_loss(model, rgb, target, guides, context, burn_in=2, amp=True):
    """The parent alone owns state; head outputs never feed the next parent step."""
    if type(model) not in (JointParentToneModel, FrozenParentToneModel) or type(model.head) is not SemanticToneHead:
        raise TypeError('Batched training requires the verified stateless semantic-head graph')
    if rgb.shape[0] != 1 or not 1 <= burn_in < rgb.shape[1]:
        raise ValueError('This optimization supports batch1 and a nonempty burn-in')
    state = previous = None
    bases = []
    for frame in range(rgb.shape[1]):
        with torch.set_grad_enabled(frame >= burn_in), precision_context(rgb, amp):
            base, state = model.parent.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
            if frame == burn_in - 1:
                previous = (model.head(rgb[:, frame], base, guides[:, frame], context[:, frame]).float()
                            - target[:, frame]).detach()
            if frame >= burn_in:
                bases.append(base)
    # N=1, so the leading flattened dimension retains causal frame order.
    def flatten(value):
        selected = value[:, burn_in:]
        return selected.reshape(-1, *selected.shape[2:])
    with precision_context(rgb, amp):
        prediction = model.head(flatten(rgb), torch.cat(bases, dim=0), flatten(guides), flatten(context)).float()
        error = prediction - flatten(target)
        losses = []
        for frame in range(error.shape[0]):
            current = error[frame:frame+1]
            losses.append(frame_objective(current, previous))
            previous = current
    return torch.stack(losses).mean()
