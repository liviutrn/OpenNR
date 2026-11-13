#!/usr/bin/env python3
"""Non-visual pre-headset capture-V2 generated-source safety contract."""
from pathlib import Path
import sys,re
root=Path(sys.argv[1]).resolve()
read=lambda p:(root/p).read_text(encoding="utf-8")
h=read("src/nr_probe_capture.hpp")
nr=read("src/dlss_nr.cpp")
runtime=read("uevr/runtime.cpp")
ui=read("uevr/scripts/cheeky_foveated_dlss.lua")
io=read("uevr/settings_io.cpp")
settings=read("src/settings.hpp")
tests=read("tests/uevr_tests.cpp")
checks={
 "default capture length 4; only 1 or 4 accepted":'nr_capture_frames{4U}' in settings and 'count!=1U && count!=4U' in io,
 "capture length transient (never serialized or templated)":'std::string_view(name) != "NrCaptureFrames"' in io and 'key == "NrCaptureFrames") continue' in io and 'std::string_view(name) != "NrCaptureFrames"' in runtime,
 "explicit in-game capture control":"Capture NR frames" in ui and "NrCaptureFrames" in ui,
 "no normal-frame staging allocation":'if(!nr_probe_busy.load(std::memory_order_acquire))return;' in h and 'nr_probe_capture_one(frame,*gpu,codec_region,settings,pass_count)' in nr,
 "one or four consecutive source frames":'nr_probe_frames_per_source=requested' in h and 'const unsigned source_frame=progress.attempted++' in h and 'nr_probe_expected_sources=settings.nr_target_mode>=2U ? 2U : 1U' in h,
 "target foveas only":'if(frame.source_role==4U)return;' in h,
 "timeout prevents stale capture requests":'now-armed>15000ULL' in h,
 "backpressure refuses excess readbacks":'nr_probe_inflight.size()>=8U' in h and 'used>256ULL*1024ULL*1024ULL-required' in h,
 "no detached thread":'std::thread([completed]' not in h and 'nr_probe_write(completed);' in h,
 "GPU use tracked before copies":h.index('capture->lifetime.record(frame.command_list)')<h.index('CopyTextureRegion(&dst,0U,0U,0U,&from,&box)'),
 "no change to VRAM admission":"nr_lite_effective_headroom(previous, next)" in runtime,
 "partial images saved":'if(!image.valid || !image.readback)continue;' in h and '"unsupported_format_or_region"' in h,
 "format26 supported":'DXGI_FORMAT_R11G11B10_FLOAT' in h,
 "schema and decoder metadata":'schema' in h and 'capture->exposure_pre' in h and 'capture->exposure_multiplier' in h and 'exposure_texel_available' in h and 'capture->dll_version' in h and 'source_frame_index' in h,
 "model and frame metadata":'capture->logical_pass=frame.logical_pass' in h and 'capture->source_frame_index=source_frame' in h and 'capture->intensity=settings.nr_intensity' in h,
 "correct NR flag failure trace":bool(re.search(r'nr_flags,\s*result\s*\)',nr)),
 "correct logical pass telemetry":"cost.logical_pass=frame.logical_pass;" in nr and "cost.logical_pass," in nr,
 "compiled transient settings test":"CaptureFrames transient" in tests,
}
for n,ok in checks.items():print(("PASS " if ok else "FAIL ")+n)
if not all(checks.values()):raise SystemExit("Capture V2 generated-source contract failed")
print("PASS source contract: capture V2 gating, memory, format, metadata, lifetime, and no detached thread")
