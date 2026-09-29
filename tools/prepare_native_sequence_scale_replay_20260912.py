"""Prepare a stateful native Feature 18 replay at one reduced model scale.

The resulting config is consumed by the isolated teacher_sequence_bench
executable.  Inputs are resized copies of existing packed RGBA8 Skyrim frames;
depth and motion remain the original exact guide resources.  The native handle
is kept alive while the listed frames are submitted in order, so the output
sequence can retain native temporal state instead of resetting every frame.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


DEFAULT_DLL = Path(
    r"E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.7 OpenNR"
    r"\Shaders\Upscaling\Streamline\nvngx_dlssnr.dll"
)
DEFAULT_CORE_ROOT = Path(r"C:\Windows\System32\DriverStore\FileRepository")
FULL_WIDTH = 2496
FULL_HEIGHT = 2688
GUIDE_WIDTH = 1664
GUIDE_HEIGHT = 1792


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_frames(spec: str) -> list[int]:
    result: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            left, right = (int(value) for value in token.split("-", 1))
            if right < left:
                raise ValueError(f"invalid frame range: {token}")
            result.extend(range(left, right + 1))
        else:
            result.append(int(token))
    if not result or len(set(result)) != len(result):
        raise ValueError("frames must be a non-empty list/range without duplicates")
    return result


def scaled_dimension(value: int, percent: int) -> int:
    return max(1, (value * percent + 50) // 100)


def resized_rgba8(source: Path, destination: Path, width: int, height: int) -> None:
    expected = FULL_WIDTH * FULL_HEIGHT * 4
    payload = source.read_bytes()
    if len(payload) != expected:
        raise ValueError(f"unexpected input size for {source}: {len(payload)} != {expected}")
    image = Image.fromarray(
        np.frombuffer(payload, dtype=np.uint8).reshape(FULL_HEIGHT, FULL_WIDTH, 4),
        mode="RGBA",
    )
    resized = image.resize((width, height), resample=Image.Resampling.BOX)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(resized.tobytes())


def find_core() -> Path:
    candidates = list(DEFAULT_CORE_ROOT.glob("nv_dispi.inf_amd64_*\\_nvngx.dll"))
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one active NGX core, found {len(candidates)}")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", type=Path, required=True)
    parser.add_argument("--frames", required=True, help="comma-separated IDs or inclusive ranges, e.g. 1-2")
    parser.add_argument("--scale", type=int, choices=(33, 50, 75, 85, 90), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dll", type=Path, default=DEFAULT_DLL)
    parser.add_argument("--core", type=Path)
    parser.add_argument("--keep-inputs", action="store_true")
    args = parser.parse_args()

    frame_ids = parse_frames(args.frames)
    scale_width = scaled_dimension(FULL_WIDTH, args.scale)
    scale_height = scaled_dimension(FULL_HEIGHT, args.scale)
    dll = args.dll.resolve()
    core = (args.core or find_core()).resolve()
    if not dll.is_file():
        raise FileNotFoundError(dll)
    if not core.is_file():
        raise FileNotFoundError(core)

    output_root = args.output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    config_lines = [
        f"{len(frame_ids)} {scale_width} {scale_height} {scale_width} {scale_height} "
        f"{scale_width} {scale_height} {GUIDE_WIDTH} {GUIDE_HEIGHT}",
        str(output_root),
        str(dll),
        str(core),
        "2.0 2.0 2.0 -1.0 0 1 0",
    ]

    for frame_id in frame_ids:
        frame_dir = args.sequence / "frames" / f"frame_{frame_id:08d}"
        input_paths = [frame_dir / f"input_eye{eye}_full.raw.bin" for eye in range(2)]
        depth_paths = [frame_dir / f"depth_eye{eye}_full.raw.bin" for eye in range(2)]
        motion_paths = [frame_dir / f"motion_vectors_eye{eye}_full.raw.bin" for eye in range(2)]
        teacher_paths = [frame_dir / f"teacher_eye{eye}_full.raw.bin" for eye in range(2)]
        required = [*input_paths, *depth_paths, *motion_paths, *teacher_paths]
        for path in required:
            if not path.is_file():
                raise FileNotFoundError(path)

        frame_output = output_root / f"frame_{frame_id:08d}"
        frame_output.mkdir(parents=True, exist_ok=True)
        frame_row: dict[str, object] = {
            "frame_id": frame_id,
            "scale_percent": args.scale,
            "network_dimensions": [scale_width, scale_height],
            "source_inputs": [str(path.resolve()) for path in input_paths],
            "source_teachers": [str(path.resolve()) for path in teacher_paths],
            "depth_paths": [str(path.resolve()) for path in depth_paths],
            "motion_paths": [str(path.resolve()) for path in motion_paths],
            "outputs": [],
        }
        config_lines.append(str(frame_id))
        for eye in range(2):
            input_path = frame_output / f"input_eye{eye}.rgba"
            resized_rgba8(input_paths[eye], input_path, scale_width, scale_height)
            output_path = frame_output / f"teacher_eye{eye}.rgba"
            motion_x = GUIDE_WIDTH * scale_width / FULL_WIDTH
            motion_y = GUIDE_HEIGHT * scale_height / FULL_HEIGHT
            config_lines.extend(
                [
                    str(input_path),
                    str(depth_paths[eye].resolve()),
                    str(motion_paths[eye].resolve()),
                    f"{motion_x:.9f} {motion_y:.9f}",
                    str(output_path),
                ]
            )
            frame_row["outputs"].append(
                {
                    "eye": eye,
                    "input": str(input_path),
                    "input_sha256": sha256(input_path),
                    "output": str(output_path),
                    "source_input": str(input_paths[eye].resolve()),
                    "source_teacher": str(teacher_paths[eye].resolve()),
                    "source_teacher_sha256": sha256(teacher_paths[eye]),
                }
            )
        rows.append(frame_row)

    args.config.parent.mkdir(parents=True, exist_ok=True)
    args.config.write_text("\n".join(config_lines) + "\n", encoding="utf-8")
    manifest = {
        "schema": "opennr-native-sequence-scale-replay-input-v1",
        "sequence": str(args.sequence.resolve()),
        "frames": frame_ids,
        "scale_percent": args.scale,
        "network_dimensions": [scale_width, scale_height],
        "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
        "dll": str(dll),
        "dll_sha256": sha256(dll),
        "core": str(core),
        "core_sha256": sha256(core),
        "config": str(args.config.resolve()),
        "rows": rows,
        "resize": "PIL RGBA8 BOX from existing full-eye input; depth/motion remain original exact resources",
        "tuning": {
            "intensity": 2.0,
            "local_tone_strength": 2.0,
            "local_structure_strength": 2.0,
            "skin_structure_strength": -1.0,
            "style": 0,
            "use_auto_mask": True,
            "ui_correction": False,
        },
        "history_contract": "single process, frame order preserved, reset only on first listed frame",
        "keep_inputs": bool(args.keep_inputs),
    }
    (output_root / "input_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": str(args.config.resolve()), "manifest": str(output_root / "input_manifest.json"), "frames": frame_ids, "scale": args.scale}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
