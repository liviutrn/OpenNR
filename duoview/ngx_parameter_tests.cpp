#include "DuoViewNgxParameters.hpp"
#include "DuoViewDlssHistoryPolicy.hpp"
#include <cassert>
#include <cstring>
#include <iostream>
using namespace uevr::duoview;
struct FakeParameters final:NVSDK_NGX_Parameter {
    unsigned value{},writes{};bool signed_only{},missing{};
    void Set(const char*,unsigned x) override { value=x;++writes; }
    void Set(const char*,int x) override { value=static_cast<unsigned>(x);++writes; }
    NVSDK_NGX_Result Get(const char* name,unsigned* out) const override {
        if (missing || signed_only || std::strcmp(name,NVSDK_NGX_Parameter_Reset)) return NVSDK_NGX_Result_Fail;
        *out=value;return NVSDK_NGX_Result_Success;
    }
    NVSDK_NGX_Result Get(const char* name,int* out) const override {
        if (missing || std::strcmp(name,NVSDK_NGX_Parameter_Reset)) return NVSDK_NGX_Result_Fail;
        *out=static_cast<int>(value);return NVSDK_NGX_Result_Success;
    }
#define UNUSED_SET(T) void Set(const char*,T) override {}
    UNUSED_SET(unsigned long long) UNUSED_SET(float) UNUSED_SET(double)
    UNUSED_SET(ID3D11Resource*) UNUSED_SET(ID3D12Resource*) UNUSED_SET(void*)
#undef UNUSED_SET
#define UNUSED_GET(T) NVSDK_NGX_Result Get(const char*,T*) const override { return NVSDK_NGX_Result_Fail; }
    UNUSED_GET(unsigned long long) UNUSED_GET(float) UNUSED_GET(double)
    UNUSED_GET(ID3D11Resource*) UNUSED_GET(ID3D12Resource*) UNUSED_GET(void*)
#undef UNUSED_GET
    void Reset() override {}
};
int main() {
    for (bool signed_only:{false,true}) {
        FakeParameters parameters;parameters.signed_only=signed_only;
        ngx::ResetParameters adapter{&parameters};
        { DlssResetScope reset{adapter,true};assert(reset.active() && parameters.value==1); }
        assert(parameters.value==0 && parameters.writes==2);
        parameters.value=1;parameters.writes=0;
        { DlssResetScope reset{adapter,true};assert(!reset.active()); }
        assert(parameters.value==1 && parameters.writes==0);
        parameters.missing=true;parameters.value=0;
        { DlssResetScope reset{adapter,true};assert(!reset.active()); }
        assert(parameters.value==0 && parameters.writes==0);
    }
    std::cout << "Official NGX interface: signed/unsigned reset ABI, authored reset and restoration passed\n";
}
