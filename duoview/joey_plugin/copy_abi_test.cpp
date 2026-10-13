#include "JoeyCopyABI.hpp"
#include <cassert>
#include <cstddef>
#include <iostream>
using namespace duoview_joey;
static_assert(sizeof(CopyCallback)==72);
static_assert(sizeof(RetainedPair)==16);
static_assert(offsetof(d3d12::CommandContext,cmd_list)==16);
static_assert(offsetof(d3d12::CommandContext,fence_value)==32);
static_assert(offsetof(d3d12::CommandContext,mtx)==48);
static_assert(offsetof(d3d12::CommandContext,has_commands)==129);
static_assert(offsetof(d3d12::CommandContext,poisoned)==130);
CopyFn original;
bool detour(void* self,uint32_t i,ID3D12Resource* s,CopyCallback a,ExtraCallback b,
 D3D12_RESOURCE_STATES state,D3D12_BOX* box,CopyCallback c,ID3D12Resource* keep,RetainedPair pair) {
 return original(self,i,s,std::move(a),std::move(b),state,box,std::move(c),keep,std::move(pair));
}
int main(int argc,char** argv) {
 assert(argc==2);auto module=LoadLibraryA(argv[1]);assert(module);
 original=reinterpret_cast<CopyFn>(GetProcAddress(module,"fixture_copy"));assert(original);
 int calls=0;auto lease=std::make_shared<int>(1);std::weak_ptr<int> lifetime=lease;
 CopyCallback a=std::function<void(d3d12::CommandContext&,ID3D12Resource*)>([&,lease](auto&,auto* s){assert(s==reinterpret_cast<ID3D12Resource*>(0x4321));++calls;});
 ExtraCallback b=std::function<void(d3d12::CommandContext&)>([&,lease](auto&){++calls;});
 CopyCallback c=a;lease.reset();D3D12_BOX box{};box.right=37;
 assert(detour(reinterpret_cast<void*>(0x1234),7,reinterpret_cast<ID3D12Resource*>(0x4321),
  std::move(a),std::move(b),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,&box,std::move(c),
  reinterpret_cast<ID3D12Resource*>(0x4321),nullptr));
 assert(calls==3);a.reset();b.reset();c.reset();assert(lifetime.expired());
 assert(detour(reinterpret_cast<void*>(0x1234),7,reinterpret_cast<ID3D12Resource*>(0x4321),
  std::nullopt,std::nullopt,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,&box,std::nullopt,
  reinterpret_cast<ID3D12Resource*>(0x4321),nullptr));
 FreeLibrary(module);std::cout<<"Cross-DLL MSVC copy ABI, exact CommandContext layout and callback destruction PASS\n";
}
