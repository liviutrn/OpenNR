"""Research wrapper allowing the output loss to adapt the causal parent.

The parent still owns recurrent state. Head-corrected pixels are not fed back;
this changes optimization of the existing graph, not its inference contract.
"""
from pathlib import Path
import torch
from torch import nn


class JointParentToneModel(nn.Module):
    def __init__(self, parent, head):
        super().__init__()
        self.parent = parent.requires_grad_(True)
        self.head = head

    def forward_temporal(self, rgb, guides, context, state=None):
        base, next_state = self.parent.forward_temporal(rgb, guides, context, state)
        return self.head(rgb, base, guides, context), next_state


def load_joint_checkpoint(path):
    from prepare_conditioning_pilot import sha
    from semantic_tone_head import SemanticToneHead
    from train_capacity_temporal_student import _load_parent
    payload = torch.load(path, map_location='cpu', weights_only=False)
    if payload.get('architecture') != 'semantic_joint_parent_v1':
        raise ValueError('Expected joint-parent semantic checkpoint')
    run = payload['run']
    for name, digest in run['source_sha256'].items():
        if sha(Path(__file__).with_name(name)) != digest:
            raise ValueError('Training source changed: ' + name)
    if sha(Path(run['parent'])) != run['parent_sha256']:
        raise ValueError('Original parent changed')
    for root, digest in zip(run['cohorts'], run['cohort_complete_sha256']):
        if sha(Path(root) / 'complete.json') != digest:
            raise ValueError('Cohort changed')
    for relative, digest in run['encoder_provenance']['source_sha256'].items():
        if sha(Path(run['encoder_provenance']['source']) / relative) != digest:
            raise ValueError('Encoder source changed: ' + relative)
    parent, *_ = _load_parent(Path(run['parent']))
    parent.load_state_dict(payload['parent_model'], strict=True)
    head = SemanticToneHead(False).cuda()
    head.load_state_dict(payload['head'], strict=True)
    return JointParentToneModel(parent, head).eval(), payload
