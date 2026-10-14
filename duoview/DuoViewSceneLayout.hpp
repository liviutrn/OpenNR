#pragma once
#include "DuoViewConfig.hpp"

namespace uevr::duoview {
inline Layout scene_layout(uint32_t width,uint32_t height,const Settings& settings) {
    if (const auto layout=make_layout(width,height,settings.crop_width,settings.crop_height,
        settings.peripheral_scale,settings.foveal_density,.5f,.5f,true)) return *layout;
    return *make_layout(256,256,.5f,.5f,.5f,1.f,.5f,.5f,true);
}
inline Rect scene_rectangle(const Layout& layout,unsigned fovea_view,int raw_index,bool double_precision) {
    const auto index=renderer_view_index(raw_index,double_precision);
    return index<0 || static_cast<unsigned>(index)==fovea_view ? layout.fovea : layout.periphery;
}
}
