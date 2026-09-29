#!/usr/bin/env python3
"""Probe a reduced-resolution residual wrapper around the public NR graph.

This is an offline speed/quality experiment.  It keeps the recovered weights
and public fused kernels, runs the model on an aspect-preserving 512x512
canvas, then upsamples only the signed low-resolution residual back onto the
original 1920x1080 RGB frame.  It is not a native Feature 18 contract and does
not modify OpenNR or any game profile.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import torch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--rgb-png", type=Path, required=True)
    parser.add_argument("--teacher-png", type=Path)
    parser.add_argument("--reference-npy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--front-mode", choices=("analytic", "dynamic-probe"), default="analytic")
    parser.add_argument("--size", choices=(256, 512), type=int, default=512)
    parser.add_argument("--cuda-graph", action="store_true")
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")

    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    if str(args.backend.resolve()) not in sys.path:
        sys.path.insert(0, str(args.backend.resolve()))
    if str(args.snapshots.resolve()) not in sys.path:
        sys.path.insert(0, str(args.snapshots.resolve()))

    from benchmark_b580_cuda_fast_probe import _event_ms, _fast, _make_probe_noise_tables
    from nr_backend.executor import ResetNR
    from nr_backend.front import reset_front_features
    from nr_backend.weights import load_pinned_records
    from residual_scale_v1 import ResidualScale

    from PIL import Image

    image = Image.open(args.rgb_png.resolve()).convert("RGB").resize((1920, 1080), Image.Resampling.BOX)
    rgb_np = np.asarray(image, dtype=np.float32) / 255.0
    rgb = torch.from_numpy(rgb_np).to(device="cuda", dtype=torch.float32).contiguous()
    motion = torch.zeros((1080, 1920, 2), device="cuda", dtype=torch.float32)

    scale = ResidualScale(args.size, device="cuda")
    with torch.inference_mode():
        _ = scale.prepare(rgb, motion)
        torch.cuda.synchronize()
        prepare_ms, (canvas, low_motion) = _event_ms(lambda: scale.prepare(rgb, motion))
        del low_motion

    model_rgb = canvas.to(dtype=torch.float16).contiguous()
    records = load_pinned_records(args.weights.resolve())
    model = ResetNR(records, None).eval().to("cuda")
    padded_size = (320, 320) if args.size == 256 else (512, 576)
    if args.front_mode == "dynamic-probe":
        from fused_dynamic_front_v1 import forward as dynamic_front

        noise = _make_probe_noise_tables("cuda")
        front_fn = lambda: dynamic_front(
            model_rgb, padded_size=padded_size, seed=args.seed, noise_source=noise
        )
    else:
        front_fn = lambda: reset_front_features(
            model_rgb, padded_size=padded_size, seed=args.seed, noise_source=None
        )

    with torch.inference_mode():
        _ = front_fn()
        torch.cuda.synchronize()
        front_ms, front = _event_ms(front_fn)

    # The public batched adapter creates an immutable LUT during setup; keep
    # that setup outside inference_mode so its version counter remains valid.
    network_times, low_nr, dispatches, provider, adapters, profile = _fast(
        model,
        model_rgb,
        front,
        snapshots=args.snapshots.resolve(),
        branch_mode="batched",
        k8_mode="fp16",
        cuda_graph=args.cuda_graph,
        profile_stages=False,
        warmup=args.warmup,
        iterations=args.iterations,
        # RTX 5070 Ti launch configuration selected by the companion full-frame
        # probe. This remains an offline research setting, not a runtime claim.
        c32_bm=16,
        c32_warps=4,
        c32_stages=1,
        swin_bm=64,
        swin_warps=4,
        swin_stages=1,
        head_bm=64,
        head_warps=4,
        head_stages=1,
        head_normalize=True,
        head_swin=True,
        branch_pair_warps=8,
        branch_project_warps=4,
        branch_project_stages=1,
        branch_pair_bm=None,
        branch_project_bm=32,
        branch_project_bn=None,
        vit_bm=32,
        vit_bn=32,
        vit_large_bn=64,
        vit_stages=1,
        k8_bm=16,
        k8_bn=32,
        k8_warps=4,
        k8_stages=1,
        dense_mode="snapshot",
        dense_bm=16,
        dense_bn=32,
        dense_bk=32,
        dense_bn_small=None,
        dense_warps=4,
        dense_stages=1,
        batched_mode="snapshot",
        batched_bm=16,
        batched_bn=32,
        batched_bk=32,
        batched_warps=4,
        batched_stages=1,
    )

    with torch.inference_mode():
        _ = scale.composite(rgb, canvas, low_nr)
        torch.cuda.synchronize()
        composite_ms, composite = _event_ms(lambda: scale.composite(rgb, canvas, low_nr))

    reference = np.load(args.reference_npy.resolve()).astype(np.float32)
    low_values = composite.detach().float().cpu().numpy()
    raw_values = rgb.detach().float().cpu().numpy()
    if reference.shape != low_values.shape:
        raise ValueError(f"Reference shape {reference.shape} does not match {low_values.shape}")
    low_diff = np.abs(low_values - reference)
    raw_diff = np.abs(raw_values - reference)
    teacher_values = None
    if args.teacher_png is not None:
        teacher_image = Image.open(args.teacher_png.resolve()).convert("RGB").resize(
            (1920, 1080), Image.Resampling.BOX
        )
        teacher_values = np.asarray(teacher_image, dtype=np.float32) / 255.0
        if teacher_values.shape != low_values.shape:
            raise ValueError(f"Teacher shape {teacher_values.shape} does not match {low_values.shape}")
        teacher_diff = np.abs(low_values - teacher_values)
        raw_teacher_diff = np.abs(raw_values - teacher_values)
    else:
        teacher_diff = raw_teacher_diff = None

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "reduced_nr_composite.npy", low_values)
    np.save(output_dir / "raw_rgb.npy", raw_values)
    if teacher_values is not None:
        np.save(output_dir / "teacher_resized.npy", teacher_values)
    preview = Image.fromarray(np.clip(low_values * 255.0 + 0.5, 0, 255).astype(np.uint8), mode="RGB")
    preview.save(output_dir / "reduced_nr_composite.png")
    result = {
        "schema": "opennr-public-b580-residual-scale-probe-v1",
        "status": "passed",
        "source_contract": [1080, 1920, 3],
        "model_contract": [args.size, args.size, 3],
        "active_model_area": [scale.active_h, args.size, 3],
        "front_mode": args.front_mode,
        "cuda_graph": args.cuda_graph,
        "launch_config": {
            "c32": {"bm": 16, "warps": 4, "stages": 1},
            "swin": {"bm": 64, "warps": 4, "stages": 1},
            "multihead": {"bm": 64, "warps": 4, "stages": 1},
            "branches": {"pair_warps": 8, "project_warps": 4,
                          "project_stages": 1, "project_bm": 32},
            "vit": {"bm": 32, "bn": 32, "large_bn": 64, "stages": 1},
            "k8": {"bm": 16, "bn": 32, "warps": 4, "stages": 1},
            "dense": {"mode": "snapshot", "bm": 16, "bn": 32,
                       "bn_small": None, "bk": 32, "warps": 4,
                       "stages": 1},
            "batched": {"mode": "snapshot", "bm": 16, "bn": 32,
                         "bk": 32, "warps": 4, "stages": 1},
        },
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "front_prepare_ms": front_ms,
        "downsample_prepare_ms": prepare_ms,
        "network_ms": network_times,
        "network_median_ms": float(np.median(network_times)),
        "network_p95_ms": float(np.percentile(network_times, 95)),
        "composite_ms": composite_ms,
        "serial_end_to_end_ms_median": float(prepare_ms + front_ms + np.median(network_times) + composite_ms),
        "raw_mae_vs_full_reference": float(raw_diff.mean()),
        "reduced_residual_mae_vs_full_reference": float(low_diff.mean()),
        "raw_psnr_db_vs_full_reference": float(10.0 * np.log10(1.0 / max(np.mean(raw_diff ** 2), 1e-20))),
        "reduced_residual_psnr_db_vs_full_reference": float(10.0 * np.log10(1.0 / max(np.mean(low_diff ** 2), 1e-20))),
        "teacher_comparison": None if teacher_values is None else {
            "source": str(args.teacher_png.resolve()),
            "resize": "BOX to 1920x1080; comparison target is a resized existing native teacher image",
            "raw_mae": float(raw_teacher_diff.mean()),
            "reduced_residual_mae": float(teacher_diff.mean()),
            "raw_psnr_db": float(10.0 * np.log10(1.0 / max(np.mean(raw_teacher_diff ** 2), 1e-20))),
            "reduced_residual_psnr_db": float(10.0 * np.log10(1.0 / max(np.mean(teacher_diff ** 2), 1e-20))),
        },
        "output_finite": bool(np.isfinite(low_values).all()),
        "output_min": float(low_values.min()),
        "output_max": float(low_values.max()),
        "reference_npy": str(args.reference_npy.resolve()),
        "weights": str(args.weights.resolve()),
        "dispatches": dispatches,
        "provider_calls": provider.calls,
        "adapter_calls": {type(adapter).__name__: adapter.calls for adapter in adapters if hasattr(adapter, "calls")},
        "scope": "offline reduced-resolution residual experiment; no temporal, stereo, Feature 18, headset, or VR acceptance",
    }
    (output_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
