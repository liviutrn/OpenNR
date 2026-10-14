#pragma once
#include "DuoViewConfig.hpp"
namespace uevr::duoview {
inline bool protect_dlss_history(const FrameConfig& frame,uint32_t width,uint32_t height) {
    const auto& l=frame.layout;
    return frame.settings.dlss_history_protection && frame.foveal_history_reset &&
        width==l.fovea.width && height==l.fovea.height &&
        (width!=l.periphery.width || height!=l.periphery.height);
}
template<typename Parameters>
class DlssResetScope {
public:
    explicit DlssResetScope(Parameters& parameters,bool requested):parameters_{parameters} {
        if (requested && parameters_.get_reset(previous_) && previous_==0) {
            parameters_.set_reset(1); active_=true;
        }
    }
    ~DlssResetScope() { if (active_) parameters_.set_reset(previous_); }
    bool active() const { return active_; }
    DlssResetScope(const DlssResetScope&)=delete;
    DlssResetScope& operator=(const DlssResetScope&)=delete;
private:
    Parameters& parameters_;
    unsigned previous_{};
    bool active_{};
};
}
