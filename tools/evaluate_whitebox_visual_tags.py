#!/usr/bin/env python3
"""Evaluate frozen white-box-proxy students on manually tagged subsets."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

import numpy as np
import torch

from opennr_student import load_student
from train_whitebox_proxy_student import ProxyPatches


def metrics(errors: list[float], baselines: list[float], pixels: int) -> dict[str, float | int]:
    error_sum = float(sum(errors))
    baseline_sum = float(sum(baselines))
    mae = error_sum / max(1, pixels)
    identity_mae = baseline_sum / max(1, pixels)
    return {
        "mae": mae,
        "identity_mae": identity_mae,
        "improvement_pct": 100.0 * (identity_mae - mae) / max(identity_mae, 1e-12),
        "pixels": pixels,
    }


@torch.no_grad()
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--tags", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, action="append", required=True)
    parser.add_argument("--label", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    args = parser.parse_args()

    if len(args.checkpoint) != len(args.label):
        raise ValueError("each --checkpoint requires one matching --label")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for tagged evaluation")
    cache = args.cache.expanduser().resolve()
    tags_path = args.tags.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output: {output}")
    tags = json.loads(tags_path.read_text(encoding="utf-8"))
    if tags.get("schema") != "opennr-whitebox-manual-visual-tags-v1":
        raise ValueError("unexpected visual-tag schema")
    tagged_by_patch: dict[int, set[str]] = {}
    allowed = set(tags.get("allowed_categories", []))
    for sample in tags.get("samples", []):
        patch_index = int(sample["patch_index"])
        values = set(sample.get("tags", []))
        unknown = values - allowed
        if unknown:
            raise ValueError(f"patch {patch_index}: unknown tag(s) {sorted(unknown)}")
        tagged_by_patch[patch_index] = tagged_by_patch.get(patch_index, set()) | values

    dataset = ProxyPatches(cache, args.split)
    model_results: dict[str, dict[str, object]] = {}
    for label, checkpoint in zip(args.label, args.checkpoint):
        model, saved = load_student(checkpoint.expanduser().resolve(), "cuda")
        totals: dict[str, list[float | int]] = defaultdict(lambda: [0.0, 0.0, 0])
        counts: dict[str, int] = defaultdict(int)
        for local_index in range(len(dataset)):
            item = dataset[local_index]
            patch_index = int(item["index"])
            categories = tagged_by_patch.get(patch_index, set())
            if not categories:
                continue
            rgb = item["rgb"].float().unsqueeze(0).cuda() / 255.0
            proxy = item["target"].float().unsqueeze(0).cuda() / 255.0
            native = item["native_teacher"].float().unsqueeze(0).cuda() / 255.0
            guides = item["guides"].float().unsqueeze(0).cuda()
            context = item["context"].float().unsqueeze(0).cuda()
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                prediction = model(rgb, guides, context)
            for category in categories:
                for name, reference in (("proxy", proxy), ("native", native)):
                    error = (prediction.float() - reference.float()).abs().sum().item()
                    baseline = (rgb.float() - reference.float()).abs().sum().item()
                    totals[f"{category}:{name}"][0] += error
                    totals[f"{category}:{name}"][1] += baseline
                    totals[f"{category}:{name}"][2] += reference.numel()
                counts[category] += 1
        categories_result = {}
        for category in sorted(counts):
            proxy_values = totals[f"{category}:proxy"]
            native_values = totals[f"{category}:native"]
            categories_result[category] = {
                "samples": counts[category],
                "proxy": metrics([float(proxy_values[0])], [float(proxy_values[1])], int(proxy_values[2])),
                "native": metrics([float(native_values[0])], [float(native_values[1])], int(native_values[2])),
            }
        model_results[label] = {
            "checkpoint": str(checkpoint.expanduser().resolve()),
            "checkpoint_step": saved.get("step"),
            "architecture": saved.get("config"),
            "categories": categories_result,
        }
        del model
        torch.cuda.empty_cache()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "opennr-whitebox-manual-visual-tag-evaluation-v1",
        "scope": f"manually tagged frozen {args.split} crops; proxy/native/raw comparison; not runtime acceptance",
        "cache": str(cache),
        "tags": str(tags_path),
        "tagging_complete": bool(tags.get("tagging_complete")),
        "models": model_results,
        "test_used_for_tuning": False,
        "live_runtime_tested": False,
        "promotion": False,
    }
    (output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
