#pragma once

#include <cstdint>
#include <string>

struct ID3D12CommandQueue;
struct ID3D12Resource;

namespace vr { class IVRSystem; class IVRCompositor; }

class VRPresenter {
public:
    enum class Layout { Mono, SideBySide, OverUnder };

    VRPresenter() = default;
    ~VRPresenter();
    VRPresenter(const VRPresenter&) = delete;
    VRPresenter& operator=(const VRPresenter&) = delete;

    bool Initialize();
    void Shutdown();
    bool BeginFrame();
    bool Submit(ID3D12Resource* source, ID3D12CommandQueue* queue, Layout layout);
    void PostPresent();

    bool Active() const { return m_compositor != nullptr; }
    bool HmdPresent() const { return m_hmdPresent; }
    uint32_t RecommendedWidth() const { return m_recommendedWidth; }
    uint32_t RecommendedHeight() const { return m_recommendedHeight; }
    const std::string& LastError() const { return m_lastError; }

private:
    vr::IVRSystem* m_system = nullptr;
    vr::IVRCompositor* m_compositor = nullptr;
    bool m_hmdPresent = false;
    uint32_t m_recommendedWidth = 0;
    uint32_t m_recommendedHeight = 0;
    std::string m_lastError;
};
