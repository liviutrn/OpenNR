#!/usr/bin/env python3
"""Pre-headset capture V2, strictly AFTER apply_v063_preheadset.py.
Does not alter earlier patch scripts, NR routing, VRAM admission or gameplay.
All changes are behind explicit NR frame-capture interaction; no writer thread.
"""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
def replace(path,old,new):
    p=root/path;s=p.read_text(encoding="utf-8");n=s.count(old)
    if n!=1:raise RuntimeError(f"{path}: expected 1 anchor, found {n}: {old[:100]!r}")
    p.write_text(s.replace(old,new,1),encoding="utf-8",newline="\n")
    print("NR-CAP-V2",path,old[:65].replace("\n"," "))
def insert(path,old,new):
    replace(path,old,new+old)

# CLI setting 1 or 4, default 4, explicitly not saved or templated.
replace("src/settings.hpp",
'''    std::uint32_t nr_debug_view{0U}; // transient 0=off,1=exposure edit,2=chroma edit''',
'''    std::uint32_t nr_debug_view{0U}; // transient 0=off,1=exposure edit,2=chroma edit
    std::uint32_t nr_capture_frames{4U}; // 1 or 4, in-session only''')
replace("src/settings.cpp",
'''std::atomic<std::uint32_t> nr_debug_view{0U};''',
'''std::atomic<std::uint32_t> nr_debug_view{0U};
std::atomic<std::uint32_t> nr_capture_frames{4U};''')
replace("src/settings.cpp",
'''    settings.nr_debug_view = nr_debug_view.load(std::memory_order_acquire);''',
'''    settings.nr_debug_view = nr_debug_view.load(std::memory_order_acquire);
    settings.nr_capture_frames = nr_capture_frames.load(std::memory_order_acquire);''')
replace("src/settings.cpp",
'''    nr_debug_view.store((std::min)(settings.nr_debug_view, 2U), std::memory_order_release);''',
'''    nr_debug_view.store((std::min)(settings.nr_debug_view, 2U), std::memory_order_release);
    nr_capture_frames.store(settings.nr_capture_frames == 1U ? 1U : 4U, std::memory_order_release);''')
replace("uevr/settings_fields.inc",
'''CHEEKY_SETTING("NrDebugView", nr_debug_view)''',
'''CHEEKY_SETTING("NrDebugView", nr_debug_view)
CHEEKY_SETTING("NrCaptureFrames", nr_capture_frames)''')
replace("uevr/settings_io.cpp",
'''    if(key=="NrDebugView" || key=="NrCreateFlagsMode") {''',
'''    if(key=="NrCaptureFrames") {
        unsigned count{};
        if(!parse(value,count) || (count!=1U && count!=4U)) return false;
        s.nr_capture_frames=count;return true;
    }
    if(key=="NrDebugView" || key=="NrCreateFlagsMode") {''')
replace("uevr/settings_io.cpp",
'''if (std::string_view(name) != "NrDebugView") out''',
'''if (std::string_view(name) != "NrDebugView" && std::string_view(name) != "NrCaptureFrames") out''')
replace("uevr/settings_io.cpp",
'''    candidate.nr_debug_view = 0U; // Session-only; never load saved debug mode.''',
'''    candidate.nr_debug_view = 0U; // Session-only; never load saved debug mode.
    candidate.nr_capture_frames = 4U; // Never load saved capture count.''')
replace("uevr/settings_io.cpp",
'''            if (key == "NrDebugView") continue; // Deliberately transient.''',
'''            if (key == "NrDebugView" || key == "NrCaptureFrames") continue; // Transient only.''')
replace("uevr/runtime.cpp",
'''std::string_view(name) != "NrDebugView") settings.field = stored.field;''',
'''std::string_view(name) != "NrDebugView" && std::string_view(name) != "NrCaptureFrames") settings.field = stored.field;''')
replace("uevr/scripts/cheeky_foveated_dlss.lua",
'''        if imgui.button("Capture one NR frame (lossless raw)") then send("nr_capture") end''',
'''        combo("NR capture length (next consecutive evaluations)", "NrCaptureFrames",
            {[1]="1 frame", [4]="4 frames per source (default)"}, {1,4})
        if imgui.button("Capture NR frames") then send("nr_capture") end''')
replace("uevr/scripts/cheeky_foveated_dlss.lua",
'''        text("Four raw images plus capture.json; saves only after GPU completion.")''',
'''        text("Original/proxy/neural/final raw images + per-frame JSON after GPU completion.")
        text("TriView captures both foveas; frames have per-source sequence indexes.")
        text("Readback IO can cause a short hitch while files are saved.")''')

# Version metadata is capture-only. Version read once during startup.
replace("src/dlss_nr.cpp",
'''        trace_event("[CheekyNR][Runtime] path=%s version=%u.%u.%u.%u (file version; zero means unavailable)",''',
'''        sprintf_s(nr_probe_dll_version, "%u.%u.%u.%u",
            version_parts[0],version_parts[1],version_parts[2],version_parts[3]);
        trace_event("[CheekyNR][Runtime] path=%s version=%u.%u.%u.%u (file version; zero means unavailable)",''')
# Repoint creation-failed message to actual NR flags rather than SR flags:
replace("src/dlss_nr.cpp",
'''            frame.create_flags,
            result
        );
        return false;''',
'''            nr_flags,
            result
        );
        return false;''')
replace("src/dlss_nr.cpp",'''cost.preset=preset;cost.logical_pass=view.pass;''',
'''cost.preset=preset;cost.logical_pass=frame.logical_pass;''')
replace("src/dlss_nr.cpp",'''static_cast<unsigned long long>(view.view_id),cost.logical_pass+1U,''',
'''static_cast<unsigned long long>(view.view_id),cost.logical_pass,''')

# Non-blocking request (no GPU work until a successful evaluated frame).
replace("src/dlss_nr.hpp",
'''[[nodiscard]] bool request_dlss_nr_capture() noexcept;''',
'''[[nodiscard]] bool request_dlss_nr_capture(unsigned frames) noexcept;''')
replace("src/dlss_nr.cpp",
'''bool request_dlss_nr_capture() noexcept {
    unsigned idle=0U;
    return nr_probe_requested.compare_exchange_strong(idle,1U);
}''',
'''bool request_dlss_nr_capture(unsigned frames) noexcept {
    if(frames != 1U && frames != 4U) return false;
    bool expected=false;
    if(!nr_probe_busy.compare_exchange_strong(expected,true,
            std::memory_order_acq_rel)) return false;
    nr_probe_armed_ms.store(GetTickCount64(),std::memory_order_release);
    nr_probe_requested.store(frames,std::memory_order_release);
    trace_event("[CheekyNR][FrameCapture] request framesPerSource=%u",frames);
    return true;
}''')
replace("uevr/runtime.cpp",
'''const bool armed=request_dlss_nr_capture();''',
'''const bool armed=request_dlss_nr_capture(configured_settings().nr_capture_frames);''')
replace("uevr/runtime.cpp",
'''                ? "NR frame capture armed; GPU readback files will be written to LocalAppData/ CheekyNR-Captures after GPU completion"''',
'''                ? "NR frame sequence armed (1 or 4/source); files will appear in LocalAppData/CheekyNR-Captures after GPU completion"''')

# Existing generated header belongs to our previous patch, so changing only
# it does not perturb D3D12 instrumentation or the baseline shader path.
replace("src/nr_probe_capture.hpp",
'''    const char* name{};
};''',
'''    const char* name{};
    const char* status{"not_attempted"};
    bool valid{};
};''')
replace("src/nr_probe_capture.hpp",
'''    std::uint64_t sequence{},source_id{},reserved{}, captured_ms{};''',
'''    std::uint64_t sequence{},source_id{},reserved{}, captured_ms{};
    std::uint64_t session_id{}, sample_tick{}, source_frame_index{};
    std::string dll_version{};''')
replace("src/nr_probe_capture.hpp",
'''    std::uint32_t region_x{},region_y{},working_width{},working_height{};''',
'''    std::uint32_t region_x{},region_y{},region_width{},region_height{},working_width{},working_height{};
    std::uint32_t source_width{},source_height{},source_base_x{},source_base_y{};
    std::uint32_t logical_pass{},nr_passes_requested{},shared_chain{},route{},processing_order{};
    std::uint32_t preset{},style{},debug_view{},hdr_mode{},exposure_format{};
    float intensity{},tone{},structure{},skin{},roundness{},transition{},shape_w{},shape_h{};
    float exposure_pre{},exposure_scale{},exposure_ratio{},exposure_multiplier{};''')
replace("src/nr_probe_capture.hpp",
'''std::atomic<unsigned> nr_probe_requested{};
std::atomic<std::uint64_t> nr_probe_memory{};''',
'''struct NrProbeSourceProgress { std::uint64_t id{}; unsigned attempted{}; };
std::atomic<unsigned> nr_probe_requested{};
std::atomic<bool> nr_probe_busy{};
std::atomic<std::uint64_t> nr_probe_armed_ms{};
std::array<NrProbeSourceProgress,2> nr_probe_source_progress{};
unsigned nr_probe_source_count{},nr_probe_expected_sources{},nr_probe_frames_per_source{};
bool nr_probe_active{};
std::uint64_t nr_probe_session{},nr_probe_started_ms{};
char nr_probe_dll_version[80]{"unknown"};
std::atomic<std::uint64_t> nr_probe_memory{};''')
replace("src/nr_probe_capture.hpp",
'''    out.format=static_cast<std::uint32_t>(real.Format);out.name=name;
    return true;''',
'''    out.format=static_cast<std::uint32_t>(real.Format);out.name=name;
    out.valid=true;out.status="captured";
    return true;''')
replace("src/nr_probe_capture.hpp",
'''       real.Format!=DXGI_FORMAT_R10G10B10A2_UNORM) return false;''',
'''       real.Format!=DXGI_FORMAT_R10G10B10A2_UNORM &&
       real.Format!=DXGI_FORMAT_R11G11B10_FLOAT) return false;''')

# Synchronous writer after GPU retirement: detached thread can run inside
# unloaded DLL, so never use one. Explicitly ignore skipped images.
replace("src/nr_probe_capture.hpp",
'''        for(const auto& image:capture->images){
            void* data{};''',
'''        for(const auto& image:capture->images){
            if(!image.valid || !image.readback)continue;
            void* data{};''')
replace("src/nr_probe_capture.hpp",
'''        try { std::thread([completed]{nr_probe_write(completed);}).detach(); }
        catch (...) { trace_event("[CheekyNR][FrameCapture] worker_unavailable"); }''',
'''        nr_probe_write(completed); // GPU complete; no detached DLL code. May briefly hitch.''')

# All captures in the same request live in one session folder; distinct files
# for each source/frame; raw row_pitch is explicitly preserved and lossless.
replace("src/nr_probe_capture.hpp",
'''        swprintf_s(name,L"%04u%02u%02u-%02u%02u%02u-%llu-view-%llu",
            time.wYear,time.wMonth,time.wDay,time.wHour,time.wMinute,time.wSecond,
            static_cast<unsigned long long>(capture->sequence),
            static_cast<unsigned long long>(capture->source_id));
        const auto folder=std::filesystem::path(root)/L"CheekyNR-Captures"/name;''',
'''        swprintf_s(name,L"session-%llu",static_cast<unsigned long long>(capture->session_id));
        const auto folder=std::filesystem::path(root)/L"CheekyNR-Captures"/name;
        char stem[150]{};
        sprintf_s(stem,"src%llu_f%llu",
            static_cast<unsigned long long>(capture->source_id),
            static_cast<unsigned long long>(capture->source_frame_index));''')
replace("src/nr_probe_capture.hpp",
'''std::ofstream file(folder/(std::string(image.name)+".bin"),std::ios::binary);''',
'''std::ofstream file(folder/(std::string(stem)+"_"+image.name+".bin"),std::ios::binary);''')
replace("src/nr_probe_capture.hpp",
'''std::ofstream meta(folder/"capture.json",std::ios::binary);''',
'''std::ofstream meta(folder/(std::string(stem)+".json"),std::ios::binary);''')
replace("src/nr_probe_capture.hpp",
'''            meta << "{\\n  \\"schema\\":1,\\n  \\"source_id\\":\\"" << capture->source_id''',
'''            meta << "{\\n  \\"schema\\":2,\\n  \\"session_id\\":\\"" << capture->session_id
                 << "\\",\\n  \\"source_frame_index\\":" << capture->source_frame_index
                 << ",\\n  \\"timestamp_ms\\":" << capture->sample_tick
                 << ",\\n  \\"source_id\\":\\"" << capture->source_id''')
replace("src/nr_probe_capture.hpp",
'''                 << "\\",\\n  \\"source_role\\":" << capture->source_role''',
'''                 << "\\",\\n  \\"source_role\\":" << capture->source_role
                 << ",\\n  \\"dll_file_version\\":\\"" << capture->dll_version
                 << "\\",\\n  \\"logical_pass\\":" << capture->logical_pass
                 << ",\\n  \\"nr_passes_requested\\":" << capture->nr_passes_requested
                 << ",\\n  \\"shared_pass_chain\\":" << capture->shared_chain
                 << ",\\n  \\"route\\":" << capture->route
                 << ",\\n  \\"processing_order\\":" << capture->processing_order
                 << ",\\n  \\"source_width\\":" << capture->source_width
                 << ",\\n  \\"source_height\\":" << capture->source_height
                 << ",\\n  \\"source_base_x\\":" << capture->source_base_x
                 << ",\\n  \\"source_base_y\\":" << capture->source_base_y
                 << ",\\n  \\"region_width\\":" << capture->region_width
                 << ",\\n  \\"region_height\\":" << capture->region_height
                 << ",\\n  \\"hdr_mode\\":" << capture->hdr_mode
                 << ",\\n  \\"preset\\":" << capture->preset
                 << ",\\n  \\"style\\":" << capture->style
                 << ",\\n  \\"intensity\\":" << capture->intensity
                 << ",\\n  \\"local_tone\\":" << capture->tone
                 << ",\\n  \\"local_structure\\":" << capture->structure
                 << ",\\n  \\"skin_structure\\":" << capture->skin
                 << ",\\n  \\"debug_view\\":" << capture->debug_view
                 << ",\\n  \\"foveation_roundness\\":" << capture->roundness
                 << ",\\n  \\"foveation_transition\\":" << capture->transition
                 << ",\\n  \\"foveation_shape_width\\":" << capture->shape_w
                 << ",\\n  \\"foveation_shape_height\\":" << capture->shape_h
                 << ",\\n  \\"exposure_texture_format\\":" << capture->exposure_format
                 << ",\\n  \\"exposure_texel_available\\":false"
                 << ",\\n  \\"exposure_pre\\":" << capture->exposure_pre
                 << ",\\n  \\"exposure_scale\\":" << capture->exposure_scale
                 << ",\\n  \\"exposure_pre_div_scale\\":" << capture->exposure_ratio
                 << ",\\n  \\"exposure_white_multiplier\\":" << capture->exposure_multiplier
                 << ",\\n  \\"codec_white_formula\\":\\"max(PaperWhiteScale*clamp(ExposureWhiteMultiplier/exposure_texel,0.0001,1024),0.0001) when supported; game exposure texel not sampled\\""
                 << ",\\n  \\"gpu_exposure_texel_not_captured\\":true"''')
replace("src/nr_probe_capture.hpp",
'''                 << ",\\n  \\"format_note\\":\\"R16G16B16A16_FLOAT=10, R8G8B8A8_UNORM=28, R10G10B10A2_UNORM=24; little-endian; rows include DXGI padding\\",\\n  \\"images\\":{\\n";''',
'''                 << ",\\n  \\"format_note\\":\\"10=RGBA16F,26=R11G11B10_FLOAT,28=RGBA8_UNORM,24=R10G10B10A2; little-endian; rows include GPU copy pitch\\",\\n  \\"images\\":{\\n";''')
replace("src/nr_probe_capture.hpp",
'''                meta<<"    \\""<<im.name<<"\\":{\\"file\\":\\""<<im.name<<".bin\\",\\"width\\":"<<im.width''',
'''                meta<<"    \\""<<im.name<<"\\":{\\"file\\":\\""<<stem<<"_"<<im.name<<".bin\\",\\"status\\":\\""<<im.status<<"\\",\\"width\\":"<<im.width''')
# Logging describes saved image count and detects partial samples explicitly.
replace("src/nr_probe_capture.hpp",
'''        trace_event("[CheekyNR][FrameCapture] %s path=%s source=%llu bytes=%llu (readback after GPU recording retirement)",''',
'''        trace_event("[CheekyNR][FrameCapture] %s path=%s source=%llu bytes=%llu frame=%llu session=%llu (GPU complete; synchronous write)",''')
replace("src/nr_probe_capture.hpp",
'''            static_cast<unsigned long long>(capture->reserved));''',
'''            static_cast<unsigned long long>(capture->reserved),
            static_cast<unsigned long long>(capture->source_frame_index),
            static_cast<unsigned long long>(capture->session_id));''')

# Replace session and capture-front logic. An independent source gets 4
# consecutive eligible evaluations; TriView gets two fovea source identities.
replace("src/nr_probe_capture.hpp",
'''void nr_probe_capture_one(const DlssNrFrame& frame,const GpuResources& gpu,
    const NrRegion& codec,const Settings& settings,unsigned passes) noexcept {
    if(!nr_probe_requested.load(std::memory_order_acquire))return;
    if(nr_probe_inflight.size()>=2U)return;
    if(!frame.command_list||!frame.color||!gpu.original_output ||
        !gpu.color_proxy||!gpu.neural_output)return;
    if(nr_probe_requested.exchange(0U,std::memory_order_acq_rel)==0U)return;
    try {''',
'''void nr_probe_capture_one(const DlssNrFrame& frame,const GpuResources& gpu,
    const NrRegion& codec,const Settings& settings,unsigned passes) noexcept {
    // The cheap disabled check is the only normal-frame cost.
    if(!nr_probe_busy.load(std::memory_order_acquire))return;
    if(frame.source_role==4U)return; // Capture fovea(s), not Tri periphery.
    // Split pass-2 uses a synthetic source ID. Its original is already relit,
    // so four-surface decoder comparisons need pass 2 disabled for that mode.
    const auto source_mask=cheeky_nr_selected_passes(current_settings(),
        frame.view_id & ~(1ULL<<63U));
    if(frame.logical_pass!=1U ||
       (settings.nr_passes==1U && (source_mask&2U)!=0U)) {
        static std::atomic<unsigned> split_warning{};
        if(split_warning.fetch_add(1U,std::memory_order_relaxed)<4U)
            trace_event("[CheekyNR][FrameCapture] skipped split pass chain; disable pass 2 for objective capture");
        return;
    }
    if(!frame.command_list||!frame.color||!gpu.original_output ||
        !gpu.color_proxy||!gpu.neural_output)return;
    if(!nr_probe_active) {
        const unsigned requested=nr_probe_requested.exchange(0U,std::memory_order_acq_rel);
        if(!requested)return;
        nr_probe_active=true;nr_probe_frames_per_source=requested;
        nr_probe_expected_sources=settings.nr_target_mode>=2U ? 2U : 1U;
        nr_probe_source_count=0U;
        nr_probe_source_progress={};
        nr_probe_started_ms=GetTickCount64();
        // FILETIME is globally unique enough to prevent folder overwrites
        // across game restarts and multiple capture requests.
        FILETIME session_time{};
        GetSystemTimeAsFileTime(&session_time);
        nr_probe_session=(static_cast<std::uint64_t>(session_time.dwHighDateTime)<<32U) |
            session_time.dwLowDateTime;
        trace_event("[CheekyNR][FrameCapture] session_start=%llu frames=%u foveaSources=%u",
            static_cast<unsigned long long>(nr_probe_session),requested,nr_probe_expected_sources);
    }
    unsigned slot=0U;
    while(slot<nr_probe_source_count && nr_probe_source_progress[slot].id!=frame.view_id)++slot;
    if(slot==nr_probe_source_count) {
        if(slot>=nr_probe_expected_sources || slot>=nr_probe_source_progress.size())return;
        nr_probe_source_progress[slot].id=frame.view_id;
        nr_probe_source_progress[slot].attempted=0U;
        ++nr_probe_source_count;
    }
    auto& progress=nr_probe_source_progress[slot];
    if(progress.attempted>=nr_probe_frames_per_source)return;
    const unsigned source_frame=progress.attempted++;
    const auto all_done=[&]() {
        if(nr_probe_source_count<nr_probe_expected_sources)return false;
        for(unsigned i=0;i<nr_probe_source_count;++i)
            if(nr_probe_source_progress[i].attempted<nr_probe_frames_per_source)return false;
        return true;
    };
    // Count attempts even when readback memory cannot be acquired: no fake
    // continuity after a missed frame. Metadata+log show holes explicitly.
    const bool finishing=all_done();
    if(finishing)nr_probe_active=false;
    if(nr_probe_inflight.size()>=8U) {
        trace_event("[CheekyNR][FrameCapture] skipped frame=%u source=%llu inflight_limit",
            source_frame,static_cast<unsigned long long>(frame.view_id));
        return;
    }
    try {''')
replace("src/nr_probe_capture.hpp",
'''        std::uint64_t required{};
        for(size_t i=0;i<sources.size();++i){''',
'''        std::uint64_t required{};
        for(size_t i=0;i<sources.size();++i){''') # stable insertion anchor
replace("src/nr_probe_capture.hpp",
'''               !nr_probe_readback(device.Get(),capture->images[i],
                   src.tex,src.width,src.height,src.name)) {
                trace_event("[CheekyNR][FrameCapture] unsupported_format_or_region");
                return;
            }
            required+=capture->images[i].size;''',
'''               !nr_probe_readback(device.Get(),capture->images[i],
                   src.tex,src.width,src.height,src.name)) {
                capture->images[i].name=src.name;
                capture->images[i].status="unsupported_format_or_region";
                trace_event("[CheekyNR][FrameCapture] skipped image=%s frame=%u source=%llu format=%u",
                    src.name,source_frame,static_cast<unsigned long long>(frame.view_id),
                    static_cast<unsigned>(desc.Format));
                continue; // Never discard the other images.
            }
            required+=capture->images[i].size;''')
replace("src/nr_probe_capture.hpp",
'''        if(required>192ULL*1024ULL*1024ULL) {''',
'''        if(!required) {
            trace_event("[CheekyNR][FrameCapture] no_supported_images frame=%u",source_frame);
            return;
        }
        if(required>192ULL*1024ULL*1024ULL) {''')
replace("src/nr_probe_capture.hpp",
'''            if(used>256ULL*1024ULL*1024ULL-required)return;''',
'''            if(used>256ULL*1024ULL*1024ULL-required) {
                trace_event("[CheekyNR][FrameCapture] skipped frame=%u source=%llu memory_cap usedMiB=%llu requestedMiB=%llu",
                    source_frame,static_cast<unsigned long long>(frame.view_id),
                    static_cast<unsigned long long>(used>>20),
                    static_cast<unsigned long long>(required>>20));
                return;
            }''')
replace("src/nr_probe_capture.hpp",
'''        capture->sequence=nr_probe_sequence.fetch_add(1U)+1U;
        capture->source_id=frame.view_id;capture->source_role=frame.source_role;''',
'''        capture->sequence=nr_probe_sequence.fetch_add(1U)+1U;
        capture->session_id=nr_probe_session;
        capture->source_frame_index=source_frame;
        capture->sample_tick=GetTickCount64();
        capture->dll_version=nr_probe_dll_version;
        capture->source_id=frame.view_id;capture->source_role=frame.source_role;''')
replace("src/nr_probe_capture.hpp",
'''        capture->region_x=codec.base_x;capture->region_y=codec.base_y;''',
'''        capture->region_x=codec.base_x;capture->region_y=codec.base_y;
        capture->region_width=codec.width;capture->region_height=codec.height;
        capture->source_width=frame.output_width;capture->source_height=frame.output_height;
        capture->source_base_x=frame.color_base_x;capture->source_base_y=frame.color_base_y;
        capture->logical_pass=frame.logical_pass;
        capture->nr_passes_requested=settings.nr_passes;
        capture->shared_chain=passes>1U?1U:0U; // split pass represented by logical_pass==2
        capture->route=static_cast<unsigned>(frame.route);
        capture->processing_order=static_cast<unsigned>(settings.nr_processing_order);
        capture->preset=settings.nr_preset;capture->style=settings.nr_style;
        capture->intensity=settings.nr_intensity;
        capture->tone=settings.nr_local_tone_strength;
        capture->structure=settings.nr_local_structure_strength;
        capture->skin=settings.nr_skin_structure_strength;
        capture->debug_view=settings.nr_debug_view;
        capture->hdr_mode=frame.create_flags&1U;
        capture->roundness=codec.roundness;capture->transition=codec.transition;
        capture->shape_w=codec.shape_width;capture->shape_h=codec.shape_height;
        capture->exposure_pre=debug_exposure.pre;
        capture->exposure_scale=debug_exposure.scale;
        capture->exposure_ratio=gpu.exposure?debug_exposure.pre/debug_exposure.scale:0.0F;
        capture->exposure_multiplier=capture->exposure_ratio;
        capture->exposure_format=gpu.exposure?
            static_cast<unsigned>(gpu.exposure->GetDesc().Format):0U;''')
replace("src/nr_probe_capture.hpp",
'''        for(size_t i=0;i<sources.size();++i){
            const auto& src=sources[i];
            nr_probe_transition''',
'''        for(size_t i=0;i<sources.size();++i){
            if(!capture->images[i].valid)continue;
            const auto& src=sources[i];
            nr_probe_transition''')
# The writer can be triggered by collect() when the command list has been
# retired on all queues. Add a bounded session timeout to avoid stuck Busy
# if TriView never supplies the second fovea (or the game is paused).
replace("src/nr_probe_capture.hpp",
'''void nr_probe_poll() noexcept {
    for(auto it=nr_probe_inflight.begin();''',
'''void nr_probe_poll() noexcept {
    const auto now=GetTickCount64();
    const auto armed=nr_probe_armed_ms.load(std::memory_order_acquire);
    if(nr_probe_busy.load(std::memory_order_acquire) && armed &&
       now>=armed && now-armed>15000ULL) {
        if(nr_probe_active) {
            trace_event("[CheekyNR][FrameCapture] session_timeout=%llu sources=%u (no GPU wait)",
                static_cast<unsigned long long>(nr_probe_session),nr_probe_source_count);
            nr_probe_active=false;
        }
        nr_probe_requested.store(0U,std::memory_order_release);
    }
    for(auto it=nr_probe_inflight.begin();''')
replace("src/nr_probe_capture.hpp",
'''        nr_probe_write(completed); // GPU complete; no detached DLL code. May briefly hitch.
    }
}''',
'''        nr_probe_write(completed); // GPU complete; no detached DLL code. May briefly hitch.
    }
    if(nr_probe_busy.load(std::memory_order_acquire) &&
       !nr_probe_active && nr_probe_inflight.empty() &&
       nr_probe_requested.load(std::memory_order_acquire)==0U) {
        nr_probe_busy.store(false,std::memory_order_release);
        trace_event("[CheekyNR][FrameCapture] session_complete");
    }
}''')

# No new game-texel transition; the above snapshot stores the same known
# CPU-derived data used by the Exposure log, with explicit missing texel.
print("PASS V2 consecutive source capture, partial images, exposure CPU metadata, synchronous writer, logical-pass labels")
