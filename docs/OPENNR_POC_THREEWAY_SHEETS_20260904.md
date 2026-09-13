# OpenNR POC three-way visual sheets — 2026-09-04

These sheets contain 24 held-out examples, split across three pages. Every row
is the same crop in all three columns.

- **A — MGO VANILLA / NO DLSS:** captured MGO pre-NR input before the Feature
  18/DLSSNR teacher pass. This is not a separate stock-unmodded Skyrim run.
- **B — OUR MODEL 1x (RGB ONLY):** the current best POC checkpoint applied once.
- **C — REAL TEACHER (FEATURE 18):** the captured teacher output for that same
  crop.

The row labels identify the sequence, frame, eye, and crop. The model is the
RGB-only checkpoint because it was the stronger of the two current POC models;
the RGB+depth/MV variant remains available in the earlier four-column sheets.

Sheets are generated under:

    D:\.CODEX_Projects\OpenNR-VR\out\opennr_poc\threeway_labeled

- `threeway_rgb_sheet_01_of_03.png`
- `threeway_rgb_sheet_02_of_03.png`
- `threeway_rgb_sheet_03_of_03.png`
