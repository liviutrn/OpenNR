#!/usr/bin/env python3
"""Trace five internal stages of the isolated recovered MLX-DLSS graph.

The graph has procedural operations rather than named ``nn.Module`` stages, so
this tool mirrors its reviewed forward order and records tensors at semantic
encoder/global/decoder boundaries.  It does not modify the upstream clone,
weights, OpenNR caches, labels, student checkpoint, or runtime.

The source and teacher images are both used only as inputs to the stateless
first-frame graph.  The response, stereo, and sparse-frame comparisons are
diagnostics for this graph; they are not native Feature-18 temporal-state
measurements.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_rows(rows: list[dict], split: str, sequence_limit: int, frame_ids: list[int]):
    sequences = []
    seen = set()
    for row in rows:
        if row.get("split") != split:
            continue
        sequence = str(row["sequence_id"])
        if sequence not in seen:
            seen.add(sequence)
            sequences.append(sequence)
    sequences = set(sequences[:sequence_limit])
    return [
        (index, row)
        for index, row in enumerate(rows)
        if row.get("split") == split
        and str(row["sequence_id"]) in sequences
        and int(row["frame_id"]) in frame_ids
    ]


def trace_forward(model, input_value):
    """Compatibility alias for the explicit skip-retaining trace below."""
    return trace_forward_fixed(model, input_value)


def trace_forward_fixed(model, input_value):
    """Trace with the model's three encoder skip tensors retained separately."""
    # The graph's decoder reuses three encoder skips, so this implementation is
    # the exact upstream body with that list retained for the trace points.
    from mlxdlss import model as reference

    adapter = model.weight("block0.layer0.input_adapter_weight")
    value = reference._per_token(lambda tokens: tokens @ adapter, input_value)
    block0_output = model._window(value, 0, head_count=1)
    full_resolution_skip = reference.e4m3_round_trip(block0_output)
    value = reference.e4m3_round_trip(reference.average_pool2(block0_output))
    for index in range(1, 4):
        value = model._window(value, index, head_count=1)
    stages = {"F1_encoder_1_3": value}
    skips = [value]
    value = model._downsample_window(value, 4, head_count=1)

    for regular, transition, head_count in (
        (range(5, 8), 8, 2),
        (range(9, 14), 14, 4),
        (range(15, 22), 22, 8),
    ):
        for index in regular:
            value = model._window(value, index, head_count=head_count)
        skips.append(value)
        value = model._downsample_window(value, transition, head_count=head_count)
        if transition == 8:
            stages["F2_encoder_8"] = value

    for index in range(23, 30):
        value = model._split_window(value, index)
    value = model._split_window(value, 30)
    split_skip = value
    value = reference.pad_spatial_end(value, 8)
    value = reference.downsample(value, weight=model.weight("block30.layer4.weight"))
    value = reference.e4m3_round_trip(value)
    for index in range(31, 39):
        value = model._global(value, index)
    stages["F3_global_31_38"] = value

    value = reference.decoder_input_merge(
        value @ model.weight("block39.layer0.conv_weight"),
        skip=split_skip,
        skip_sine=model.weight("block39.layer0.inp_upsample_sin"),
    )
    value = reference.e4m3_round_trip(value)
    for index in range(40, 48):
        value = model._split_window(value, index)
    value = model._upsample_window(value, skips[3], 48, head_count=8)
    for index in range(49, 56):
        value = model._window(value, index, head_count=8)
    stages["F4_decoder_49_55"] = value

    for transition, regular, skip_index, head_count in (
        (56, range(57, 62), 2, 4),
        (62, range(63, 66), 1, 2),
        (66, range(67, 70), 0, 1),
    ):
        value = model._upsample_window(value, skips[skip_index], transition, head_count=head_count)
        for index in regular:
            value = model._window(value, index, head_count=head_count)

    value = reference.nearest_upsample2_crop(
        value, height=full_resolution_skip.shape[1], width=full_resolution_skip.shape[2]
    )
    value = reference._rows(
        lambda up, skip: up * model.weight("block70.layer0.inp_merge_sin")
        + skip * model.weight("block70.layer0.inp_merge_cos"),
        value,
        full_resolution_skip,
    )
    value = model._window(value, 70, head_count=1)
    stages["F5_pre_output_block70"] = value
    head = reference._per_token(
        lambda tokens: tokens[..., :16] @ model.weight("block70.layer0.out_gain")
        + tokens[..., 16:] @ model.weight("block70.layer0.out_conv_weight"),
        value,
    )
    return head, stages


def stats(tensor) -> dict[str, object]:
    value = tensor.detach()
    value_float = value.float()
    shape = list(value.shape)
    if value.ndim == 3:
        shape_nhwc = [1, *shape]
        height, width = shape[0], shape[1]
    else:
        shape_nhwc = shape
        height, width = shape[1], shape[2]
    return {
        "shape_nhwc": shape_nhwc,
        "batch": int(shape_nhwc[0]),
        "channels": int(value.shape[-1]),
        "spatial": [int(height), int(width)],
        "dtype": str(value.dtype),
        "mean": float(value_float.mean().item()),
        "std": float(value_float.std(unbiased=False).item()),
        "min": float(value_float.min().item()),
        "max": float(value_float.max().item()),
        "memory_size_bytes": int(value.numel() * value.element_size()),
    }


def tensor_delta(left, right) -> dict[str, float]:
    delta = (left.float() - right.float()).abs()
    denominator = left.float().abs().mean().item()
    return {
        "mean_abs": float(delta.mean().item()),
        "relative_to_left_mean_abs": float(delta.mean().item() / max(1e-6, denominator)),
        "rms": float(torch_sqrt_mean_square(delta)),
    }


def torch_sqrt_mean_square(value) -> float:
    return float(value.square().mean().sqrt().item())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--precision", choices=("reference", "fast"), default="fast")
    parser.add_argument("--split", default="validation")
    parser.add_argument("--sequence-limit", type=int, default=2)
    parser.add_argument("--frames", default="1,16,32,48,64")
    parser.add_argument("--local-tone", type=float, default=1.0)
    parser.add_argument("--local-structure", type=float, default=1.0)
    parser.add_argument("--skin-structure", type=float, default=-1.0)
    parser.add_argument("--mask-structure", type=float, default=1.0)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)

    dataset = args.dataset.resolve()
    weights = args.weights.resolve()
    rows = json.loads((dataset / "rows.json").read_text(encoding="utf-8"))
    packed = np.load(dataset / "rgb.npy", mmap_mode="r")
    frame_ids = [int(value) for value in args.frames.split(",") if value.strip()]
    selected = select_rows(rows, args.split, args.sequence_limit, frame_ids)
    if len(selected) < 4:
        raise ValueError(f"selected only {len(selected)} rows")

    from mlxdlss import AutomaticMask, NeuralRenderingPipeline
    import torch

    if not torch.cuda.is_available() and str(args.device).startswith("cuda"):
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    pipeline = NeuralRenderingPipeline.from_safetensors(
        weights, device=args.device, precision=args.precision
    )
    pipeline.model.eval()
    automatic_mask = AutomaticMask(args.skin_structure, args.mask_structure)
    options = {
        "profile": "standard",
        "processing_scale": 1.0,
        "local_tone_strength": args.local_tone,
        "local_structure_strength": args.local_structure,
        "automatic_mask": automatic_mask,
    }

    stage_stats = None
    response_records = []
    stereo_values = defaultdict(list)
    sparse_values = defaultdict(list)
    stage_values = defaultdict(list)
    outputs_by_key = {}
    trace_model_max_abs = 0.0
    started = time.perf_counter()
    with torch.no_grad():
        for row_index, row in selected:
            source = np.asarray(packed[row_index, 0], dtype=np.float32).transpose(1, 2, 0) / 255.0
            target = np.asarray(packed[row_index, 1], dtype=np.float32).transpose(1, 2, 0) / 255.0
            source_prepared = pipeline.prepare(
                source, frame_index=int(row["frame_id"]) - 1, **options
            )
            target_prepared = pipeline.prepare(
                target, frame_index=int(row["frame_id"]) - 1, **options
            )
            source_head, source_stages = trace_forward_fixed(
                pipeline.model,
                torch.from_numpy(source_prepared.features).to(pipeline.device, pipeline.dtype)[None],
            )
            target_head, target_stages = trace_forward_fixed(
                pipeline.model,
                torch.from_numpy(target_prepared.features).to(pipeline.device, pipeline.dtype)[None],
            )
            if len(response_records) == 0:
                source_input = torch.from_numpy(source_prepared.features).to(
                    pipeline.device, pipeline.dtype
                )[None]
                target_input = torch.from_numpy(target_prepared.features).to(
                    pipeline.device, pipeline.dtype
                )[None]
                trace_model_max_abs = max(
                    float((source_head - pipeline.model(source_input)).abs().max().item()),
                    float((target_head - pipeline.model(target_input)).abs().max().item()),
                )
            source_stages = {name: value[0].detach().cpu() for name, value in source_stages.items()}
            target_stages = {name: value[0].detach().cpu() for name, value in target_stages.items()}
            if stage_stats is None:
                stage_stats = {
                    name: {"source_input": stats(value), "teacher_input": stats(target_stages[name])}
                    for name, value in source_stages.items()
                }
            record = {
                "sequence": row["sequence_id"],
                "frame": int(row["frame_id"]),
                "eye": int(row["eye"]),
                "stage_source_to_teacher": {
                    name: tensor_delta(source_stages[name], target_stages[name])
                    for name in source_stages
                },
            }
            response_records.append(record)
            for name in source_stages:
                stage_values[name].append(record["stage_source_to_teacher"][name]["mean_abs"])
            outputs_by_key[(row["sequence_id"], int(row["frame_id"]), int(row["eye"]))] = (
                source_stages,
                target_stages,
            )

    # The selected rows contain paired eyes and sparse frame anchors.  These
    # comparisons use the same first-frame graph and are intentionally labeled
    # as diagnostics rather than temporal-state evidence.
    by_pair = defaultdict(dict)
    for record in response_records:
        by_pair[(record["sequence"], record["frame"])][record["eye"]] = record
    for key, eyes in by_pair.items():
        if 0 not in eyes or 1 not in eyes:
            continue
        left = outputs_by_key[(key[0], key[1], 0)][0]
        right = outputs_by_key[(key[0], key[1], 1)][0]
        for name in left:
            stereo_values[name].append(tensor_delta(left[name], right[name])["mean_abs"])
    by_stream = defaultdict(list)
    for record in response_records:
        by_stream[(record["sequence"], record["eye"])].append(record)
    for key, values in by_stream.items():
        values.sort(key=lambda value: value["frame"])
        for previous, current in zip(values, values[1:]):
            previous_source = outputs_by_key[(key[0], previous["frame"], key[1])][0]
            current_source = outputs_by_key[(key[0], current["frame"], key[1])][0]
            for name in previous_source:
                sparse_values[name].append(
                    tensor_delta(previous_source[name], current_source[name])["mean_abs"]
                )

    def mean(values):
        return float(np.mean(values)) if values else None

    summary = {
        "schema": "opennr-mlx-dlss-stage-trace-v1",
        "dataset": str(dataset),
        "dataset_rows_sha256": sha256(dataset / "rows.json"),
        "weights": str(weights),
        "weights_sha256": sha256(weights),
        "source_commit": args.source_commit,
        "device": str(pipeline.device),
        "precision": args.precision,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "controls": {
            "profile": "standard",
            "local_tone_strength": args.local_tone,
            "local_structure_strength": args.local_structure,
            "skin_structure_strength": args.skin_structure,
            "automatic_mask_structure_strength": args.mask_structure,
        },
        "split": args.split,
        "selected_sequences": sorted({record["sequence"] for record in response_records}),
        "frame_ids": frame_ids,
        "eye_rows": len(response_records),
        "elapsed_seconds": float(time.perf_counter() - started),
        "trace_vs_model_head_max_abs": trace_model_max_abs,
        "stages": stage_stats,
        "stage_source_to_teacher_mean_abs": {
            name: mean(values) for name, values in sorted(stage_values.items())
        },
        "stereo_stage_mean_abs": {
            name: mean(values) for name, values in sorted(stereo_values.items())
        },
        "sparse_frame_stage_mean_abs": {
            name: mean(values) for name, values in sorted(sparse_values.items())
        },
        "diagnostic_scope": (
            "Source-versus-teacher appearance response, left/right response, and "
            "selected-frame response of the stateless first-frame graph. No native "
            "history, motion-vector, contiguous temporal, face-label, headset, or "
            "VR-budget acceptance is established."
        ),
        "records": response_records,
        "selection_recommendation": {
            "candidate_features": ["F2_encoder_8", "F3_global_31_38", "F4_decoder_49_55"],
            "reason": "Representative encoder, global, and decoder boundaries; do not promote to training while Gate A fails.",
            "training_authorized": False,
        },
    }
    args.output.mkdir(parents=True)
    (args.output / "stage_trace.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "eye_rows": summary["eye_rows"],
                "trace_vs_model_head_max_abs": summary["trace_vs_model_head_max_abs"],
                "stages": {
                    name: value["source_input"] for name, value in summary["stages"].items()
                },
                "source_to_teacher_mean_abs": summary["stage_source_to_teacher_mean_abs"],
                "stereo_mean_abs": summary["stereo_stage_mean_abs"],
                "sparse_frame_mean_abs": summary["sparse_frame_stage_mean_abs"],
                "candidate_features": summary["selection_recommendation"]["candidate_features"],
                "training_authorized": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
