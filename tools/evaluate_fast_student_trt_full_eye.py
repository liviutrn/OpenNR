"""Evaluate the reduced-work FastStudent TensorRT path on a full-eye Skyrim replay.

This is a bounded offline experiment.  The engine runs on the recorded 50%
work surface, while the original full-resolution RGB frame remains the anchor:

    full_prediction = full_input + upsample(student_work - work_input)

The evaluator keeps the exact captured Feature 18 depth/motion resources,
builds the eight-channel whole-eye context from the full input and guides, and
preserves the recorded reset/stateful frame order.  It reports resident GPU
network time separately from network-plus-resolve time.  Host file I/O and
engine input copies are intentionally outside those timings.

This does not establish live SkyrimVR, stereo synchronization, temporal
quality, or VR frame-budget acceptance.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from benchmark_fast_student_trt import FixedEngine


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
GUIDE_WIDTH = 1664
GUIDE_HEIGHT = 1792


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "median_ms": math.nan, "p95_ms": math.nan, "mean_ms": math.nan}
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": int(array.size),
        "median_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "mean_ms": float(array.mean()),
        "min_ms": float(array.min()),
        "max_ms": float(array.max()),
    }


def _metrics(prediction: torch.Tensor, target: torch.Tensor, source: torch.Tensor) -> dict[str, float | bool]:
    error = prediction.float() - target.float()
    identity_error = source.float() - target.float()
    rmse = float(error.square().mean().sqrt().item())
    mae = float(error.abs().mean().item())
    identity_mae = float(identity_error.abs().mean().item())
    return {
        "mae": mae,
        "rmse": rmse,
        "psnr_db": float(20.0 * np.log10(1.0 / max(rmse, 1e-12))),
        "identity_mae": identity_mae,
        "improvement_vs_identity_mae": identity_mae - mae,
        "finite": bool(torch.isfinite(prediction).all().item()),
    }


def _pair_metrics(
    prediction: torch.Tensor,
    target: torch.Tensor,
    source: torch.Tensor,
    reference: torch.Tensor,
) -> dict[str, float | bool]:
    result = _metrics(prediction, target, source)
    reference_error = prediction.float() - reference.float()
    result.update(
        {
            "mae_vs_reference": float(reference_error.abs().mean().item()),
            "rmse_vs_reference": float(reference_error.square().mean().sqrt().item()),
        }
    )
    return result


def _read_rgba8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    rgba = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)
    rgb = np.ascontiguousarray(rgba[:, :, :3].transpose(2, 0, 1))
    return torch.from_numpy(rgb).float().unsqueeze(0).div_(255.0)


def _read_full_rgb(path: Path) -> torch.Tensor:
    return _read_rgba8(path, FULL_WIDTH, FULL_HEIGHT)


def _read_guides(frame_dir: Path, eye: int) -> torch.Tensor:
    depth_path = frame_dir / f"depth_eye{eye}_full.raw.bin"
    motion_path = frame_dir / f"motion_vectors_eye{eye}_full.raw.bin"
    depth = np.fromfile(depth_path, dtype="<f4")
    motion = np.fromfile(motion_path, dtype="<f2")
    if depth.size != GUIDE_WIDTH * GUIDE_HEIGHT:
        raise ValueError(f"{depth_path} has {depth.size} float32 values; expected {GUIDE_WIDTH * GUIDE_HEIGHT}")
    if motion.size != GUIDE_WIDTH * GUIDE_HEIGHT * 2:
        raise ValueError(
            f"{motion_path} has {motion.size} float16 values; expected {GUIDE_WIDTH * GUIDE_HEIGHT * 2}"
        )
    depth = depth.reshape(GUIDE_HEIGHT, GUIDE_WIDTH)
    motion = motion.reshape(GUIDE_HEIGHT, GUIDE_WIDTH, 2).astype(np.float32)

    # This is the same conversion used by the audited native crop cache:
    # native Feature 18 motion is converted to bounded color-pixel features,
    # while validity remains an explicit pair of channels.
    depth_valid = np.isfinite(depth) & (depth >= 0.0) & (depth <= 1.0)
    motion_valid = np.isfinite(motion).all(axis=2) & (np.abs(motion) <= 0.25).all(axis=2)
    depth = np.where(depth_valid, depth, 0.0).astype(np.float32)
    motion = np.where(motion_valid[:, :, None], motion, 0.0)
    motion[:, :, 0] *= float(FULL_WIDTH)
    motion[:, :, 1] *= float(FULL_HEIGHT)
    motion = np.clip(motion, -128.0, 128.0) / 128.0
    guide = np.concatenate(
        (
            depth[:, :, None],
            motion,
            depth_valid[:, :, None].astype(np.float32),
            motion_valid[:, :, None].astype(np.float32),
        ),
        axis=2,
    )
    return torch.from_numpy(np.ascontiguousarray(guide.transpose(2, 0, 1))).unsqueeze(0)


def _resize(value: torch.Tensor, height: int, width: int) -> torch.Tensor:
    return F.interpolate(value, size=(height, width), mode="bilinear", align_corners=False)


def _context(full_rgb: torch.Tensor, full_guides: torch.Tensor, height: int, width: int) -> torch.Tensor:
    return torch.cat((_resize(full_rgb, height, width), _resize(full_guides, height, width)), dim=1)


def _save_png(path: Path, value: torch.Tensor) -> None:
    array = (
        value.detach()
        .float()
        .clamp(0.0, 1.0)[0]
        .permute(1, 2, 0)
        .mul(255.0)
        .round()
        .to(torch.uint8)
        .cpu()
        .numpy()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array, mode="RGB").save(path)


def _load_frame(
    replay_root: Path,
    sequence: Path,
    frame_id: int,
    eye: int,
    work_width: int,
    work_height: int,
    context_height: int,
    context_width: int,
    device: torch.device,
    dtype: torch.dtype,
) -> dict[str, torch.Tensor]:
    frame_dir = sequence / "frames" / f"frame_{frame_id:08d}"
    replay_dir = replay_root / f"frame_{frame_id:08d}"
    full_input = _read_full_rgb(frame_dir / f"input_eye{eye}_full.raw.bin")
    full_teacher = _read_full_rgb(frame_dir / f"teacher_eye{eye}_full.raw.bin")
    work_input = _read_rgba8(replay_dir / f"input_eye{eye}.rgba", work_width, work_height)
    native_work = _read_rgba8(replay_dir / f"teacher_eye{eye}.rgba", work_width, work_height)
    full_guides = _read_guides(frame_dir, eye)

    work_guides = _resize(full_guides, (GUIDE_HEIGHT + 1) // 2, (GUIDE_WIDTH + 1) // 2)
    context = _context(full_input, full_guides, context_height, context_width)
    return {
        "full_input": full_input.to(device=device, dtype=dtype),
        "full_teacher": full_teacher.to(device=device, dtype=dtype),
        "work_input": work_input.to(device=device, dtype=dtype),
        "native_work": native_work.to(device=device, dtype=dtype),
        "guides": work_guides.to(device=device, dtype=dtype),
        "context": context.to(device=device, dtype=dtype),
    }


def _check_engine_shape(
    engine: FixedEngine,
    work_width: int,
    work_height: int,
    guide_width: int,
    guide_height: int,
    context_width: int,
    context_height: int,
) -> None:
    expected = {
        "rgb": (1, 3, work_height, work_width),
        "guides": (1, 5, guide_height, guide_width),
        "context": (1, 8, context_height, context_width),
    }
    for name, shape in expected.items():
        actual = tuple(engine.engine.get_tensor_shape(name))
        if actual != shape:
            raise ValueError(f"engine {name} shape {actual} does not match expected {shape}")


def _run_eye(
    engine: FixedEngine,
    items: list[dict[str, torch.Tensor]],
    frame_ids: list[int],
    eye: int,
    output_root: Path,
    save_previews: bool,
) -> tuple[list[dict[str, Any]], list[float], list[float]]:
    records: list[dict[str, Any]] = []
    network_events: list[tuple[torch.cuda.Event, torch.cuda.Event]] = []
    resolve_events: list[tuple[torch.cuda.Event, torch.cuda.Event]] = []
    student_outputs: list[torch.Tensor] = []
    work_outputs: list[torch.Tensor] = []

    # All tensors are already resident.  This wait makes the first engine
    # stream operation depend on the loading stream without charging that wait
    # to the measured network/compositor interval.
    engine.stream.wait_stream(torch.cuda.current_stream())
    # Keep the complete sequence on the engine stream.  In particular, do not
    # call .cpu() between frames: a full-eye D2H copy would make the next
    # engine event include an unrelated cross-stream wait.
    for index, item in enumerate(items):
        with torch.cuda.stream(engine.stream):
            engine.rgb.copy_(item["work_input"])
            engine.guides.copy_(item["guides"])
            engine.context_input.copy_(item["context"])
            if index == 0:
                engine.reset_state()

            network_start = torch.cuda.Event(enable_timing=True)
            network_end = torch.cuda.Event(enable_timing=True)
            resolve_start = torch.cuda.Event(enable_timing=True)
            resolve_end = torch.cuda.Event(enable_timing=True)
            network_start.record(engine.stream)
            engine.execute()
            network_end.record(engine.stream)

            resolve_start.record(engine.stream)
            work_residual = engine.prediction - engine.rgb
            full_residual = _resize(
                work_residual,
                item["full_input"].shape[-2],
                item["full_input"].shape[-1],
            )
            student = (item["full_input"] + full_residual).clamp(0.0, 1.0)
            resolve_end.record(engine.stream)
            # These clones stay on the engine stream and are only transferred
            # after the whole sequence has finished.
            student_outputs.append(student.detach().clone())
            work_outputs.append(engine.prediction.detach().clone())
            network_events.append((network_start, network_end))
            resolve_events.append((network_start, resolve_end))
            del student, full_residual, work_residual

    engine.stream.synchronize()
    network_ms = [float(start.elapsed_time(end)) for start, end in network_events]
    resolve_ms = [float(start.elapsed_time(end)) for start, end in resolve_events]

    for index, (frame_id, item, student_gpu, work_gpu) in enumerate(
        zip(frame_ids, items, student_outputs, work_outputs)
    ):
        with torch.inference_mode():
            native_residual = item["native_work"] - item["work_input"]
            native_full_residual = _resize(
                native_residual,
                item["full_input"].shape[-2],
                item["full_input"].shape[-1],
            )
            native_composite = (item["full_input"] + native_full_residual).clamp(0.0, 1.0)
            student_cpu = student_gpu.float().cpu()
            native_composite_cpu = native_composite.float().cpu()
            target_cpu = item["full_teacher"].float().cpu()
            source_cpu = item["full_input"].float().cpu()
            work_prediction = work_gpu.float().cpu()
            work_input_cpu = item["work_input"].float().cpu()
            native_work_cpu = item["native_work"].float().cpu()

        record: dict[str, Any] = {
            "frame_id": frame_id,
            "eye": eye,
            "reset": index == 0,
            "network_ms": network_ms[index],
            "network_plus_resolve_ms": resolve_ms[index],
            "student_full_vs_full_teacher": _metrics(student_cpu, target_cpu, source_cpu),
            "native_scale_composite_vs_full_teacher": _metrics(
                native_composite_cpu, target_cpu, source_cpu
            ),
            "student_full_vs_native_scale_composite": _pair_metrics(
                student_cpu, target_cpu, source_cpu, native_composite_cpu
            ),
            "work_student_vs_native_work": _pair_metrics(
                work_prediction, native_work_cpu, work_input_cpu, native_work_cpu
            ),
        }
        records.append(record)

        if save_previews:
            preview_root = output_root / "previews"
            prefix = preview_root / f"frame_{frame_id:08d}_eye{eye}"
            _save_png(prefix.with_name(prefix.name + "_input.png"), source_cpu)
            _save_png(prefix.with_name(prefix.name + "_teacher.png"), target_cpu)
            _save_png(prefix.with_name(prefix.name + "_native50_residual.png"), native_composite_cpu)
            _save_png(prefix.with_name(prefix.name + "_student.png"), student_cpu)

        del native_composite, native_full_residual, student_gpu, work_gpu

    return records, network_ms, resolve_ms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-size", type=int, default=48)
    parser.add_argument("--save-previews", action="store_true")
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the full-eye TensorRT evaluation")
    if args.context_size < 8:
        raise ValueError("context-size is too small")
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    replay_root = args.replay_root.resolve()
    manifest = json.loads((replay_root / "input_manifest.json").read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"])
    frame_ids = [int(value) for value in manifest["frames"]]
    work_width, work_height = (int(value) for value in manifest["network_dimensions"])
    guide_width = (GUIDE_WIDTH + 1) // 2
    guide_height = (GUIDE_HEIGHT + 1) // 2
    device = torch.device("cuda")
    dtype = torch.float16

    engine = FixedEngine(args.engine.resolve())
    _check_engine_shape(
        engine,
        work_width,
        work_height,
        guide_width,
        guide_height,
        args.context_size,
        args.context_size,
    )

    # Load the complete short sequence before execution.  This keeps file I/O
    # and host-to-device copies outside the reported resident GPU timings.
    by_eye: dict[int, list[dict[str, torch.Tensor]]] = {0: [], 1: []}
    for frame_id in frame_ids:
        for eye in (0, 1):
            by_eye[eye].append(
                _load_frame(
                    replay_root,
                    sequence,
                    frame_id,
                    eye,
                    work_width,
                    work_height,
                    args.context_size,
                    args.context_size,
                    device,
                    dtype,
                )
            )

    all_records: list[dict[str, Any]] = []
    all_network: list[float] = []
    all_resolve: list[float] = []
    eye_summaries: dict[str, Any] = {}
    for eye in (0, 1):
        records, network, resolve = _run_eye(
            engine,
            by_eye[eye],
            frame_ids,
            eye,
            args.output.resolve(),
            args.save_previews,
        )
        all_records.extend(records)
        all_network.extend(network)
        all_resolve.extend(resolve)
        eye_records = [record for record in records if not record["reset"]]
        eye_summaries[str(eye)] = {
            "frames": len(records),
            "steady_frames": len(eye_records),
            "network_ms": _summary(network),
            "network_plus_resolve_ms": _summary(resolve),
            "steady_network_ms": _summary([record["network_ms"] for record in eye_records]),
            "steady_network_plus_resolve_ms": _summary(
                [record["network_plus_resolve_ms"] for record in eye_records]
            ),
            "student_mae_vs_full_teacher": float(
                np.mean([record["student_full_vs_full_teacher"]["mae"] for record in records])
            ),
            "native50_composite_mae_vs_full_teacher": float(
                np.mean(
                    [
                        record["native_scale_composite_vs_full_teacher"]["mae"]
                        for record in records
                    ]
                )
            ),
            "student_vs_native50_composite_mae": float(
                np.mean(
                    [
                        record["student_full_vs_native_scale_composite"]["mae_vs_reference"]
                        for record in records
                    ]
                )
            ),
        }

    result: dict[str, Any] = {
        "schema": "opennr-fast-student-trt-full-eye-evaluation-v1",
        "engine": str(args.engine.resolve()),
        "replay_root": str(replay_root),
        "sequence": str(sequence.resolve()),
        "frames": frame_ids,
        "device": torch.cuda.get_device_name(0),
        "engine_contract": {
            "work_rgb": [1, 3, work_height, work_width],
            "work_guides": [1, 5, guide_height, guide_width],
            "context": [1, 8, args.context_size, args.context_size],
            "full_anchor": [1, 3, FULL_HEIGHT, FULL_WIDTH],
        },
        "guide_contract": "exact captured Feature 18 depth/motion, converted with the audited color-pixel motion scaling and explicit validity channels",
        "context_contract": "full-eye input RGB plus exact full-eye guides, downsampled to the fixed engine context shape",
        "history_contract": "engine reset at first frame of each eye; state carried through contiguous frame order",
        "timing_scope": "resident GPU TensorRT enqueue and enqueue-plus-full-resolution residual resolve; host I/O, input copies, and live Skyrim are excluded",
        "promotion": False,
        "live_runtime_tested": False,
        "eye_summaries": eye_summaries,
        "stereo_serial_network_ms": _summary(all_network),
        "stereo_serial_network_plus_resolve_ms": _summary(all_resolve),
        "records": all_records,
        "notes": [
            "The trained checkpoint was selected on crop-cache validation, not this full-eye replay.",
            "The 50% native composite is a reduced-native residual reference, not a claim of full native-equivalent output.",
            "The current engine is batch-1 and is measured serially across the two eyes; a stereo-batched engine remains a separate optimization study.",
        ],
    }
    payload = json.dumps(result, indent=2)
    (args.output / "result.json").write_text(payload + "\n", encoding="utf-8")
    print(payload, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
