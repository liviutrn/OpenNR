// Native bridge: the OpenXR layer is loaded by UEVR's statically linked loader.
// The existing UEVR plugin only sends Lua settings and records the GPU shader;
// it MUST NOT detour arbitrary openxr_loader.dll entry points.
#define WIN32_LEAN_AND_MEAN
#include <Windows.h>
#include <cstdint>
namespace {
using Snapshot = void(__cdecl*)(uint64_t*,uint32_t);
uint64_t status(unsigned field) {
    HMODULE m=GetModuleHandleW(L"GlamaryeOpenXRLayer.dll");
    if(!m) return 0;
    auto fn=reinterpret_cast<Snapshot>(GetProcAddress(m,"glamayre_layer_get_status"));
    if(!fn) return 0;
    uint64_t values[8]{};
    fn(values,8);
    return field<8?values[field]:0;
}
}
extern "C" void glamayre_xr_tick(const void*) {}
extern "C" void glamayre_xr_reset_buffers() {}
extern "C" bool glamayre_xr_hooks_ready() {return status(0)!=0;}
extern "C" bool glamayre_xr_resolved_hooks_ready(){return false;}
extern "C" unsigned long long glamayre_xr_acquire_count(){return status(1);}
extern "C" unsigned long long glamayre_xr_release_count(){return status(2);}
extern "C" unsigned long long glamayre_xr_endframe_count(){return status(3);}
extern "C" unsigned long long glamayre_xr_projection_count(){return status(4);}
extern "C" unsigned long long glamayre_xr_dimension_count(){return status(4);}
extern "C" unsigned long long glamayre_xr_eligible_count(){return status(5);}
extern "C" unsigned long long glamayre_xr_processed_count(){return status(5);}
extern "C" unsigned long long glamayre_xr_enum_failed(){return status(7);}
