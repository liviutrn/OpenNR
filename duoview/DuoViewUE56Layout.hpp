#pragma once
// ABI evidence for the shipping UE5.6 FSceneView layout used by STALKER2.
//
// This is a byte-layout mirror, not a replacement UE type.  Every member and
// size below comes from Epic's UE5.6.1 SceneView.h and the Core container
// declarations at commit 21c8b14bfff55c51074d960563d1d92056a9b09a.  The
// runtime writer is additionally gated by live Family/State/projection/rect
// validation before it ever touches ClipToPrevClipOverride.
#include <array>
#include <cstddef>
#include <cstdint>

namespace uevr::duoview::ue56::layout {

template <size_t Size, size_t Alignment>
struct alignas(Alignment) Bytes {
    std::byte data[Size];
};

using Matrix = Bytes<0x80, 16>;             // FMatrix / UE::Math::TMatrix<double>
using Vector = Bytes<0x18, 8>;              // FVector / UE::Math::TVector<double>
using Rotator = Bytes<0x18, 8>;             // FRotator (three doubles)
using Quat = Bytes<0x20, 16>;               // FQuat / TQuat<double>
using Transform = Bytes<0x60, 16>;          // FTransform / TTransform<double>
using Plane = Bytes<0x20, 16>;              // FPlane / TPlane<double>
using Vector4f = Bytes<0x10, 4>;
using Vector2f = Bytes<0x08, 4>;
using Vector2d = Bytes<0x10, 8>;
using IntRect = Bytes<0x10, 4>;
using IntPoint = Bytes<0x08, 4>;
using LinearColor = Bytes<0x10, 4>;
using Name = Bytes<0x0c, 4>;                // FName: two FNameEntryId + int32
using ViewOwner = Bytes<0x10, 8>;           // uint32 ActorUniqueId + AActor*
using SharedPtr = Bytes<0x10, 8>;            // TSharedPtr<FConvexVolume>
using Set = Bytes<0x50, 8>;                 // TSet<FPrimitiveComponentId>
using ConvexVolume = Bytes<0x200, 16>;      // two TArray<FPlane, TInlineAllocator<N>>
using FirstPerson = Bytes<0x0c, 4>;         // 2 floats + bool + padding

struct Optional32 {
    uint32_t value{};
    bool set{};
};
struct OptionalBool {
    bool value{};
    bool set{};
};
struct OptionalMatrix {
    Matrix value{};
    bool set{};
};
struct OptionalTransform {
    Transform value{};
    bool set{};
};

struct SceneViewProjectionData {
    Vector ViewOrigin;
    Matrix ViewRotationMatrix;
    Matrix ProjectionMatrix;
    IntRect ViewRect;
    Vector CameraToViewTarget;
    IntRect ConstrainedViewRect;
};

struct InitOptions {
    SceneViewProjectionData ProjectionData;
    void* ViewFamily;
    void* SceneViewStateInterface;
    void* ExposureSceneViewStateInterface;
    ViewOwner ViewActor;
    int32_t PlayerIndex;
    void* ViewElementDrawer;
    LinearColor BackgroundColor;
    LinearColor OverlayColor;
    LinearColor ColorScale;
    int32_t StereoPass;
    int32_t StereoViewIndex;
    float WorldToMetersScale;
    Vector ViewLocation;
    Rotator ViewRotation;
    Set HiddenPrimitives;
    Set ShowOnlyPrimitives;
    IntPoint CursorPos;
    float LODDistanceFactor;
    float OverrideFarClippingPlaneDistance;
    Vector OriginOffsetThisFrame;
    bool bInCameraCut;
    bool bUseFieldOfViewForLOD;
    float FOV;
    float DesiredFOV;
    FirstPerson FirstPersonParams;
    bool bIsSceneCapture;
    bool bIsSceneCaptureCube;
    bool bSceneCaptureUsesRayTracing;
    bool bIsReflectionCapture;
    bool bIsPlanarReflection;
    bool bExcludeFromSceneTextureExtents;
    float OverridePrimaryResolutionFraction;
    float OverscanResolutionFraction;
    float CropFraction;
    Vector4f AsymmetricCropFraction;
};

struct ViewMatricesData {
    Matrix ProjectionMatrix;
    Matrix ProjectionNoAAMatrix;
    Matrix InvProjectionMatrix;
    Matrix ViewMatrix;
    Matrix InvViewMatrix;
    Matrix ViewProjectionMatrix;
    Matrix InvViewProjectionMatrix;
    Matrix HMDViewMatrixNoRoll;
    Matrix TranslatedViewMatrix;
    Matrix InvTranslatedViewMatrix;
    Matrix OverriddenTranslatedViewMatrix;
    Matrix OverriddenInvTranslatedViewMatrix;
    Matrix TranslatedViewProjectionMatrix;
    Matrix InvTranslatedViewProjectionMatrix;
    Matrix ScreenToClipMatrix;
    Matrix FirstPersonTransform;
    Vector PreViewTranslation;
    Vector ViewOrigin;
    Vector CameraToViewTarget;
    Vector2d ProjectionScale;
    Vector2d TemporalAAProjectionJitter;
    float ScreenScale;
    float PerProjectionDepthThicknessScale;
    FirstPerson FirstPersonParams;
};

struct SceneView {
    void* VTable;
    void* Family;
    void* State;
    void* ViewUniformBuffer;
    void* DynamicMeshElementsShadowCullFrustum;
    Vector PreShadowTranslation;
    SharedPtr StereoCullingFrustum;
    InitOptions SceneViewInitOptions;
    ViewOwner ViewActor;
    int32_t PlayerIndex;
    void* Drawer;
    IntRect UnscaledViewRect;
    IntRect UnconstrainedViewRect;
    int32_t MaxShadowCascades;
    ViewMatricesData ViewMatrices;
    Vector ViewLocation;
    Rotator ViewRotation;
    Quat BaseHmdOrientation;
    Vector BaseHmdLocation;
    float WorldToMetersScale;
    OptionalTransform PreviousViewTransform;
    uint8_t ShadowViewMatrices;
    Matrix ProjectionMatrixUnadjustedForRHI;
    LinearColor BackgroundColor;
    LinearColor OverlayColor;
    LinearColor ColorScale;
    int32_t StereoPass;
    int32_t StereoViewIndex;
    int32_t PrimaryViewIndex;
    bool bAllowCrossGPUTransfer;
    bool bOverrideGPUMask;
    uint32_t GPUMask;
    bool bRenderFirstInstanceOnly;
    bool bUseFieldOfViewForLOD;
    bool bHMDHiddenAreaMaskActive;
    float FOV;
    float DesiredFOV;
    int32_t DrawDynamicFlags;
    Name CurrentBufferVisualizationMode;
    Name CurrentNaniteVisualizationMode;
    Name CurrentLumenVisualizationMode;
    Name CurrentSubstrateVisualizationMode;
    Name CurrentGroomVisualizationMode;
    Name CurrentVirtualShadowMapVisualizationMode;
    Name CurrentVirtualTextureVisualizationMode;
    Name CurrentVisualizeCalibrationColorMaterialName;
    Name CurrentVisualizeCalibrationGrayscaleMaterialName;
    Name CurrentVisualizeCalibrationCustomMaterialName;
    Name CurrentGPUSkinCacheVisualizationMode;
    Vector4f DiffuseOverrideParameter;
    Vector4f SpecularOverrideParameter;
    Vector4f NormalOverrideParameter;
    Vector2f RoughnessOverrideParameter;
    Vector2f AmbientOcclusionOverrideParameter;
    float MaterialTextureMipBias;
    Set HiddenPrimitives;
    Set ShowOnlyPrimitives;
    bool bAllowTemporalJitter;
    ConvexVolume ViewFrustum;
    uint8_t CullingFrustum;
    bool bHasNearClippingPlane;
    Plane NearClippingPlane;
    float NearClippingDistance;
    Vector CullingOrigin;
    bool bReverseCulling;
    Vector4f InvDeviceZToWorldZTransform;
    Vector OriginOffsetThisFrame;
    float LODDistanceFactor;
    bool bCameraCut;
    IntPoint CursorPos;
    bool bIsGameView;
    bool bIsViewInfo;
    void* CustomRenderPass;
    bool bIsSceneCapture;
    bool bIsSceneCaptureCube;
    bool bEyeAdaptationAllViewPixels;
    bool bSceneCaptureUsesRayTracing;
    bool bIsReflectionCapture;
    bool bIsPlanarReflection;
    bool bIsVirtualTexture;
    bool bIsOfflineRender;
    bool bRenderSceneTwoSided;
    bool bIsLocked;
    bool bStaticSceneOnly;
    bool bIsInstancedStereoEnabled;
    bool bIsMultiViewportEnabled;
    bool bIsMobileMultiViewEnabled;
    bool bShouldBindInstancedViewUB;
    bool bIsSinglePassStereo;
    bool bForceCameraVisibilityReset;
    bool bDisableDistanceBasedFadeTransitions;
    bool bExcludeFromSceneTextureExtents;
    bool bForcePathTracerReset;
    int32_t PathTracerSeedOffset;
    float UnderwaterDepth;
    uint8_t WaterIntersection;
    Plane GlobalClippingPlane;
    IntRect CameraConstrainedViewRect;
    Vector TranslucentSortAxis;
    uint8_t TranslucentSortPolicy;
    Optional32 OverrideFrameIndexValue;
    Optional32 OverrideOutputFrameIndexValue;
    Vector4f LensPrincipalPointOffsetScale;
    OptionalBool bCameraMotionBlur;
    OptionalMatrix ClipToPrevClipOverride;
};

static_assert(sizeof(SceneViewProjectionData) == 0x160);
static_assert(offsetof(InitOptions, ViewFamily) == 0x160);
static_assert(offsetof(InitOptions, ProjectionData) == 0x000);
static_assert(offsetof(InitOptions, ProjectionData) +
              offsetof(SceneViewProjectionData, ProjectionMatrix) == 0x0a0);
static_assert(offsetof(InitOptions, ProjectionData) +
              offsetof(SceneViewProjectionData, ViewRect) == 0x120);
static_assert(offsetof(InitOptions, ProjectionData) +
              offsetof(SceneViewProjectionData, ConstrainedViewRect) == 0x148);
static_assert(sizeof(InitOptions) == 0x310);
static_assert(offsetof(SceneView, Family) == 0x08);
static_assert(offsetof(SceneView, State) == 0x10);
static_assert(offsetof(SceneView, SceneViewInitOptions) == 0x50);
static_assert(offsetof(SceneView, ViewMatrices) == 0x3b0);
static_assert(offsetof(SceneView, ClipToPrevClipOverride) == 0x12a0);
static_assert(sizeof(OptionalMatrix) == 0x90);
static_assert(sizeof(OptionalTransform) == 0x70);
static_assert(sizeof(SceneView) == 0x1330);

inline constexpr size_t scene_view_family_offset = offsetof(SceneView, Family);
inline constexpr size_t scene_view_state_offset = offsetof(SceneView, State);
inline constexpr size_t scene_view_init_options_offset = offsetof(SceneView, SceneViewInitOptions);
inline constexpr size_t init_options_view_origin_offset =
    offsetof(InitOptions, ProjectionData) + offsetof(SceneViewProjectionData, ViewOrigin);
inline constexpr size_t init_options_view_rotation_offset =
    offsetof(InitOptions, ProjectionData) + offsetof(SceneViewProjectionData, ViewRotationMatrix);
inline constexpr size_t init_options_projection_offset =
    offsetof(InitOptions, ProjectionData) + offsetof(SceneViewProjectionData, ProjectionMatrix);
inline constexpr size_t init_options_view_rect_offset =
    offsetof(InitOptions, ProjectionData) + offsetof(SceneViewProjectionData, ViewRect);
inline constexpr size_t init_options_family_offset = offsetof(InitOptions, ViewFamily);
inline constexpr size_t init_options_state_offset = offsetof(InitOptions, SceneViewStateInterface);
inline constexpr size_t clip_to_prev_clip_override_offset = offsetof(SceneView, ClipToPrevClipOverride);

} // namespace uevr::duoview::ue56::layout
