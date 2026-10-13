#include "JoeyCopyABI.hpp"
using namespace duoview_joey;
void d3d12::CommandContext::reset() {}
extern "C" __declspec(dllexport) bool fixture_copy(void* self,uint32_t index,ID3D12Resource* source,
 CopyCallback pre,ExtraCallback extra,D3D12_RESOURCE_STATES state,D3D12_BOX* box,
 CopyCallback post,ID3D12Resource* retained,RetainedPair pair) {
 if(self!=reinterpret_cast<void*>(0x1234) || index!=7 || source!=reinterpret_cast<ID3D12Resource*>(0x4321) ||
    state!=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE || !box || box->right!=37 ||
    retained!=source || (pair && pair.get()!=reinterpret_cast<uevr::stalker2_native::PairFrame*>(0x123456))) return false;
 d3d12::CommandContext commands;
 if(pre) (*pre)(commands,source);
 if(extra) (*extra)(commands);
 if(post) (*post)(commands,source);
 return true;
}
