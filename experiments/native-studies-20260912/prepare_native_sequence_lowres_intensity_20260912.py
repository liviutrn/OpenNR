"""Prepare reset-qualified low-resolution native intensity replays.

This is an offline study only.  It runs the native Feature 18 carrier on the
same retained 16-frame Skyrim sequence at 50% and 33% physical color
resolution, with three native intensity values.  Captured depth and motion
guides remain the exact full-resolution guides.  A later evaluator applies
the post-compositor residual-strength sweep to the saved native outputs.
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
SCALES = (50, 33)
INTENSITIES = (1.0, 1.7, 2.0)
SEQUENCE = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789064397821-5"
)
OUTPUT = Path(r"C:\OpenNR\NativeSequenceLowResIntensity_20260912")
DLL = Path(
    r"E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.7 OpenNR"
    r"\Shaders\Upscaling\Streamline\nvngx_dlssnr.dll"
)
CORE_ROOT = Path(r"C:\Windows\System32\DriverStore\FileRepository")


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


def intensity_label(intensity: float) -> str:
    return f"intensity_{intensity:.2f}".replace(".", "p")


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {OUTPUT}")
    if not SEQUENCE.is_dir():
        raise FileNotFoundError(SEQUENCE)
    if not DLL.is_file():
        raise FileNotFoundError(DLL)
    cores = list(CORE_ROOT.glob("nv_dispi.inf_amd64_*\\_nvngx.dll"))
    if len(cores) != 1:
        raise RuntimeError(f"expected one active NGX core, found {len(cores)}")
    core = cores[0]

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
        scale_root = OUTPUT / f"scale{scale:03d}"
        inputs_root = scale_root / "inputs"
        inputs_root.mkdir(parents=True, exist_ok=False)
        input_frames: dict[int, Path] = {}
        for frame_number in range(1, FRAME_COUNT + 1):
            source_frame = frame_path(frame_number)
            replay_frame = inputs_root / f"frame_{frame_number:08d}"
            replay_frame.mkdir(parents=True, exist_ok=False)
            input_frames[frame_number] = replay_frame
            for eye in range(2):
                resize_rgba(
                    source_frame / f"input_eye{eye}_full.raw.bin",
                    replay_frame / f"input_eye{eye}.rgba",
                    width,
                    height,
                )

        intensity_records: list[dict[str, object]] = []
        for intensity in INTENSITIES:
            label = intensity_label(intensity)
            branch_root = scale_root / label
            branch_root.mkdir(parents=True, exist_ok=False)
            for frame_number in range(1, FRAME_COUNT + 1):
                (branch_root / "frames" / f"frame_{frame_number:08d}").mkdir(
                    parents=True,
                    exist_ok=False,
                )

            lines = [
                f"{FRAME_COUNT} {width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT} "
                f"{width} {height} {GUIDE_WIDTH} {GUIDE_HEIGHT}",
                str(branch_root.resolve()),
                str(DLL),
                str(core),
                f"{intensity:.2f} 1.70 1.70 -1.0 0 1 0",
            ]
            for frame_number in range(1, FRAME_COUNT + 1):
                source = frame_path(frame_number)
                lines.append(str(frame_number))
                replay = input_frames[frame_number]
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
                            str(
                                branch_root
                                / "frames"
                                / f"frame_{frame_number:08d}"
                                / f"teacher_eye{eye}.rgba"
                            ),
                        ]
                    )

            config = branch_root / "inputs.txt"
            config.write_text("\n".join(lines) + "\n", encoding="utf-8")
            record = {
                "intensity": intensity,
                "label": label,
                "scale_percent": scale,
                "network_dimensions": [width, height],
                "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
                "root": str(branch_root.resolve()),
                "config": str(config.resolve()),
                "tuning": {
                    "intensity": intensity,
                    "local_tone_strength": 1.70,
                    "local_structure_strength": 1.70,
                    "skin_structure_strength": -1.0,
                    "style": 0,
                    "use_auto_mask": True,
                    "ui_correction": False,
                },
                "history_contract": (
                    "one native process with frame 1 reset=true and contiguous frames 2..16; "
                    "no mid-sequence reset"
                ),
            }
            (branch_root / "provenance.json").write_text(
                json.dumps(
                    {
                        "schema": "opennr-native-sequence-lowres-intensity-input-v1",
                        "source_sequence": str(SEQUENCE),
                        "frame_ids": list(range(1, FRAME_COUNT + 1)),
                        "scale_percent": scale,
                        "intensity": intensity,
                        "network_dimensions": [width, height],
                        "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
                        "logical_input_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
                        "resize": "PIL RGBA BOX approximation for isolated native study",
                        "dll": str(DLL),
                        "dll_sha256": sha256(DLL),
                        "driver_core": str(core),
                        "driver_core_sha256": sha256(core),
                        "tuning": record["tuning"],
                        "history_contract": record["history_contract"],
                        "scope": (
                            "Offline native Feature 18 replay using a retained face-visible "
                            "Skyrim sequence. Physical color is reduced while captured exact "
                            "depth and motion remain at guide dimensions. This is not live VR "
                            "validation."
                        ),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            intensity_records.append(record)

        scale_records.append(
            {
                "scale_percent": scale,
                "network_dimensions": [width, height],
                "input_root": str(inputs_root.resolve()),
                "intensities": intensity_records,
            }
        )

    manifest = {
        "schema": "opennr-native-sequence-lowres-intensity-input-v1",
        "source_sequence": str(SEQUENCE),
        "frame_ids": list(range(1, FRAME_COUNT + 1)),
        "full_dimensions": [FULL_WIDTH, FULL_HEIGHT],
        "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
        "scales": scale_records,
        "native_intensities": list(INTENSITIES),
        "post_compositor_strengths": [0.5, 1.0, 1.5, 2.0],
        "residual_definition": (
            "full_input + bilinear(native_work - work_input) * strength"
        ),
        "note": (
            "Each scale/intensity branch is one reset-qualified 16-frame native "
            "process. Intensity is a native control; strength is applied later."
        ),
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
