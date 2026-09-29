"""Measure whether the learned chroma-preserving luminance branch is used."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from prepare_conditioning_pilot import save, sha
from renderer_conditioned_stable import (
    RendererFeatureAlignedCohort,
    load_renderer_checkpoint,
)
from teacher_mode_head import set_teacher_mode


@torch.no_grad()
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--final-checkpoint", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)

    checkpoint = args.run / ("last.pt" if args.final_checkpoint else "best_all_cohorts.pt")
    model, payload = load_renderer_checkpoint(checkpoint)
    head = model.head
    if not hasattr(head, "luma_affine"):
        raise ValueError("Checkpoint is not the chroma-preserving luma architecture")
    set_teacher_mode(head, 1)
    report = {
        "checkpoint": str(checkpoint),
        "sha256": sha(checkpoint),
        "step": payload["step"],
        "test_used": False,
        "luma_weight_l2": float(head.luma_affine.weight.float().norm().item()),
        "luma_weight_max_abs": float(head.luma_affine.weight.float().abs().max().item()),
        "luma_bias_abs": float(head.luma_affine.bias.float().abs().item()),
        "luma_weight_nonzero_fraction": float(
            (head.luma_affine.weight.float().abs() > 1e-9).float().mean().item()
        ),
        "cohorts": {},
    }
    labels = payload["run"]["cohort_labels"]
    roots = payload["run"]["cohorts"]
    modes = payload["run"]["teacher_pass_counts"]
    for label, root, mode in zip(labels, roots, modes):
        cache = RendererFeatureAlignedCohort(Path(root), "validation", expected_pass_count=mode)
        set_teacher_mode(head, mode)
        branch_differences = []
        head_corrections = []
        stream_count = 0
        for selected, arrays in cache.stream_batches(1):
            stream_count += len(selected)
            rgb_np, target_np, guides_np, context_np, conditioning_np = arrays
            del target_np
            rgb, guides, context, conditioning = tuple(
                torch.from_numpy(value).cuda().float()
                for value in (rgb_np, guides_np, context_np, conditioning_np)
            )
            rgb = rgb / 255.0
            state = None
            for frame in range(rgb.shape[1]):
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    base, state = model.parent.forward_temporal(
                        rgb[:, frame], guides[:, frame], context[:, frame], state
                    )
                    head.exact_zero_bypass = False
                    actual = head(
                        rgb[:, frame],
                        base,
                        guides[:, frame],
                        context[:, frame],
                        conditioning[:, frame],
                    )
                    head.exact_zero_bypass = True
                    disabled = head(
                        rgb[:, frame],
                        base,
                        guides[:, frame],
                        context[:, frame],
                        conditioning[:, frame],
                    )
                branch_differences.append(float((actual.float() - disabled.float()).abs().mean().item()))
                head_corrections.append(float((actual.float() - base.float()).abs().mean().item()))
            if len(branch_differences) >= 128:
                break
        head.exact_zero_bypass = False
        report["cohorts"][label] = {
            "schema": cache.complete.get("schema"),
            "streams_sampled": stream_count,
            "frames_sampled": len(branch_differences),
            "learned_branch_vs_disabled_mae": (
                float(np.mean(branch_differences)) if branch_differences else None
            ),
            "actual_head_correction_mae": (
                float(np.mean(head_corrections)) if head_corrections else None
            ),
        }
    save(args.output / "result.json", report)
    save(args.output / "status.json", {"state": "complete", "test_used": False})
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
