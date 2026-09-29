"""Prepare repeated native 65% configs for an intensity-only sweep."""

from __future__ import annotations

import json
from pathlib import Path


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
GUIDE_WIDTH = 1664
GUIDE_HEIGHT = 1792
WORK_WIDTH = 1622
WORK_HEIGHT = 1747
REPEATS = 41  # first call resets the feature; the remaining calls are warmed
CAPTURE = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910"
    r"\seq-1789063628889-1\frames\frame_00000001"
)
SOURCE = Path(r"C:\OpenNR\NativeResolutionStudy65_20260912")
ROOT = Path(r"C:\OpenNR\Native65IntensitySweep_20260912")
DLL = Path(
    r"E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.7 OpenNR"
    r"\Shaders\Upscaling\Streamline\nvngx_dlssnr.dll"
)
CORE_ROOT = Path(r"C:\Windows\System32\DriverStore\FileRepository")
INTENSITIES = (1.0, 1.7, 2.0)


def main() -> None:
    cores = list(CORE_ROOT.glob("nv_dispi.inf_amd64_*\\_nvngx.dll"))
    if len(cores) != 1:
        raise RuntimeError(f"expected one active NGX core, found {len(cores)}")
    core = cores[0]
    required = [
        DLL,
        core,
        SOURCE / "input_eye0.rgba",
        SOURCE / "input_eye1.rgba",
        CAPTURE / "depth_eye0_full.raw.bin",
        CAPTURE / "depth_eye1_full.raw.bin",
        CAPTURE / "motion_vectors_eye0_full.raw.bin",
        CAPTURE / "motion_vectors_eye1_full.raw.bin",
        CAPTURE / "teacher_eye0_full.raw.bin",
        CAPTURE / "teacher_eye1_full.raw.bin",
    ]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)

    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "opennr-native65-intensity-sweep-input-v1",
        "source_frame": str(CAPTURE),
        "work_dimensions": [WORK_WIDTH, WORK_HEIGHT],
        "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
        "repeat_count": REPEATS,
        "intensities": [],
        "scope": (
            "Same 65% physical input/output and exact native guides for every "
            "run. Each run is a single process with reset on the first repeated "
            "frame, then 40 warm native evaluations. Only DLSSNR.Intensity changes."
        ),
    }
    for intensity in INTENSITIES:
        label = f"intensity_{intensity:.2f}".replace(".", "p")
        output = ROOT / label
        if output.exists() and any(output.iterdir()):
            raise FileExistsError(f"refusing non-empty output: {output}")
        output.mkdir(parents=True, exist_ok=True)
        lines = [
            f"{REPEATS} {WORK_WIDTH} {WORK_HEIGHT} {GUIDE_WIDTH} {GUIDE_HEIGHT} "
            f"{WORK_WIDTH} {WORK_HEIGHT} {GUIDE_WIDTH} {GUIDE_HEIGHT}",
            str(output.resolve()),
            str(DLL),
            str(core),
            f"{intensity:.2f} 1.70 1.70 -1.0 0 1 0",
        ]
        for _ in range(REPEATS):
            lines.append("1")
            for eye in range(2):
                lines.extend(
                    [
                        str((SOURCE / f"input_eye{eye}.rgba").resolve()),
                        str((CAPTURE / f"depth_eye{eye}_full.raw.bin").resolve()),
                        str((CAPTURE / f"motion_vectors_eye{eye}_full.raw.bin").resolve()),
                        f"{GUIDE_WIDTH * WORK_WIDTH / FULL_WIDTH:.9f} "
                        f"{GUIDE_HEIGHT * WORK_HEIGHT / FULL_HEIGHT:.9f}",
                        str((output / f"teacher_eye{eye}.rgba").resolve()),
                    ]
                )
        config = output / "inputs.txt"
        config.write_text("\n".join(lines) + "\n", encoding="utf-8")
        record = {
            "intensity": intensity,
            "output": str(output.resolve()),
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
        }
        (output / "provenance.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        manifest["intensities"].append(record)
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
