#include "VRPresenter.h"

#include "Log.h"

#include <d3d12.h>
#include <openvr.h>

namespace {
    const char* CompositorError(vr::EVRCompositorError error) {
        switch (error) {
        case vr::VRCompositorError_None: return "none";
        case vr::VRCompositorError_DoNotHaveFocus: return "do-not-have-focus";
        case vr::VRCompositorError_InvalidTexture: return "invalid-texture";
        case vr::VRCompositorError_TextureIsOnWrongDevice: return "texture-on-wrong-device";
        case vr::VRCompositorError_TextureUsesUnsupportedFormat: return "unsupported-format";
        case vr::VRCompositorError_SharedTexturesNotSupported: return "shared-textures-not-supported";
        case vr::VRCompositorError_AlreadySubmitted: return "already-submitted";
        case vr::VRCompositorError_InvalidBounds: return "invalid-bounds";
        default: return "unknown";
        }
    }
}

VRPresenter::~VRPresenter() { Shutdown(); }

bool VRPresenter::Initialize() {
    Shutdown();
    m_hmdPresent = vr::VR_IsHmdPresent();
    vr::EVRInitError error = vr::VRInitError_None;
    m_system = vr::VR_Init(&error, vr::VRApplication_Scene);
    if (!m_system) {
        m_lastError = vr::VR_GetVRInitErrorAsEnglishDescription(error);
        LOG("OpenVR unavailable: " << m_lastError);
        return false;
    }
    m_compositor = vr::VRCompositor();
    if (!m_compositor) {
        m_lastError = "SteamVR compositor interface is unavailable";
        LOG(m_lastError);
        vr::VR_Shutdown();
        m_system = nullptr;
        return false;
    }
    m_system->GetRecommendedRenderTargetSize(&m_recommendedWidth, &m_recommendedHeight);
    LOG("OpenVR ready: HMD=" << (m_hmdPresent ? "present" : "not-present")
        << " recommended=" << m_recommendedWidth << "x" << m_recommendedHeight);
    return true;
}

void VRPresenter::Shutdown() {
    if (m_system || m_compositor)
        vr::VR_Shutdown();
    m_system = nullptr;
    m_compositor = nullptr;
    m_hmdPresent = false;
    m_recommendedWidth = 0;
    m_recommendedHeight = 0;
}

bool VRPresenter::BeginFrame() {
    if (!m_compositor)
        return false;
    vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
    const auto error = m_compositor->WaitGetPoses(poses, vr::k_unMaxTrackedDeviceCount, nullptr, 0);
    if (error != vr::VRCompositorError_None) {
        m_lastError = std::string("WaitGetPoses: ") + CompositorError(error);
        return false;
    }
    return true;
}

bool VRPresenter::Submit(ID3D12Resource* source, ID3D12CommandQueue* queue, Layout layout) {
    if (!m_compositor || !source || !queue)
        return false;

    vr::D3D12TextureData_t data{};
    data.m_pResource = source;
    data.m_pCommandQueue = queue;
    data.m_nNodeMask = 1;
    vr::Texture_t texture{};
    texture.handle = &data;
    texture.eType = vr::TextureType_DirectX12;
    texture.eColorSpace = vr::ColorSpace_Linear;

    vr::VRTextureBounds_t left{0.0f, 0.0f, 1.0f, 1.0f};
    vr::VRTextureBounds_t right = left;
    if (layout == Layout::SideBySide) {
        left = {0.0f, 0.0f, 0.5f, 1.0f};
        right = {0.5f, 0.0f, 1.0f, 1.0f};
    } else if (layout == Layout::OverUnder) {
        left = {0.0f, 0.0f, 1.0f, 0.5f};
        right = {0.0f, 0.5f, 1.0f, 1.0f};
    }

    auto error = m_compositor->Submit(vr::Eye_Left, &texture, &left, vr::Submit_Default);
    if (error != vr::VRCompositorError_None) {
        m_lastError = std::string("Submit left eye: ") + CompositorError(error);
        return false;
    }
    error = m_compositor->Submit(vr::Eye_Right, &texture, &right, vr::Submit_Default);
    if (error != vr::VRCompositorError_None) {
        m_lastError = std::string("Submit right eye: ") + CompositorError(error);
        return false;
    }
    return true;
}

void VRPresenter::PostPresent() {
    if (m_compositor)
        m_compositor->PostPresentHandoff();
}
