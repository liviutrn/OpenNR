"""Study adaptive Neural Rendering tier handoffs using retained full-eye replays.

This is an offline, read-only study.  It does not load a DLL, change a game
profile, or modify a capture.  Existing reduced-resolution replay outputs are
upsampled to a sampled full-eye grid and compared with three handoff models:

* hard: switch directly from the high-resolution output to the reduced output;
* crossfade: blend the old/high and new/low outputs over N frames;
* residual ramp: grow the reduced residual from the full-resolution source.

The crossfade is intentionally an idealized visual upper bound: a live
implementation needs a motion/depth-reprojected history or a second render.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
DEFAULT_STRENGTH = {50: 0.65, 75: 0.76}


def read_rgba8(path: Path, width: int, height: int) -> np.ndarray:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    return (
        np.frombuffer(payload, dtype=np.uint8)
        .reshape(height, width, 4)[..., :3]
        .astype(np.float32)
        / 255.0
    )


def upsample_residual(
    residual: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    """Approximate the runtime bilinear residual resolve on a sampled grid."""

    result = np.empty((height, width, 3), dtype=np.float32)
    for channel in range(3):
        result[..., channel] = np.asarray(
            Image.fromarray(residual[..., channel], mode="F").resize(
                (width, height), Image.Resampling.BILINEAR
            ),
            dtype=np.float32,
        )
    return result


def mean_abs(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.mean(np.abs(left - right)))


def sample_full(image: np.ndarray, stride: int) -> np.ndarray:
    return image[::stride, ::stride, :]


def load_records(
    replay_root: Path,
    stride: int,
    residual_strength: float | None,
) -> tuple[Path, list[int], int, dict[int, list[dict[str, np.ndarray]]]]:
    manifest_path = replay_root / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"])
    frames = [int(value) for value in manifest["frames"]]
    scale = int(manifest["scale_percent"])
    network_width, network_height = (
        int(value) for value in manifest["network_dimensions"]
    )
    strength = (
        DEFAULT_STRENGTH.get(scale)
        if residual_strength is None
        else residual_strength
    )
    if strength is None:
        raise ValueError(
            f"no current resolve strength is known for scale {scale}; "
            "pass --residual-strength explicitly"
        )

    sample_height = (FULL_HEIGHT + stride - 1) // stride
    sample_width = (FULL_WIDTH + stride - 1) // stride
    records: dict[int, list[dict[str, np.ndarray]]] = {0: [], 1: []}

    for frame_id in frames:
        frame_dir = sequence / "frames" / f"frame_{frame_id:08d}"
        replay_dir = replay_root / f"frame_{frame_id:08d}"
        for eye in (0, 1):
            source = read_rgba8(
                frame_dir / f"input_eye{eye}_full.raw.bin", FULL_WIDTH, FULL_HEIGHT
            )
            high = read_rgba8(
                frame_dir / f"teacher_eye{eye}_full.raw.bin", FULL_WIDTH, FULL_HEIGHT
            )
            small_input = read_rgba8(
                replay_dir / f"input_eye{eye}.rgba", network_width, network_height
            )
            small_output = read_rgba8(
                replay_dir / f"teacher_eye{eye}.rgba", network_width, network_height
            )
            residual = upsample_residual(
                small_output - small_input, sample_width, sample_height
            )
            source_sample = sample_full(source, stride)
            high_sample = sample_full(high, stride)
            full_residual = np.clip(source_sample + residual, 0.0, 1.0)
            tier = np.clip(source_sample + strength * residual, 0.0, 1.0)
            records[eye].append(
                {
                    "high": high_sample,
                    "source": source_sample,
                    "full_residual": full_residual,
                    "tier": tier,
                }
            )

    return sequence, frames, scale, records


def transition_rows(
    records: dict[int, list[dict[str, np.ndarray]]],
    frames: list[int],
    direction: str,
    low_key: str,
    steps: int,
) -> list[dict[str, float | int]]:
    if steps < 1:
        raise ValueError("steps must be positive")
    rows: list[dict[str, float | int]] = []
    frame_count = len(frames)

    # Leave one frame before and one frame after the simulated switch.
    for switch in range(1, frame_count - 1):
        hard_jumps: list[float] = []
        crossfade_jumps: list[float] = []
        residual_ramp_jumps: list[float] = []
        scene_deltas: list[float] = []
        crossfade_quality: list[float] = []
        residual_quality: list[float] = []
        steady_quality: list[float] = []
        temporal_mismatch: list[float] = []

        for eye in (0, 1):
            sequence = records[eye]
            base_key = "high" if direction == "down" else low_key
            target_key = low_key if direction == "down" else "high"
            previous = sequence[switch - 1][base_key]
            hard_jumps.append(mean_abs(sequence[switch][target_key], previous))
            scene_deltas.append(
                mean_abs(sequence[switch]["high"], sequence[switch - 1]["high"])
            )

            previous_crossfade = previous
            for index in range(switch, min(frame_count, switch + steps)):
                alpha = min(1.0, (index - switch + 1) / steps)
                current = sequence[index]
                if direction == "down":
                    crossfade = (
                        (1.0 - alpha) * current["high"]
                        + alpha * current[low_key]
                    )
                    residual_ramp = current["source"] + alpha * (
                        current[low_key] - current["source"]
                    )
                else:
                    crossfade = (
                        (1.0 - alpha) * current[low_key]
                        + alpha * current["high"]
                    )
                    residual_ramp = current["source"] + (
                        (1.0 - alpha) * (current[low_key] - current["source"])
                        + alpha * (current["high"] - current["source"])
                    )

                if index == switch:
                    crossfade_jumps.append(mean_abs(crossfade, previous))
                    residual_ramp_jumps.append(mean_abs(residual_ramp, previous))
                temporal_mismatch.append(
                    mean_abs(
                        crossfade - previous_crossfade,
                        current["high"] - sequence[index - 1]["high"],
                    )
                )
                crossfade_quality.append(mean_abs(crossfade, current["high"]))
                residual_quality.append(mean_abs(residual_ramp, current["high"]))
                steady_quality.append(mean_abs(current[target_key], current["high"]))
                previous_crossfade = crossfade

        def median(key: str) -> float:
            return float(np.median([row[key] for row in rows])) if rows else 0.0

        rows.append(
            {
                "switch_frame": frames[switch],
                "hard_jump_lsb": float(np.mean(hard_jumps) * 255.0),
                "crossfade_first_jump_lsb": float(
                    np.mean(crossfade_jumps) * 255.0
                ),
                "residual_ramp_first_jump_lsb": float(
                    np.mean(residual_ramp_jumps) * 255.0
                ),
                "scene_delta_lsb": float(np.mean(scene_deltas) * 255.0),
                "crossfade_transition_mae_lsb": float(
                    np.mean(crossfade_quality) * 255.0
                ),
                "residual_ramp_transition_mae_lsb": float(
                    np.mean(residual_quality) * 255.0
                ),
                "steady_low_mae_lsb": float(np.mean(steady_quality) * 255.0),
                "crossfade_temporal_mismatch_lsb": float(
                    np.mean(temporal_mismatch) * 255.0
                ),
            }
        )

    if not rows:
        return []
    keys = [key for key in rows[0] if key != "switch_frame"]
    summary = {key: median(key) for key in keys}
    summary["switch_samples"] = len(rows)
    summary["hard_jump_p95_lsb"] = float(
        np.percentile([float(row["hard_jump_lsb"]) for row in rows], 95)
    )
    return [summary]


def summarize(
    replay_root: Path,
    stride: int,
    steps: list[int],
    residual_strength: float | None,
) -> dict[str, object]:
    sequence, frames, scale, records = load_records(
        replay_root, stride, residual_strength
    )
    quality: dict[str, float] = {}
    for key in ("full_residual", "tier", "source"):
        values: list[float] = []
        for eye in (0, 1):
            values.extend(
                mean_abs(record[key], record["high"]) * 255.0
                for record in records[eye]
            )
        quality[f"{key}_mae_lsb"] = float(np.mean(values))

    transitions: dict[str, object] = {}
    for key in ("tier", "full_residual"):
        for direction in ("down", "up"):
            for frame_count in steps:
                rows = transition_rows(
                    records, frames, direction, key, frame_count
                )
                if rows:
                    transitions[
                        f"{direction}_{key}_{frame_count}f"
                    ] = rows[0]

    return {
        "schema": "opennr-adaptive-nr-handoff-study-v1",
        "replay_root": str(replay_root.resolve()),
        "sequence": str(sequence),
        "scale_percent": scale,
        "frames": frames,
        "sampling_stride": stride,
        "quality_lsb": quality,
        "transitions": transitions,
        "scope": (
            "Offline sampled-pixel comparison. The crossfade is an idealized "
            "visual model; no live DLL, game, headset, compositor, or profile "
            "was changed or tested by this tool."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replay-root",
        type=Path,
        action="append",
        required=True,
        help="Existing native scale replay root; repeat for multiple sequences.",
    )
    parser.add_argument("--stride", type=int, default=8)
    parser.add_argument("--steps", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument(
        "--residual-strength",
        type=float,
        default=None,
        help="Override the current per-tier resolve strength for all inputs.",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.stride < 1:
        raise ValueError("stride must be positive")
    if any(value < 1 for value in args.steps):
        raise ValueError("all transition step counts must be positive")

    result = {
        "schema": "opennr-adaptive-nr-handoff-study-bundle-v1",
        "stride": args.stride,
        "steps": args.steps,
        "studies": [
            summarize(root, args.stride, args.steps, args.residual_strength)
            for root in args.replay_root
        ],
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
