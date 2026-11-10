#!/usr/bin/env python3
"""TriView NR GPU timestamp breakdown, no GPU waits; patch after independent routing."""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
def patch(path,old,new):
    f=root/path;s=f.read_text(encoding="utf-8")
    n=s.count(old)
    if n!=1: raise RuntimeError(f"{path} strict anchor count {n}: {old[:100]!r}")
    f.write_text(s.replace(old,new,1),encoding="utf-8",newline="\n")
    print("NR-PROFILE",path)

patch("src/dlss_nr.hpp","struct DlssNrFrame {",
"""enum class NrGpuStage : std::uint32_t { before_input_copy, encode, model_pass1, model_pass2, decode };
void* nr_gpu_stage_begin(ID3D12GraphicsCommandList*, NrGpuStage,
    std::uint32_t role, std::uint32_t preset, bool crop,
    std::uint32_t width, std::uint32_t height) noexcept;
void nr_gpu_stage_end(void*, bool valid=true) noexcept;
struct DlssNrFrame {""")
patch("src/hooks.cpp","#include <mutex>\n#include <vector>","#include <mutex>\n#include <new>\n#include <vector>")
patch("src/hooks.cpp","    native_peripheral_dlss,\n};",
"""    native_peripheral_dlss,
    nr_stage_copy, nr_stage_encode, nr_stage_model1, nr_stage_model2, nr_stage_decode
};""")
patch("src/hooks.cpp","    D3D12TimingKind kind{D3D12TimingKind::full_nr};",
"""    D3D12TimingKind kind{D3D12TimingKind::full_nr};
    std::uint32_t stage_role{}, stage_preset{}, stage_crop{}, stage_width{}, stage_height{};""")
patch("src/hooks.cpp","GpuTimingStatus timing_status;",
"""GpuTimingStatus timing_status;
// Group by role, model, crop, resolution and GPU stage. Timings are measured by
// GPU timestamps and published only after the owning queue fence completes.
struct NrGpuStageGroup {
    std::uint32_t kind{},role{},preset{},crop{},width{},height{};
    std::uint64_t samples{},last_serial{};
    double sum{},lowest{},highest{};
};
std::array<NrGpuStageGroup,128> nr_stage_groups{};
std::uint64_t nr_stage_serial{};
void nr_stage_measurement(const D3D12NrTimingSlot& slot,double ms) noexcept {
    NrGpuStageGroup *found{},*empty{},*oldest{};
    for(auto& g:nr_stage_groups){
        if(!g.samples){if(!empty)empty=&g;continue;}
        if(g.kind==static_cast<std::uint32_t>(slot.kind)&&g.role==slot.stage_role&&
           g.preset==slot.stage_preset&&g.crop==slot.stage_crop&&
           g.width==slot.stage_width&&g.height==slot.stage_height){found=&g;break;}
        if(!oldest||g.last_serial<oldest->last_serial)oldest=&g;
    }
    if(!found){
        found=empty?empty:oldest;
        if(!found)return;
        *found={};
        found->kind=static_cast<std::uint32_t>(slot.kind);
        found->role=slot.stage_role;found->preset=slot.stage_preset;
        found->crop=slot.stage_crop;found->width=slot.stage_width;found->height=slot.stage_height;
    }
    ++found->samples;found->sum+=ms;found->last_serial=++nr_stage_serial;
    found->lowest=found->samples==1?ms:(std::min)(found->lowest,ms);
    found->highest=(std::max)(found->highest,ms);
    if(found->samples==4U||found->samples%16U==0U){
        const char* stage="unknown";
        switch(slot.kind){
        case D3D12TimingKind::nr_stage_copy:stage="input_copy";break;
        case D3D12TimingKind::nr_stage_encode:stage="encode";break;
        case D3D12TimingKind::nr_stage_model1:stage="model_pass1";break;
        case D3D12TimingKind::nr_stage_model2:stage="model_pass2";break;
        case D3D12TimingKind::nr_stage_decode:stage="decode";break;
        default:break;}
        trace_event("[CheekyNR][GPUStage] stage=%s role=%u preset=%u cropped=%u work=%ux%u samples=%llu avg_ms=%.4f min_ms=%.4f max_ms=%.4f",
            stage,found->role,found->preset,found->crop,found->width,found->height,
            static_cast<unsigned long long>(found->samples),
            found->sum/found->samples,found->lowest,found->highest);
    }
}""")
patch("src/hooks.cpp",
'''            if (slot.kind == D3D12TimingKind::before_pipeline || slot.kind == D3D12TimingKind::after_pipeline) {''',
'''            if (slot.kind>=D3D12TimingKind::nr_stage_copy) {
                nr_stage_measurement(slot,milliseconds);
            } else if (slot.kind == D3D12TimingKind::before_pipeline || slot.kind == D3D12TimingKind::after_pipeline) {''')
patch("src/hooks.cpp",
'''        if (command_list == nullptr ||
            !diagnostic_should_sample_gpu_time(
                kind == D3D12TimingKind::native_peripheral_dlss''',
'''        if (command_list == nullptr ||
            (kind<D3D12TimingKind::nr_stage_copy && !diagnostic_should_sample_gpu_time(
                kind == D3D12TimingKind::native_peripheral_dlss''')
patch("src/hooks.cpp",
'''                        : DiagnosticGpuTiming::d3d12_peripheral_dlaa
            )) {''',
'''                        : DiagnosticGpuTiming::d3d12_peripheral_dlaa
            ))) {''')
# Stage token uses the existing fence-safe query ring. All calls are nonblocking.
patch("src/hooks.cpp",
'''struct NrPipelineTimingScope {''',
'''struct NrStageToken {
    D3D12PeripheralTimingScope timer;
    NrStageToken(ID3D12GraphicsCommandList* l,D3D12TimingKind k) noexcept:timer(l,k){timer.begin();}
};
struct NrPipelineTimingScope {''')
# Export out of the unnamed namespace; all implementation types remain TU-local.
patch("src/hooks.cpp",
'''}  // namespace

HMODULE find_loaded_ngx_core_runtime() noexcept''',
'''}  // namespace

void* nr_gpu_stage_begin(ID3D12GraphicsCommandList* list,NrGpuStage stage,
    std::uint32_t role,std::uint32_t preset,bool crop,
    std::uint32_t width,std::uint32_t height) noexcept {
    const auto index=static_cast<unsigned>(stage);
    if(!list||index>4U)return nullptr;
    static std::array<std::atomic<std::uint64_t>,5> samples{};
    // Sample one of every 16 stage evaluations; no readback stall.
    if((samples[index].fetch_add(1U,std::memory_order_relaxed)&15U)!=0U)return nullptr;
    const auto kind=static_cast<D3D12TimingKind>(
        static_cast<unsigned>(D3D12TimingKind::nr_stage_copy)+index);
    auto* token=new(std::nothrow) NrStageToken(list,kind);
    if(!token)return nullptr;
    if(!token->timer.slot){delete token;return nullptr;}
    auto* slot=token->timer.slot;
    slot->stage_role=role;slot->stage_preset=preset;
    slot->stage_crop=crop?1U:0U;slot->stage_width=width;slot->stage_height=height;
    return token;
}
void nr_gpu_stage_end(void* opaque,bool valid) noexcept {
    auto* token=static_cast<NrStageToken*>(opaque);
    if(!token)return;
    token->timer.finish(valid);
    delete token;
}

HMODULE find_loaded_ngx_core_runtime() noexcept''')
patch("src/dlss_nr_input.cpp",
'''    transition(frame.command_list, frame.color, frame.color_state, D3D12_RESOURCE_STATE_COPY_SOURCE);''',
'''    auto* copy_timing=nr_gpu_stage_begin(frame.command_list,NrGpuStage::before_input_copy,
        cheeky_nr_source_role(frame.view_id),settings.nr_preset,settings.nr_foveated,
        frame.input_width,frame.input_height);
    transition(frame.command_list, frame.color, frame.color_state, D3D12_RESOURCE_STATE_COPY_SOURCE);''')
patch("src/dlss_nr_input.cpp",
'''    frame.color = private_color;
    auto processing_settings = settings;''',
'''    nr_gpu_stage_end(copy_timing);
    frame.color = private_color;
    auto processing_settings = settings;''')
patch("src/dlss_nr.cpp",
'''    uav_barrier(frame.command_list, frame.color);
    transition(
        frame.command_list,
        frame.color,
        frame.color_state,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE
    );
    dispatch_codec(''',
'''    auto* encode_timing=nr_gpu_stage_begin(frame.command_list,NrGpuStage::encode,
        frame.source_role,settings.nr_preset,settings.nr_foveated,working_width,working_height);
    uav_barrier(frame.command_list, frame.color);
    transition(
        frame.command_list,
        frame.color,
        frame.color_state,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE
    );
    dispatch_codec(''')
patch("src/dlss_nr.cpp",
'''    // Alternate model outputs so the last pass always writes neural_output,''',
'''    nr_gpu_stage_end(encode_timing);
    // Alternate model outputs so the last pass always writes neural_output,''')
patch("src/dlss_nr.cpp",
'''        result = runtime.evaluate_feature(
            frame.command_list,
            model.view->handle,
            parameters,
            nullptr
        );
        if (!ngx_succeeded(result)) { failed_pass = pass; break; }''',
'''        auto* inference_timing=nr_gpu_stage_begin(frame.command_list,
            (frame.logical_pass==2U||pass==1U) ? NrGpuStage::model_pass2 : NrGpuStage::model_pass1,
            frame.source_role,model.settings.nr_preset,model.settings.nr_foveated,
            working_width,working_height);
        result = runtime.evaluate_feature(
            frame.command_list,
            model.view->handle,
            parameters,
            nullptr
        );
        nr_gpu_stage_end(inference_timing,ngx_succeeded(result));
        if (!ngx_succeeded(result)) { failed_pass = pass; break; }''')
patch("src/dlss_nr.cpp",
'''    move_model_output(gpu->neural_output, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    transition(
        frame.command_list,
        frame.color,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS
    );''',
'''    auto* decode_timing=nr_gpu_stage_begin(frame.command_list,NrGpuStage::decode,
        frame.source_role,settings.nr_preset,settings.nr_foveated,working_width,working_height);
    move_model_output(gpu->neural_output, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    transition(
        frame.command_list,
        frame.color,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS
    );''')
patch("src/dlss_nr.cpp",
'''    ++diagnostics.evaluation_calls;
    ++diagnostics.decoded_frames;''',
'''    nr_gpu_stage_end(decode_timing);
    ++diagnostics.evaluation_calls;
    ++diagnostics.decoded_frames;''')
print("PASS GPU timestamp instrumentation added")
