"""Verify projection-only checkpoints preserve all warm U-Net and encoder tensors."""
import argparse
from pathlib import Path
import torch
from prepare_conditioning_pilot import save, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--encoder-reference', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    torch.set_num_threads(4)
    payload = torch.load(a.checkpoint, map_location='cpu', weights_only=False)
    run, head = payload['run'], payload['head']
    if not run.get('projection_only') or run['trainable_head_parameters'] != 24640:
        raise ValueError('Expected projection-only training contract')
    warm_path = Path(run['warm_head'])
    if sha(warm_path) != run['warm_head_sha256']:
        raise ValueError('Warm checkpoint changed')
    warm = torch.load(warm_path, map_location='cpu', weights_only=False)['head']
    reference = torch.load(a.encoder_reference, map_location='cpu', weights_only=False)
    encoder = {k: v for k, v in reference['head'].items() if k.startswith('encoder.')}
    if reference['run']['pretrained_encoder'] != run['pretrained_encoder']:
        raise ValueError('Encoder reference arm mismatch')
    if reference['run']['seed'] != run['seed']:
        raise ValueError('Encoder reference seed mismatch')
    unequal_warm = [k for k, v in warm.items() if not torch.equal(v, head[k])]
    unequal_encoder = [k for k, v in encoder.items() if not torch.equal(v, head[k])]
    result = {'checkpoint': str(a.checkpoint.resolve()), 'sha256': sha(a.checkpoint),
              'step': payload['step'], 'warm_sha256': sha(warm_path),
              'encoder_reference': str(a.encoder_reference.resolve()),
              'encoder_reference_sha256': sha(a.encoder_reference),
              'warm_tensors_checked': len(warm), 'encoder_tensors_checked': len(encoder),
              'unequal_warm': unequal_warm, 'unequal_encoder': unequal_encoder,
              'projection_weight_l2': float(head['semantic_projection.weight'].norm()),
              'projection_bias_l2': float(head['semantic_projection.bias'].norm()),
              'verified': not unequal_warm and not unequal_encoder,
              'source_sha256': sha(Path(__file__))}
    save(a.output, result)
    if not result['verified']:
        raise ValueError('Frozen tensors changed')
    print(result)


if __name__ == '__main__':
    main()
