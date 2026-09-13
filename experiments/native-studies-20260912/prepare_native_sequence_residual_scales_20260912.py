"""Prepare reset-qualified 16-frame native residual-scale replays.

This is an isolated offline study.  It reduces only the physical color input
for the native Feature 18 call; exact captured depth and motion guides remain
at their native guide dimensions.  The later evaluator composes

    full_input + upsample(native_reduced - reduced_input)

against the saved full-resolution teacher and the source sequence.  No live
Skyrim/MGO files are touched.
"""

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
FRAME_COUNT = 16
SCALES = (75, 65, 50)
SEQUENCE = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789064397821-5"
)
OUTPUT = Path(r"C:\OpenNR\NativeSequenceResidualScales_20260912")
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
        raise ValueError(f"unexpected RGBA source size: {source} ({len(payload)} != {expected})")
    image = Image.fromarray(
        np.frombuffer(payload, dtype=np.uint8).reshape(FULL_HEIGHT, FULL_WIDTH, 4),
        mode="RGBA",
    )
    resized = image.resize((width, height), resample=Image.Resampling.BOX)
    destination.write_bytes(resized.tobytes())


def frame_path(frame_number: int) -> Path:
    return SEQUENCE / "frames" / f"frame_{frame_number:08d}"


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {OUTPUT}")
    if not SEQUENCE.is_dir():
        raise FileNotFoundError(SEQUENCE)
    if not DLL.is_file():
        raise FileNotFoundError(DLL)
    core_candidates = list(
        Path(r"C:\Windows\System32\DriverStore\FileRepository").glob(
            "nv_dispi.inf_amd64_*\\_nvngx.dll"
        )
    )
    if len(core_candidates) != 1:
        raise RuntimeError(f"expected one active NGX core, found {len(core_candidates)}")
    core = core_candidates[0]

    for frame_number in range(1, FRAME_COUNT + 1):
        frame = frame_path(frame_number)
        if not frame.is_dir():
            raise FileNotFoundError(frame)
        for eye in range(2):
            for name in (
                f"input_eye{eye}_full.raw.bin",
                f"depth_eye{eye}_full.raw.bin",
                f"motion_vectors_eye{eye}_full.raw.bin",
                f"teacher_eye{eye}_full.raw.bin",
            ):
                path = frame / name
                if not path.is_file():
                    raise FileNotFoundError(path)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    scale_records: list[dict[str, object]] = []
    for scale in SCALES:
        width = scaled_dimension(FULL_WIDTH, scale)
        height = scaled_dimension(FULL_HEIGHT, scale)
        root = OUTPUT / f"scale{scale:03d}"
        root.mkdir(parents=True, exist_ok=False)
        frame_records: list[dict[str, object]] = []
        for frame_number in range(1, FRAME_COUNT + 1):
            source_frame = frame_path(frame_number)
            replay_frame = root / "frames" / f"frame_{frame_number:08d}"
            replay_frame.mkdir(parents=True, exist_ok=False)
            colors: list[Path] = []
            for eye in range(2):
                destination = replay_frame / f"input_eye{eye}.rgba"
                resize_rgba(
                    source_frame / f"input_eye{eye}_full.raw.bin",
                    destination,
                    width,
                    height,
                )
                colors.append(destination)

            lines = [
                f"{FRAME_COUNT} {width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT} "
                f"{width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT}",
                str(root.resolve()),
                str(DLL),
                str(core),
                "1.70 1.70 1.70 -1.0 0 1 0",
            ]
            for frame_id in range(1, FRAME_COUNT + 1):
                source = frame_path(frame_id)
                replay = root / "frames" / f"frame_{frame_id:08d}"
                lines.append(str(frame_id))
                motion_scale = (
                    f"{GUIDE_WIDTH * width / FULL_WIDTH:.9f} "
                    f"{GUIDE_HEIGHT * height / FULL_HEIGHT:.9f}"
                )
                for eye in range(2):
                    lines.extend(
                        [
                            str(replay / f"input_eye{eye}.rgba"),
                            str(source / f"depth_eye{eye}_full.raw.bin"),
                            str(source / f"motion_vectors_eye{eye}_full.raw.bin"),
                            motion_scale,
                            str(replay / f"teacher_eye{eye}.rgba"),
                        ]
                    )

            config = root / "inputs.txt"
            config.write_text("\n".join(lines) + "\n", encoding="utf-8")
            frame_records.append(
                {
                    "frame_id": frame_number,
                    "source_frame": str(source_frame),
                    "replay_frame": str(replay_frame),
                }
            )

        (root / "provenance.json").write_text(
            json.dumps(
                {
                    "schema": "opennr-native-sequence-residual-scale-input-v1",
                    "source_sequence": str(SEQUENCE),
                    "frame_ids": list(range(1, FRAME_COUNT + 1)),
                    "scale_percent": scale,
                    "network_dimensions": [width, height],
                    "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
                    "logical_input_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
                    "resize": "PIL RGBA BOX approximation for isolated native study",
                    "dll": str(DLL),
                    "dll_sha256": sha256(DLL),
                    "driver_core": str(core),
                    "driver_core_sha256": sha256(core),
                    "history_contract": (
                        "one native process with frame 1 reset=true and contiguous frames 2..16; "
                        "no mid-sequence reset"
                    ),
                    "scope": (
                        "Offline native Feature 18 replay using a face-visible Skyrim sequence. "
                        "Physical color is reduced while captured exact depth and motion remain "
                        "at guide dimensions. This is not live VR validation."
                    ),
                    "frames": frame_records,
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
                "frame_count": FRAME_COUNT,
            }
        )

    manifest = {
        "schema": "opennr-native-sequence-residual-scale-input-v1",
        "source_sequence": str(SEQUENCE),
        "frame_ids": list(range(1, FRAME_COUNT + 1)),
        "full_dimensions": [FULL_WIDTH, FULL_HEIGHT],
        "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
        "scales": scale_records,
        "residual_definition": "full_input + bilinear(native_work - work_input), strength=1.0",
        "note": "Each scale is one reset-qualified 16-frame native process.",
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
