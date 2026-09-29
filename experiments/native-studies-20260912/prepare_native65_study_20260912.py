"""Prepare the missing 65% native Feature 18 resolution-study input."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
GUIDE_WIDTH = 1664
GUIDE_HEIGHT = 1792
SCALE = 65
SEQUENCE = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789063628889-1"
)
FRAME = SEQUENCE / "frames" / "frame_00000001"
OUTPUT = Path(r"C:\OpenNR\NativeResolutionStudy65Run_20260912")
DLL = Path(
    r"E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.7 OpenNR"
    r"\Shaders\Upscaling\Streamline\nvngx_dlssnr.dll"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scaled_dimension(value: int) -> int:
    return max(1, (value * SCALE + 50) // 100)


def resize_rgba(source: Path, destination: Path, width: int, height: int) -> None:
    expected = FULL_WIDTH * FULL_HEIGHT * 4
    payload = source.read_bytes()
    if len(payload) != expected:
        raise ValueError(f"unexpected RGBA source size: {len(payload)} != {expected}")
    image = Image.fromarray(
        np.frombuffer(payload, dtype=np.uint8).reshape(FULL_HEIGHT, FULL_WIDTH, 4),
        mode="RGBA",
    )
    resized = image.resize((width, height), resample=Image.Resampling.BOX)
    destination.write_bytes(resized.tobytes())


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {OUTPUT}")
    core_candidates = list(
        Path(r"C:\Windows\System32\DriverStore\FileRepository").glob(
            "nv_dispi.inf_amd64_*\\_nvngx.dll"
        )
    )
    if len(core_candidates) != 1:
        raise RuntimeError(f"expected one active NGX core, found {len(core_candidates)}")
    core = core_candidates[0]
    source_inputs = [FRAME / f"input_eye{eye}_full.raw.bin" for eye in range(2)]
    depths = [FRAME / f"depth_eye{eye}_full.raw.bin" for eye in range(2)]
    motions = [FRAME / f"motion_vectors_eye{eye}_full.raw.bin" for eye in range(2)]
    for path in [DLL, core, *source_inputs, *depths, *motions]:
        if not path.is_file():
            raise FileNotFoundError(path)

    width = scaled_dimension(FULL_WIDTH)
    height = scaled_dimension(FULL_HEIGHT)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    colors: list[Path] = []
    for eye, source in enumerate(source_inputs):
        destination = OUTPUT / f"input_eye{eye}.rgba"
        resize_rgba(source, destination, width, height)
        colors.append(destination)

    # Current sequence-harness form: frame count, physical color, logical NGX
    # input, physical output, native guides.  The logical input dimensions
    # remain the native guide dimensions, matching the Skyrim Feature 18 call
    # used in the existing ladder.
    lines = [
        f"1 {width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT} "
        f"{width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT}",
        str(OUTPUT.resolve()),
        str(DLL),
        str(core),
        "1.70 1.70 1.70 -1.0 0 1 0",
        "1",
    ]
    for eye in range(2):
        lines.extend(
            [
                str(colors[eye]),
                str(depths[eye]),
                str(motions[eye]),
                f"{GUIDE_WIDTH * width / FULL_WIDTH:.9f} "
                f"{GUIDE_HEIGHT * height / FULL_HEIGHT:.9f}",
                str(OUTPUT / f"teacher_eye{eye}.rgba"),
            ]
        )
    (OUTPUT / "inputs.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    provenance = {
        "study": "native_feature18_resolution_only_missing_65",
        "source_sequence": str(SEQUENCE),
        "source_frame": 1,
        "scale_percent": SCALE,
        "network_dimensions": [width, height],
        "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
        "logical_input_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
        "iterations": 40,
        "warmup_iterations": 20,
        "resize": "PIL RGBA BOX approximation for isolated speed study",
        "dll": str(DLL),
        "dll_sha256": sha256(DLL),
        "driver_core": str(core),
        "driver_core_sha256": sha256(core),
        "scope": (
            "Native Feature 18 replay with reduced physical color input/output "
            "and full-resolution native depth/motion guides. Excludes renderer "
            "downsample, full-eye resolve, live synchronization, and VR acceptance."
        ),
    }
    (OUTPUT / "provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )
    print(json.dumps(provenance, indent=2))
    print(OUTPUT / "inputs.txt")


if __name__ == "__main__":
    main()
