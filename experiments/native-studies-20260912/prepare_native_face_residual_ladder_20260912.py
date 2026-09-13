"""Prepare native reduced-resolution residual runs for an actual Skyrim face frame."""

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
SCALES = (90, 75, 65, 50, 33)
SEQUENCE = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789064397821-5"
)
FRAME_NUMBER = 8
FRAME = SEQUENCE / "frames" / f"frame_{FRAME_NUMBER:08d}"
OUTPUT = Path(r"C:\OpenNR\NativeFaceResidualLadder_20260912")
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


def scaled_dimension(value: int, scale: int) -> int:
    return max(1, (value * scale + 50) // 100)


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
    for eye in range(2):
        for name in (
            f"input_eye{eye}_full.raw.bin",
            f"depth_eye{eye}_full.raw.bin",
            f"motion_vectors_eye{eye}_full.raw.bin",
        ):
            path = FRAME / name
            if not path.is_file():
                raise FileNotFoundError(path)
    if not DLL.is_file():
        raise FileNotFoundError(DLL)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    scale_records = []
    for scale in SCALES:
        width = scaled_dimension(FULL_WIDTH, scale)
        height = scaled_dimension(FULL_HEIGHT, scale)
        root = OUTPUT / f"scale{scale:03d}"
        root.mkdir(parents=True, exist_ok=False)
        colors = []
        for eye in range(2):
            destination = root / f"input_eye{eye}.rgba"
            resize_rgba(FRAME / f"input_eye{eye}_full.raw.bin", destination, width, height)
            colors.append(destination)

        lines = [
            f"1 {width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT} "
            f"{width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT}",
            str(root.resolve()),
            str(DLL),
            str(core),
            "1.70 1.70 1.70 -1.0 0 1 0",
            str(FRAME_NUMBER),
        ]
        motion_scale = f"{GUIDE_WIDTH * width / FULL_WIDTH:.9f} {GUIDE_HEIGHT * height / FULL_HEIGHT:.9f}"
        for eye in range(2):
            lines.extend(
                [
                    str(colors[eye]),
                    str(FRAME / f"depth_eye{eye}_full.raw.bin"),
                    str(FRAME / f"motion_vectors_eye{eye}_full.raw.bin"),
                    motion_scale,
                    str(root / f"teacher_eye{eye}.rgba"),
                ]
            )
        (root / "inputs.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (root / "provenance.json").write_text(
            json.dumps(
                {
                    "schema": "opennr-native-face-residual-ladder-input-v1",
                    "source_sequence": str(SEQUENCE),
                    "source_frame": FRAME_NUMBER,
                    "scale_percent": scale,
                    "network_dimensions": [width, height],
                    "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
                    "logical_input_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
                    "resize": "PIL RGBA BOX approximation for isolated native study",
                    "dll": str(DLL),
                    "dll_sha256": sha256(DLL),
                    "driver_core": str(core),
                    "driver_core_sha256": sha256(core),
                    "scope": (
                        "Single reset-qualified native Feature 18 replay for a face-visible "
                        "Skyrim frame. Physical color is reduced; depth and motion remain "
                        "the captured full-resolution guides. This is not live VR validation."
                    ),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        scale_records.append(
            {
                "scale_percent": scale,
                "root": str(root),
                "width": width,
                "height": height,
            }
        )

    manifest = {
        "schema": "opennr-native-face-residual-ladder-v1",
        "source_sequence": str(SEQUENCE),
        "source_frame": FRAME_NUMBER,
        "full_dimensions": [FULL_WIDTH, FULL_HEIGHT],
        "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
        "scales": scale_records,
        "residual_definition": "full_input + bilinear(native_work - work_input), strength=1.0",
        "note": "Each scale is a separate process and starts from a clean native temporal state.",
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
