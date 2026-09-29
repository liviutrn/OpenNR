"""Measure local 5070 Ti latency for the selected direct precision variants.

This is a read-only research benchmark over one fixed validation sequence.  It
does not claim a shipped runtime speedup: the fake-E4M3 hook is Python/PyTorch
instrumentation rather than an optimized TensorRT/FP8 engine.  Results are
reported to distinguish quality evidence from deployment evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time

import numpy as np
import torch

from joint_parent_tone_model import load_joint_checkpoint
from train_fp8_qat import ClampE4M3QAT
from train_residual_target_pair import ResidualView, _sha256_file


def _write_json(path: Path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_candidate(candidate: Path, runtime: Path):
    payload = torch.load(candidate, map_location="cpu", weights_only=False)
    if payload.get("arm") != "direct" or int(payload.get("step", -1)) != 0:
        raise ValueError("Latency benchmark expects the direct step-0 candidate")
    model, _ = load_joint_checkpoint(runtime)
    model.parent.load_state_dict(payload["parent_model"], strict=True)
    model.head.load_state_dict(payload["head"], strict=True)
    return model.cuda().eval()


def _load_sequence(view: ResidualView):
    source = view.sources[0]
    sequence = source.validation.sequence_ids[0]
    indices = np.stack([source.validation.streams[(sequence, 0)], source.validation.streams[(sequence, 1)]])
    local = source.local_from_global(indices)
    rgb = np.array(source.rgb[local, 0], copy=True)
    guides = np.array(source.guides[local], copy=True)
    context = np.array(source.context[local], copy=True)
    return sequence, (
        torch.from_numpy(rgb).cuda(non_blocking=True).float() / 255.0,
        torch.from_numpy(guides).cuda(non_blocking=True).float(),
        torch.from_numpy(context).cuda(non_blocking=True).float(),
    )


def _run_pass(model, tensors, dtype):
    rgb, guides, context = tensors
    state = None
    with torch.no_grad():
        for frame in range(64):
            with torch.autocast(device_type="cuda", dtype=dtype):
                _, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--runtime-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--passes", type=int, default=6)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.passes < 2:
        raise ValueError("At least two timed passes are required")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(output)
    output.mkdir(parents=True, exist_ok=True)
    view = ResidualView(args.view.resolve(), verify_hashes=False)
    sequence, tensors = _load_sequence(view)
    gpu_name = torch.cuda.get_device_name(0)
    result = {
        "schema": "opennr-direct-precision-latency-v1",
        "gpu": gpu_name,
        "candidate": str(args.candidate.resolve()),
        "candidate_sha256": _sha256_file(args.candidate.resolve()),
        "runtime_checkpoint": str(args.runtime_checkpoint.resolve()),
        "view": str(view.root),
        "timed_sequence": sequence,
        "timed_split": "validation",
        "batch_eyes": 2,
        "frames_per_pass": 64,
        "passes": args.passes,
        "variants": {},
        "deployment_boundary": "These are PyTorch hook/autocast timings, not an optimized shipped FP8 engine or live Skyrim VR frame-time proof.",
        "test_used": False,
    }
    variants = [
        ("bf16", torch.bfloat16, False),
        ("fp16", torch.float16, False),
        ("e4m3_clamp448_fake", torch.bfloat16, True),
    ]
    for name, dtype, fake in variants:
        print(f"benchmark {name}", flush=True)
        model = _load_candidate(args.candidate.resolve(), args.runtime_checkpoint.resolve())
        hook = None
        if fake:
            hook = ClampE4M3QAT()
            hook.attach(model)
        try:
            _run_pass(model, tensors, dtype)
            torch.cuda.synchronize()
            samples = []
            for _ in range(args.passes):
                start = torch.cuda.Event(enable_timing=True)
                end = torch.cuda.Event(enable_timing=True)
                start.record()
                _run_pass(model, tensors, dtype)
                end.record()
                end.synchronize()
                samples.append(float(start.elapsed_time(end)))
            per_frame = [value / 64.0 for value in samples]
            result["variants"][name] = {
                "status": "complete",
                "autocast_dtype": str(dtype),
                "fake_e4m3": fake,
                "pass_ms": samples,
                "mean_ms_per_64_frame_pass": statistics.mean(samples),
                "median_ms_per_64_frame_pass": statistics.median(samples),
                "mean_ms_per_frame": statistics.mean(per_frame),
                "median_ms_per_frame": statistics.median(per_frame),
                "mean_fps": 1000.0 / statistics.mean(per_frame),
                "peak_memory_gib": torch.cuda.max_memory_allocated() / 2**30,
                "test_used": False,
            }
        finally:
            if hook is not None:
                hook.remove()
            del model
            torch.cuda.empty_cache()
    _write_json(output / "latency.json", result)
    _write_json(output / "status.json", {"state": "complete", "test_used": False})
    print(json.dumps({"state": "complete", "gpu": gpu_name, "variants": list(result["variants"])}), flush=True)


if __name__ == "__main__":
    main()
