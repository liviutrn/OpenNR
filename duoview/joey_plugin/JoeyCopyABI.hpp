#pragma once
// The exact released Joey embedded-commit header, supplied by the pinned
// JOEY_SOURCE checkout. Do not use the older plugin-header reference here.
#include "mods/vr/d3d12/CommandContext.hpp"
#include <functional>
#include <optional>
#include <memory>
namespace uevr::stalker2_native { struct PairFrame; }
namespace duoview_joey {
using CopyCallback=std::optional<std::function<void(d3d12::CommandContext&,ID3D12Resource*)>>;
using ExtraCallback=std::optional<std::function<void(d3d12::CommandContext&)>>;
using RetainedPair=std::shared_ptr<uevr::stalker2_native::PairFrame>;
// This is a C++ ABI signature, including all by-value wrapper objects. Both
// trampoline and detour use it. Forward with std::move, never byte-copy or
// reinterpret a std::function/shared_ptr as a simplified C signature.
using CopyFn=bool(*)(void*,uint32_t,ID3D12Resource*,CopyCallback,ExtraCallback,
    D3D12_RESOURCE_STATES,D3D12_BOX*,CopyCallback,ID3D12Resource*,RetainedPair);
}
