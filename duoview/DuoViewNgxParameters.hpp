#pragma once
#include <nvsdk_ngx_params.h>
namespace uevr::duoview::ngx {
struct ResetParameters {
    NVSDK_NGX_Parameter* value;
    bool signed_reset{};
    bool get_reset(unsigned& out) {
        if (NVSDK_NGX_SUCCEED(value->Get(NVSDK_NGX_Parameter_Reset,&out))) return true;
        int x{};
        if (!NVSDK_NGX_SUCCEED(value->Get(NVSDK_NGX_Parameter_Reset,&x)) || x<0) return false;
        signed_reset=true;out=static_cast<unsigned>(x);return true;
    }
    void set_reset(unsigned x) {
        if (signed_reset) value->Set(NVSDK_NGX_Parameter_Reset,static_cast<int>(x));
        else value->Set(NVSDK_NGX_Parameter_Reset,x);
    }
};
}
