#!/usr/bin/env python3
"""Additional compiled tests for transient capture length and persistence."""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
p=root/"tests/uevr_tests.cpp"
s=p.read_text(encoding="utf-8")
old='''        const auto write_text=serialize_settings(configured_settings());'''
if s.count(old)!=1:raise RuntimeError("Expected one UEVR snapshot test anchor")
new='''        // CaptureFrames transient: neither menu/template save nor reload should
        // accidentally leave costly capture armed on a later game launch.
        Settings capture_test{};
        require(capture_test.nr_capture_frames == 4U,
            "CaptureFrames transient default is four");
        require(set_named_setting(capture_test,"NrCaptureFrames","1") &&
                capture_test.nr_capture_frames==1U &&
                set_named_setting(capture_test,"NrCaptureFrames","4") &&
                !set_named_setting(capture_test,"NrCaptureFrames","2") &&
                !set_named_setting(capture_test,"NrCaptureFrames","0"),
            "CaptureFrames transient accepts only 1 or 4");
        require(!set_named_setting(capture_test,"NrDebugView","3"),
            "DebugView out-of-range refused");
        capture_test.nr_debug_view=2U;
        capture_test.nr_capture_frames=1U;
        capture_test.nr_dark_pedestal=0.015F;
        capture_test.nr_create_flags_mode=1U;
        const auto transient_text=serialize_settings(capture_test);
        require(transient_text.find("NrCaptureFrames=")==std::string::npos &&
                transient_text.find("NrDebugView=")==std::string::npos &&
                transient_text.find("NrDarkPedestal=")!=std::string::npos &&
                transient_text.find("NrCreateFlagsMode=1")!=std::string::npos,
            "CaptureFrames transient and DebugView excluded from saved INI");
        const auto transient_path=root/"CheekyPreheadsetTransientTest.ini";
        std::string transient_error;
        require(write_settings_file(transient_path,capture_test,transient_error),
            "CaptureFrames transient test INI write");
        Settings loaded_capture{};loaded_capture.nr_debug_view=2U;
        loaded_capture.nr_capture_frames=1U;
        require(read_settings_file(transient_path,loaded_capture,transient_error) &&
                loaded_capture.nr_capture_frames==4U && loaded_capture.nr_debug_view==0U &&
                std::abs(loaded_capture.nr_dark_pedestal-0.015F)<0.000001F &&
                loaded_capture.nr_create_flags_mode==1U,
            "CaptureFrames transient reset on load; persistent pedestal and flags round trip");
        std::filesystem::remove(transient_path);
        const auto write_text=serialize_settings(configured_settings());'''
p.write_text(s.replace(old,new,1),encoding="utf-8",newline="\n")
print("PASS compiled CaptureFrames transient persistence, 1/4 validation and reloaded default fixtures")
