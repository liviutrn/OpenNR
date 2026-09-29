"""Prepare isolated native Feature 18 configs at several model resolutions.

The source capture and native guide resources are left untouched.  Reduced
color inputs are written under the requested output directory and the
benchmark consumes them as network-sized input/output textures while keeping
the native guide dimensions.  This measures the network-size lever only; it
does not claim that the resulting small output is a complete full-resolution
resolve.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
GUIDE_WIDTH = 1664
GUIDE_HEIGHT = 1792
SEQUENCE = Path(
    "C:/OpenNR_Captures_FullEyeTemporalStateTranche_20260910/"
    "seq-1789063628889-1"
)
FRAME = SEQUENCE / "frames/frame_00000001"
DEFAULT_SCALES = (100, 90, 85, 75, 50, 33)


def scaled_dimension(value: int, percent: int) -> int:
    return max(1, (value * percent + 50) // 100)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resize_rgba(source: Path, destination: Path, width: int, height: int) -> None:
    expected = FULL_WIDTH * FULL_HEIGHT * 4
    payload = source.read_bytes()
    if len(payload) != expected:
        raise ValueError(f"unexpected RGBA source size for {source}: {len(payload)} != {expected}")
    image = Image.fromarray(
        np.frombuffer(payload, dtype=np.uint8).reshape(FULL_HEIGHT, FULL_WIDTH, 4),
        mode="RGBA",
    )
    # The renderer's ordinary model-input path is a linear texture sample.
    # BOX is a conservative offline approximation for this speed study and
    # keeps the source geometry/alpha relationship deterministic.
    resized = image.resize((width, height), resample=Image.Resampling.BOX)
    destination.write_bytes(resized.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=40)
    parser.add_argument("--scales", type=int, nargs="+", default=list(DEFAULT_SCALES))
    parser.add_argument("--sequence", type=Path, default=SEQUENCE)
    parser.add_argument(
        "--logical-input",
        choices=("network", "guide"),
        default="network",
        help=(
            "NGX logical input dimensions; 'network' preserves the shorthand "
            "study, while 'guide' matches the Skyrim renderer's Feature 18 call."
        ),
    )
    args = parser.parse_args()

    if args.iterations < 1:
        raise ValueError("--iterations must be positive")
    if any(scale not in (33, 50, 75, 85, 90, 100) for scale in args.scales):
        raise ValueError("supported scales are 33, 50, 75, 85, 90 and 100")

    frame = args.sequence / "frames/frame_00000001"
    args.output_root.mkdir(parents=True, exist_ok=True)
    dll = Path(
        "E:/MGO-RC3-fresh/mods/Open Shaders DLSSNR VR 0.5.7 OpenNR/"
        "Shaders/Upscaling/Streamline/nvngx_dlssnr.dll"
    )
    core_candidates = list(Path("C:/Windows/System32/DriverStore/FileRepository").glob("nv_dispi.inf_amd64_*/_nvngx.dll"))
    if len(core_candidates) != 1:
        raise ValueError(f"expected exactly one active NGX core, found {len(core_candidates)}")
    core = core_candidates[0]

    source_inputs = [frame / f"input_eye{eye}_full.raw.bin" for eye in range(2)]
    guide_paths = [
        [frame / f"depth_eye{eye}_full.raw.bin", frame / f"motion_vectors_eye{eye}_full.raw.bin"]
        for eye in range(2)
    ]
    for path in [dll, core, *source_inputs, *(path for pair in guide_paths for path in pair)]:
        if not path.is_file():
            raise FileNotFoundError(path)

    manifest = {
        "study": "native_feature18_resolution_only",
        "source_sequence": str(args.sequence),
        "source_frame": 1,
        "source_color": [FULL_WIDTH, FULL_HEIGHT],
        "native_guides": [GUIDE_WIDTH, GUIDE_HEIGHT],
        "logical_input_mode": args.logical_input,
        "dll": str(dll),
        "dll_sha256": sha256(dll),
        "driver_core": str(core),
        "driver_core_sha256": sha256(core),
        "iterations": args.iterations,
        "warmup_iterations": 20,
        "scales": [],
        "scope": (
            "Isolated native Feature 18 replay. Physical input/output textures use "
            "the selected network dimensions and native depth/motion guides remain "
            "full guide resolution. The logical NGX input dimension is "
            f"{args.logical_input}; this excludes the renderer's downsample and "
            "full-eye resolve passes and is a network-cost study, not a VR "
            "acceptance test."
        ),
    }

    for scale in args.scales:
        width = scaled_dimension(FULL_WIDTH, scale)
        height = scaled_dimension(FULL_HEIGHT, scale)
        directory = args.output_root / f"scale{scale:03d}"
        directory.mkdir(parents=True, exist_ok=True)
        colors = []
        for eye, source in enumerate(source_inputs):
            if scale == 100:
                color = source
            else:
                color = directory / f"input_eye{eye}.rgba"
                resize_rgba(source, color, width, height)
            colors.append(color)

        if args.logical_input == "network":
            header = f"{width} {height} {width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT} {args.iterations}"
        else:
            # Nine-field form: physical color, logical NGX input, output, guides,
            # and iteration count.  The Skyrim renderer supplies the native guide
            # dimensions as the logical first-input dimensions even when the
            # physical model surface is smaller.
            header = (
                f"{width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT} "
                f"{width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT} {args.iterations}"
            )
        lines = [header, str(directory.resolve()), str(dll), str(core)]
        for eye in range(2):
            motion_x = GUIDE_WIDTH * width / FULL_WIDTH
            motion_y = GUIDE_HEIGHT * height / FULL_HEIGHT
            lines.extend(
                [
                    str(colors[eye]),
                    str(guide_paths[eye][0]),
                    str(guide_paths[eye][1]),
                    f"{motion_x:.9f} {motion_y:.9f}",
                ]
            )
        (directory / "inputs.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        scale_record = {
            "scale_percent": scale,
            "network_dimensions": [width, height],
            "logical_input_dimensions": (
                [width, height] if args.logical_input == "network" else [GUIDE_WIDTH, GUIDE_HEIGHT]
            ),
            "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
            "color_inputs": [str(path) for path in colors],
            "color_sha256": [sha256(path) for path in colors],
            "motion_scale": [GUIDE_WIDTH * width / FULL_WIDTH, GUIDE_HEIGHT * height / FULL_HEIGHT],
            "config": str((directory / "inputs.txt").resolve()),
            "output_directory": str(directory.resolve()),
        }
        (directory / "provenance.json").write_text(json.dumps(scale_record, indent=2), encoding="utf-8")
        manifest["scales"].append(scale_record)

    (args.output_root / "study_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
