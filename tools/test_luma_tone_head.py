"""CPU smoke tests for the chroma-preserving luminance-gain head."""

import torch

from luma_tone_head import ChromaPreservingLumaToneHead


def main():
    torch.manual_seed(1)
    head = ChromaPreservingLumaToneHead().eval()
    rgb = torch.rand(1, 3, 64, 64)
    parent = torch.rand(1, 3, 64, 64)
    guides = torch.rand(1, 5, 64, 64)
    context = torch.rand(1, 8, 64, 64)
    with torch.no_grad():
        zero = head(rgb, parent, guides, context)
    if not torch.equal(zero, parent):
        raise AssertionError("zero-initialized luma head is not identity")
    head.exact_zero_bypass = False
    head.train()
    prediction = head(rgb, parent, guides, context)
    if not torch.isfinite(prediction).all() or prediction.min() < 0 or prediction.max() > 1:
        raise AssertionError("luma head produced invalid output")
    loss = prediction.square().mean()
    loss.backward()
    if head.affine.weight.grad is None or not torch.isfinite(head.affine.weight.grad).all():
        raise AssertionError("luma head has no finite output gradient")
    if head.luma_affine.weight.grad is None or not torch.isfinite(head.luma_affine.weight.grad).all():
        raise AssertionError("luma branch has no finite output gradient")
    print({"identity": True, "bounded": True, "gradient": True})


if __name__ == "__main__":
    main()
