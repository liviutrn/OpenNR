# Dense-feature encoder follow-up: September8,2026

Decision: keep the active DINOv2 experiment intact and record DINOv3 as an untested representation alternative. No new encoder weights were downloaded, no code was executed from the new repository, and no cloud rental was made for this review.

## Verified upstream facts

Meta's official DINOv3 model card lists a21M ViT-S/16 with384-dimensional embeddings and a29M ConvNeXt Tiny, among larger variants. The ViT produces patch features with16-pixel patch size and supports image dimensions divisible by16. Meta reports downstream dense-feature results and recommends frozen features before fine-tuning. These are upstream benchmarks, not OpenNR or DLSS NR measurements. [Official model card](https://github.com/facebookresearch/dinov3/blob/main/MODEL_CARD.md).

The paper introduces Gram anchoring to address degradation of dense feature maps during extended pretraining. This provides a concrete representation hypothesis, without establishing Skyrim color, local contrast or temporal reconstruction quality. [Author paper](https://arxiv.org/abs/2508.10104).

DINOv3 uses a custom license. Its text includes redistribution under the same agreement, providing the license and acknowledging research use. It also contains use restrictions; it should not be described as an Apache-licensed replacement or assumed to have identical redistribution terms to the current encoder. [Repository license, updated August19,2025](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md).

## Local relevance and limits

The active DINOv2 branch has already demonstrated a nonzero useful training response and improvements on five ordinary validation cohorts, with a sixth-cohort regression. Therefore the immediate controlled question is optimization and generalization of that measured signal. The projection-only and conditional joint-parent comparisons address this with the existing local weights and16GiB GPU.

If those fail, a small DINOv3 feature arm could test a different dense representation. It would need pinned source/weights, appropriate attribution, an exact common-start check, a matched feature control, six-cohort/temporal evaluation and direct color/visual comparisons. Its input resolution and patch spacing differ from the current224px DINOv2 setup, so replacing the encoder would not isolate pretraining data alone. There is no verified memory, speed or OpenNR quality result for that proposed arm.
