from pathlib import Path

p = Path("psvr2toolkit/projects/psvr2_openvr_driver_ex/utils/driver_settings.h")
text = p.read_text(encoding="utf-8")
old = "#define SETTING_RENDER_TARGET_HEIGHT_DEFAULT_VALUE 2268"
new = "#define SETTING_RENDER_TARGET_HEIGHT_DEFAULT_VALUE 2174"
if old not in text:
    raise RuntimeError("Expected 2268 render-target default was not found")
p.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Adjusted default renderTargetHeight: 2268 -> 2174")
