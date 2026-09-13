"""Prepare a face-frame native 50% intensity sweep."""

from __future__ import annotations

import json
from pathlib import Path


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
WORK_WIDTH = 1248
WORK_HEIGHT = 1344
GUIDE_WIDTH = 1664
GUIDE_HEIGHT = 1792
FRAME = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910"
    r"\seq-1789064397821-5\frames\frame_00000008"
)
SOURCE = Path(r"C:\OpenNR\NativeFaceResidualLadder_20260912\scale050")
ROOT = Path(r"C:\OpenNR\NativeFace50IntensityResetSweep_20260912")
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
    for path in (
        DLL,
        core,
        SOURCE / "input_eye0.rgba",
        SOURCE / "input_eye1.rgba",
        FRAME / "depth_eye0_full.raw.bin",
        FRAME / "depth_eye1_full.raw.bin",
        FRAME / "motion_vectors_eye0_full.raw.bin",
        FRAME / "motion_vectors_eye1_full.raw.bin",
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if ROOT.exists() and any(ROOT.iterdir()):
        raise FileExistsError(f"refusing non-empty output: {ROOT}")
    ROOT.mkdir(parents=True, exist_ok=True)
    records = []
    for intensity in INTENSITIES:
        label = f"intensity_{intensity:.2f}".replace(".", "p")
        output = ROOT / label
        output.mkdir(parents=True, exist_ok=False)
        lines = [
            f"1 {WORK_WIDTH} {WORK_HEIGHT} {GUIDE_WIDTH} {GUIDE_HEIGHT} "
            f"{WORK_WIDTH} {WORK_HEIGHT} {GUIDE_WIDTH} {GUIDE_HEIGHT}",
            str(output.resolve()),
            str(DLL),
            str(core),
            f"{intensity:.2f} 1.70 1.70 -1.0 0 1 0",
            "8",
        ]
        for eye in range(2):
            lines.extend(
                [
                    str((SOURCE / f"input_eye{eye}.rgba").resolve()),
                    str((FRAME / f"depth_eye{eye}_full.raw.bin").resolve()),
                    str((FRAME / f"motion_vectors_eye{eye}_full.raw.bin").resolve()),
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
            "source_frame": str(FRAME),
            "work_dimensions": [WORK_WIDTH, WORK_HEIGHT],
            "scope": "one reset-qualified native call on the face-visible Skyrim frame",
        }
        (output / "provenance.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        records.append(record)
    manifest = {
        "schema": "opennr-native-face50-intensity-reset-sweep-v1",
        "source_frame": str(FRAME),
        "work_dimensions": [WORK_WIDTH, WORK_HEIGHT],
        "guide_dimensions": [GUIDE_WIDTH, GUIDE_HEIGHT],
        "intensities": records,
        "purpose": "face visual verification of model intensity versus residual strength",
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
