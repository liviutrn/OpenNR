"""Measure whether the learned renderer input branch is actually used."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from multilayer_teacher_mode import set_conditioned_teacher_mode as set_teacher_mode
from prepare_conditioning_pilot import save, sha
from renderer_conditioned_stable import (
    RendererFeatureAlignedCohort,
    load_renderer_checkpoint,
)


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
    set_teacher_mode(model.head, 1)
    stem = model.head.stem[0]
    learned = stem.weight[:, -payload["run"]["renderer_conditioning_channels"] :].float()
    report = {
        "checkpoint": str(checkpoint),
        "sha256": sha(checkpoint),
        "step": payload["step"],
        "test_used": False,
        "stem_renderer_weight_l2": float(learned.norm().item()),
        "stem_renderer_weight_max_abs": float(learned.abs().max().item()),
        "stem_renderer_nonzero_fraction": float((learned.abs() > 1e-9).float().mean().item()),
        "cohorts": {},
    }
    labels = payload["run"]["cohort_labels"]
    roots = payload["run"]["cohorts"]
    modes = payload["run"]["teacher_pass_counts"]
    for label, root, mode in zip(labels, roots, modes):
        cache = RendererFeatureAlignedCohort(Path(root), "validation", expected_pass_count=mode)
        if cache.renderer_conditioning is None:
            continue
        set_teacher_mode(model.head, mode)
        differences = []
        actual_norms = []
        stream_count = 0
        for selected, arrays in cache.stream_batches(1):
            stream_count += len(selected)
            rgb_np, target_np, guides_np, context_np, conditioning_np = arrays
            values = [rgb_np, guides_np, context_np, conditioning_np]
            rgb, guides, context, conditioning = tuple(torch.from_numpy(value).cuda().float() for value in values)
            rgb = rgb / 255.0
            state = None
            for frame in range(rgb.shape[1]):
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    base, state = model.parent.forward_temporal(
                        rgb[:, frame], guides[:, frame], context[:, frame], state
                    )
                    actual = model.head(rgb[:, frame], base, guides[:, frame], context[:, frame], conditioning[:, frame])
                    zeros = model.head(
                        rgb[:, frame],
                        base,
                        guides[:, frame],
                        context[:, frame],
                        torch.zeros_like(conditioning[:, frame]),
                    )
                differences.append(float((actual.float() - zeros.float()).abs().mean().item()))
                actual_norms.append(float((actual.float() - base.float()).abs().mean().item()))
            if len(differences) >= 128:
                break
        report["cohorts"][label] = {
            "schema": cache.complete.get("schema"),
            "streams_sampled": stream_count,
            "frames_sampled": len(differences),
            "actual_vs_zero_conditioning_mae": float(np.mean(differences)) if differences else None,
            "actual_head_correction_mae": float(np.mean(actual_norms)) if actual_norms else None,
        }
    save(args.output / "result.json", report)
    save(args.output / "status.json", {"state": "complete", "test_used": False})
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
