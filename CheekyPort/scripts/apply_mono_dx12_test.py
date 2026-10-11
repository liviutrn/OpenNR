#!/usr/bin/env python3
"""Exercise real WARP DX12 source stamping and both OpenXR submissions for shared Mono."""
import argparse
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("root",type=Path)
root=p.parse_args().root.resolve()
def rep(path,old,new):
    f=root/path
    src=f.read_text(encoding="utf-8")
    n=src.count(old)
    if n!=1: raise RuntimeError(f"{path}: expected 1 anchor, got {n}: {old[:100]!r}")
    f.write_text(src.replace(old,new),encoding="utf-8",newline="\n")
    print(f"MONO WARP {path}: patched")
rep("tests/openxr_calibration_tests.cpp",
    "           bool flipped = false, bool ambiguous = false, bool shifted = false,\n           bool late_begin = false, bool fail_end = false, bool support_images = false) {\n    roles();",
    "           bool flipped = false, bool ambiguous = false, bool shifted = false,\n           bool late_begin = false, bool fail_end = false, bool support_images = false,\n           bool mono = false) {\n    roles();\n    if (mono) unregister_stereo_view(9102);")
rep("tests/openxr_calibration_tests.cpp",
    """        eye_calibration_stamp12(gpu.list.Get(), a.Get(), 9101, 0, 0, 128, 128);
        eye_calibration_stamp12(gpu.list.Get(), b.Get(), 9102, 0, 0, 128, 128);
        if (scaling) {""",
    """        eye_calibration_stamp12(gpu.list.Get(), a.Get(), 9101, 0, 0, 128, 128);
        if (!mono) eye_calibration_stamp12(gpu.list.Get(), b.Get(), 9102, 0, 0, 128, 128);
        if (scaling) {""")
rep("tests/openxr_calibration_tests.cpp",
    """            gpu.copy(target.Get(), 0, 0, frame < 320 ? b.Get() : a.Get());
            gpu.copy(target.Get(), array ? 1 : 0, array ? 0 : 128, frame < 320 ? a.Get() : b.Get());""",
    """            gpu.copy(target.Get(), 0, 0, mono ? a.Get() : frame < 320 ? b.Get() : a.Get());
            gpu.copy(target.Get(), array ? 1 : 0, array ? 0 : 128, mono ? a.Get() : frame < 320 ? a.Get() : b.Get());""")
rep("tests/openxr_calibration_tests.cpp",
    "        if (frame == 319 && !ambiguous) {",
    "        if (frame == 319 && !ambiguous && !mono) {")
rep("tests/openxr_calibration_tests.cpp",
    """    if (ambiguous) {
        require(stats.valid == 0 && !stereo_eye_assignment(9101).calibrated &&""",
    """    if (mono) {
        const auto eye = stereo_eye_assignment(9101);
        require(stats.valid > 0 && eye.calibrated && eye.shared_source &&
                !has_multiple_stereo_views() && stats.left_view == 9101 &&
                stats.right_view == 9101,
                "Native DX12 Mono must verify one source stamped once and map it to BOTH OpenXR eye submissions");
        std::cout << "PASS Native DX12 WARP Mono shared-source mapping: "
                  << stats.valid << " valid captures, one neural source, two submitted eyes\\n";
        cleanup();
        return;
    }
    if (ambiguous) {
        require(stats.valid == 0 && !stereo_eye_assignment(9101).calibrated &&""")
rep("tests/openxr_calibration_tests.cpp",
    "int run_openxr_calibration_tests() {",
    """int run_cheeky_native_mono_calibration_tests() {
    try {
        run12(EyeCalibrationBackend::openxr, true, false,
              DXGI_FORMAT_R8G8B8A8_UNORM, false, false, false, false,
              false, false, false, true);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Native DX12 Mono eye calibration: " << error.what() << '\\n';
        cleanup();
        return 1;
    }
}
int run_openxr_calibration_tests() {""")
rep("tests/gaze_tests.cpp",
    '    if (argc == 2 && std::strcmp(argv[1], "--opennr-r10-gaze") == 0) {',
    """    extern int run_cheeky_native_mono_calibration_tests();
    if (argc == 2 && std::strcmp(argv[1], "--cheeky-mono-dx12") == 0)
        return run_cheeky_native_mono_calibration_tests();
    if (argc == 2 && std::strcmp(argv[1], "--opennr-r10-gaze") == 0) {""")
print("Native DX12 shared-source Mono GPU regression source installed")
