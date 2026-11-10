#!/usr/bin/env python3
"""Contract tests for the isolated Cheeky 0.6.3 TriView NR-Lite overlay."""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()

def read(path):
    return (root / path).read_text(encoding="utf-8")

hook = read("src/hooks.cpp")
nr = read("src/dlss_nr.cpp")
before = read("src/dlss_nr_input.cpp")
ui = read("uevr/scripts/cheeky_foveated_dlss.lua")
settings = read("uevr/settings_fields.inc")

checks = {
    "NR Before SR is still intercepted": "NativeNrInputScope nr_input{" in hook and "prepare_dlss_nr_input(frame, settings_for_view" in hook,
    "game native DLSS SR remains the actual fallback": "private_attempted = false;\n    return false;" in hook and "result = original(" in hook,
    "separate-eye view routing retained": "EyeProcessingMode" in settings and "cheeky_processing_allowed_for_view" in hook,
    "source timing/atlas probe": "[CheekyNR][AtlasProbe]" in hook and "frame.view_id" in hook,
    "NR scratch and committed VRAM metrics": "[CheekyNR][VRAM]" in nr and "GetResourceAllocationInfo" in nr,
    "Before-NR copies protected by recording lifetime": "selected->uses.record(frame.command_list)" in before and "complete(input)" in before,
    "one-pass can reclaim pass-2 intermediate": "if (!border_only && !need_second_pass)" in nr and "release(cached.pass_output)" in nr,
    "dormant pass2 NGX features retire safely": "stale_pass.retired = true;" in nr and "collect_retired_views()" in nr,
    "NR Lite retains styles/intensity/depth/motion tuning": all(f'"{k}"' in ui for k in ["NrStyle", "NrIntensity", "NrDepthConvention", "NrMotionScaleXMultiplier", "NrMotionScaleYMultiplier"]),
    "NR Lite retains original and faster model": "NrPreset" in ui,
    "NR Lite retains two-pass NR": "NrPasses" in ui and "nr_extra_pass(2)" in ui,
    "NR Lite retains both templates": all(k in ui for k in ["nr_template_save_1", "nr_template_save_2", "nr_template_load_1", "nr_template_load_2"]),
    "UI no longer displays unrelated FG/eye calibration": "FG status" not in ui and "Stereo and gaze" not in ui and "fg_method_combo" not in ui,
    "stereo atlas is NOT enabled without an input readiness contract": "NR atlas dispatch enabled" not in hook,
}
for label, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'} {label}")
if not all(checks.values()):
    raise SystemExit(1)
print("All NR-Lite contract tests passed")
