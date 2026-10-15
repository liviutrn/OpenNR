#pragma once

// The standalone backend test exercises D3D12 behavior, not log formatting.
// Keep the production header dependency out of this small CTest project.
namespace spdlog {

template <typename... Args>
inline void info(const char*, Args&&...) noexcept {}

} // namespace spdlog
