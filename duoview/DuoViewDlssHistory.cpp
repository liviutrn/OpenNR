#include "../VR.hpp"
#include "DuoViewDlssHistory.hpp"
#include "DuoViewDlssHistoryPolicy.hpp"
#include "DuoViewNgxParameters.hpp"
#include <safetyhook.hpp>
#include <array>
#include <atomic>
#include <mutex>
#include <unordered_map>

namespace uevr::duoview::ngx {
namespace {
struct Extent { unsigned width{},height{}; };
class Hooks {
public:
    static Hooks& get();
    void service() {
        std::scoped_lock lock{install_mutex_};
        if (installed_ || GetTickCount64()<next_attempt_) return;
        next_attempt_=GetTickCount64()+1000;
        for (const auto name:{L"nvngx_dlss.dll",L"_nvngx.dll",L"nvngx.dll"}) {
            const auto module=GetModuleHandleW(name);
            if (!module) continue;
            const auto create=GetProcAddress(module,"NVSDK_NGX_D3D12_CreateFeature");
            const auto eval=GetProcAddress(module,"NVSDK_NGX_D3D12_EvaluateFeature");
            const auto eval_c=GetProcAddress(module,"NVSDK_NGX_D3D12_EvaluateFeature_C");
            if (!create || (!eval && !eval_c)) continue;
            HMODULE pinned{};
            if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
                reinterpret_cast<LPCWSTR>(create),&pinned)) continue;
            create_=safetyhook::create_inline(reinterpret_cast<void*>(create),reinterpret_cast<void*>(&create_feature),safetyhook::InlineHook::StartDisabled);
            if (!create_) continue;
            if (eval) evaluate_=safetyhook::create_inline(reinterpret_cast<void*>(eval),reinterpret_cast<void*>(&evaluate_feature),safetyhook::InlineHook::StartDisabled);
            if (eval_c && eval_c!=eval) evaluate_c_=safetyhook::create_inline(reinterpret_cast<void*>(eval_c),reinterpret_cast<void*>(&evaluate_feature_c),safetyhook::InlineHook::StartDisabled);
            if (!evaluate_ && !evaluate_c_) { create_.reset();continue; }
            if (!create_.enable().has_value() ||
                (evaluate_ && !evaluate_.enable().has_value()) ||
                (evaluate_c_ && !evaluate_c_.enable().has_value())) {
                create_.reset();evaluate_.reset();evaluate_c_.reset();continue;
            }
            installed_.store(true,std::memory_order_release);
            spdlog::info("[DuoView][DLSS] Installed supported NGX history protection in module {:x}",reinterpret_cast<uintptr_t>(module));
            return;
        }
    }
    Counters counters() const {
        return {calls_.load(),matched_.load(),resets_.load(),missing_.load(),installed_.load()};
    }
private:
    static NVSDK_NGX_Result NVSDK_CONV create_feature(ID3D12GraphicsCommandList* cmd,
        NVSDK_NGX_Feature feature,const NVSDK_NGX_Parameter* parameters,NVSDK_NGX_Handle** output) {
        auto& hooks=get();
        const auto result=hooks.create_.call<NVSDK_NGX_Result>(cmd,feature,parameters,output);
        if (NVSDK_NGX_SUCCEED(result) && parameters && output && *output) {
            Extent extent;
            std::scoped_lock lock{hooks.metadata_mutex_};
            hooks.features_.erase(*output);
            if (feature==NVSDK_NGX_Feature_SuperSampling &&
                NVSDK_NGX_SUCCEED(parameters->Get(NVSDK_NGX_Parameter_OutWidth,&extent.width)) &&
                NVSDK_NGX_SUCCEED(parameters->Get(NVSDK_NGX_Parameter_OutHeight,&extent.height))) {
                if (hooks.features_.size()>128) hooks.features_.clear();
                hooks.features_[*output]=extent;
            }
        }
        return result;
    }
    template<typename Callback>
    NVSDK_NGX_Result evaluate(safetyhook::InlineHook& original,ID3D12GraphicsCommandList* cmd,
        const NVSDK_NGX_Handle* feature,const NVSDK_NGX_Parameter* parameters,Callback callback) {
        calls_.fetch_add(1,std::memory_order_relaxed);
        const auto vr=VR::get();
        const auto runtime=vr->duoview_openxr_runtime();
        std::optional<ViewFrame> frame;
        if (vr->is_using_duoview_mono() && runtime) {
            uint32_t render_frame{};bool known{};
            { std::scoped_lock lock{runtime->sync_assignment_mtx};
              render_frame=runtime->internal_render_frame_count;known=runtime->has_render_frame_count; }
            if (known) frame=vr->duoview_state().snapshot(vr->duoview_key(render_frame));
        }
        Extent extent{};bool known{};
        { std::scoped_lock lock{metadata_mutex_};
          if (const auto found=features_.find(feature);found!=features_.end()) { extent=found->second;known=true; } }
        const bool matched=parameters && frame && known &&
            extent.width==frame->config.layout.fovea.width && extent.height==frame->config.layout.fovea.height &&
            (extent.width!=frame->config.layout.periphery.width || extent.height!=frame->config.layout.periphery.height);
        if (matched) {
            matched_.fetch_add(1,std::memory_order_relaxed);
            unsigned input_w{},input_h{};
            if (NVSDK_NGX_SUCCEED(parameters->Get(NVSDK_NGX_Parameter_DLSS_Render_Subrect_Dimensions_Width,&input_w)) &&
                NVSDK_NGX_SUCCEED(parameters->Get(NVSDK_NGX_Parameter_DLSS_Render_Subrect_Dimensions_Height,&input_h)))
                vr->duoview_state().note_dlss_input_scale(static_cast<float>(input_w)/extent.width,static_cast<float>(input_h)/extent.height);
        } else if (!frame) missing_.fetch_add(1,std::memory_order_relaxed);
        if (!parameters) return original.call<NVSDK_NGX_Result>(cmd,feature,parameters,callback);
        ResetParameters adapter{const_cast<NVSDK_NGX_Parameter*>(parameters)};
        DlssResetScope reset{adapter,matched && protect_dlss_history(frame->config,extent.width,extent.height)};
        if (reset.active()) resets_.fetch_add(1,std::memory_order_relaxed);
        return original.call<NVSDK_NGX_Result>(cmd,feature,parameters,callback);
    }
    static NVSDK_NGX_Result NVSDK_CONV evaluate_feature(ID3D12GraphicsCommandList* cmd,
        const NVSDK_NGX_Handle* feature,const NVSDK_NGX_Parameter* parameters,PFN_NVSDK_NGX_ProgressCallback callback) {
        auto& hooks=get();return hooks.evaluate(hooks.evaluate_,cmd,feature,parameters,callback);
    }
    static NVSDK_NGX_Result NVSDK_CONV evaluate_feature_c(ID3D12GraphicsCommandList* cmd,
        const NVSDK_NGX_Handle* feature,const NVSDK_NGX_Parameter* parameters,PFN_NVSDK_NGX_ProgressCallback_C callback) {
        auto& hooks=get();return hooks.evaluate(hooks.evaluate_c_,cmd,feature,parameters,callback);
    }
    std::mutex install_mutex_,metadata_mutex_;
    safetyhook::InlineHook create_,evaluate_,evaluate_c_;
    std::unordered_map<const NVSDK_NGX_Handle*,Extent> features_;
    std::atomic<uint64_t> calls_{},matched_{},resets_{},missing_{};
    std::atomic<bool> installed_{};
    uint64_t next_attempt_{};
};
Hooks& Hooks::get() { static Hooks hooks;return hooks; }
}
void service() { Hooks::get().service(); }
Counters counters() { return Hooks::get().counters(); }
}
