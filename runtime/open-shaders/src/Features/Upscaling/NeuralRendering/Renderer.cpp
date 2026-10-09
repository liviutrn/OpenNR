#include "../CropMotion.h"
#include "Renderer.h"

#include "D3D12Interop.h"
#include "RuntimePolicy.h"
#include "../FoveatedRender/CropGeometry.h"
#include "Deferred.h"
#if defined(OPENNR_CAPTURE_ENABLED)
#include "Features/OpenNRCapture.h"
#endif
#include "Features/Upscaling/FoveatedRender/Ops.h"
#include "GpuPass.h"
#include "Globals.h"
#include "State.h"
#include "Utils/D3D.h"
#include "Utils/LazyShader.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <limits>
#include <string>
#include <utility>

#include <d3d11.h>
#include <dxgi.h>
#include <wrl/client.h>

namespace NeuralRendering
{
	namespace
	{
		constexpr std::uint32_t kEyeCount = 2;
		constexpr std::uint32_t kCascadePassCount = 3;
		constexpr std::uint32_t kAdaptiveMinimumResolution = 70;
		// The adaptive controller intentionally stops at 70%. The two lower
		// entries are fixed experimental tiers backed by the captured 50%/33%
		// native-scale studies; they are not adaptive targets and are not
		// temporal-reuse promotion evidence.
		constexpr std::array<std::uint32_t, 9> kResolutionTiers{
			100, 95, 90, 85, 80, 75, 70, 50, 33 };
		constexpr std::uint32_t kResolutionTierCount = static_cast<std::uint32_t>(kResolutionTiers.size());
		constexpr std::uint32_t kTemporalReuseMinCadence = 2;
		constexpr std::uint32_t kTemporalReuseMaxCadence = 4;

	#if defined(OPENNR_CAPTURE_ENABLED)
		struct RendererConditioningSource
		{
			RE::RENDER_TARGET target;
			const char* stage;
		};

		constexpr std::array<RendererConditioningSource, 6> kRendererConditionings{
			RendererConditioningSource{ ALBEDO, "gbuffer_albedo" },
			RendererConditioningSource{ NORMALROUGHNESS, "gbuffer_normal_roughness" },
			RendererConditioningSource{ MASKS, "gbuffer_masks" },
			RendererConditioningSource{ MASKS2, "gbuffer_masks2" },
			RendererConditioningSource{ SPECULAR, "gbuffer_specular" },
			RendererConditioningSource{ REFLECTANCE, "gbuffer_reflectance" },
		};
	#endif

		std::uint32_t ResolutionTierIndex(std::uint32_t modelResolution)
		{
			for (std::uint32_t index = 0; index < kResolutionTierCount; ++index)
				if (kResolutionTiers[index] == modelResolution)
					return index;
			return 0;
		}

		std::uint32_t FeatureSlot(std::uint32_t eyeIndex, std::uint32_t tierIndex, std::uint32_t passIndex)
		{
			return eyeIndex + (passIndex + tierIndex * kCascadePassCount) * kEyeCount;
		}

		constexpr std::uint32_t kPerEyeFeatureSlotCount = kEyeCount * kResolutionTierCount * kCascadePassCount;
		std::uint32_t AtlasFeatureSlot(std::uint32_t tierIndex, std::uint32_t passIndex)
		{
			return kPerEyeFeatureSlotCount + tierIndex * kCascadePassCount + passIndex;
		}

		std::uint32_t GetPassCount(const Tuning& tuning)
		{
			if (tuning.multiPass == 0)
				return 1;
			const auto requested = std::min(tuning.multiPass + 1, kCascadePassCount);
			return tuning.secondPass.coveragePercent < 100 ? std::min(requested, 2u) : requested;
		}

		Tuning TuningForCascadePass(const Tuning& tuning, std::uint32_t passIndex)
		{
			if (passIndex != 1)
				return tuning;
			Tuning out = tuning;
			const auto& pass = tuning.secondPass;
			out.intensity = pass.intensity;
			out.localToneStrength = pass.localToneStrength;
			out.localStructureStrength = pass.localStructureStrength;
			out.skinStructureStrength = pass.skinStructureStrength;
			out.style = pass.style;
			out.useAutoMask = pass.useAutoMask;
			out.uiCorrection = pass.uiCorrection;
			// The current v01 stage keeps both sequential evaluations on the same
			// model-resolution tier. Independent pass-2 model resolution is wired in
			// settings but is applied in the later per-pass resolve stage.
			out.multiPass = 0;
			out.temporalReuseCadence = 0;
			out.temporalReuseStaggerEyes = false;
			return out;
		}

		void TransitionEvaluationResources(ID3D12GraphicsCommandList* commandList,
			ID3D12Resource* input, ID3D12Resource* depth, ID3D12Resource* motionVectors,
			ID3D12Resource* output, bool entering)
		{
			D3D12_RESOURCE_BARRIER barriers[4]{};
			ID3D12Resource* resources[4]{ input, depth, motionVectors, output };
			for (std::size_t index = 0; index < std::size(barriers); ++index) {
				barriers[index].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
				barriers[index].Transition.pResource = resources[index];
				barriers[index].Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
				barriers[index].Transition.StateBefore = entering ? D3D12_RESOURCE_STATE_COMMON :
					(index == 3 ? D3D12_RESOURCE_STATE_UNORDERED_ACCESS : D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
				barriers[index].Transition.StateAfter = entering ?
					(index == 3 ? D3D12_RESOURCE_STATE_UNORDERED_ACCESS : D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE) :
					D3D12_RESOURCE_STATE_COMMON;
			}
			commandList->ResourceBarrier(static_cast<UINT>(std::size(barriers)), barriers);
		}

		bool GetTextureDesc(ID3D11Resource* resource, D3D11_TEXTURE2D_DESC& desc)
		{
			Microsoft::WRL::ComPtr<ID3D11Texture2D> texture;
			if (!resource || FAILED(resource->QueryInterface(IID_PPV_ARGS(&texture))))
				return false;
			texture->GetDesc(&desc);
			return true;
		}

	#if defined(OPENNR_CAPTURE_ENABLED)
		bool IsValidCaptureRect(ID3D11Resource* resource, std::uint32_t sourceX, std::uint32_t sourceY,
			std::uint32_t sourceWidth, std::uint32_t sourceHeight)
		{
			D3D11_TEXTURE2D_DESC desc{};
			return GetTextureDesc(resource, desc) &&
				static_cast<std::uint64_t>(sourceX) + sourceWidth <= desc.Width &&
				static_cast<std::uint64_t>(sourceY) + sourceHeight <= desc.Height;
		}

		bool MapConditioningRect(ID3D11Resource* color, std::uint32_t& x, std::uint32_t& y,
			std::uint32_t& width, std::uint32_t& height)
		{
			if (!color)
				return true;
			D3D11_TEXTURE2D_DESC colorDesc{}, nativeDesc{};
			if (!globals::game::renderer || !GetTextureDesc(color, colorDesc) ||
					!GetTextureDesc(Util::AsReal(globals::game::renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kMAIN].texture), nativeDesc) ||
				!colorDesc.Width || !colorDesc.Height || !nativeDesc.Width || !nativeDesc.Height ||
				static_cast<std::uint64_t>(x) + width > colorDesc.Width ||
				static_cast<std::uint64_t>(y) + height > colorDesc.Height)
				return false;
			// Map rectangle edges through the full stereo texture to preserve eye offsets and subrects.
			const auto right = (static_cast<std::uint64_t>(x) + width) * nativeDesc.Width / colorDesc.Width;
			const auto bottom = (static_cast<std::uint64_t>(y) + height) * nativeDesc.Height / colorDesc.Height;
			x = static_cast<std::uint32_t>(static_cast<std::uint64_t>(x) * nativeDesc.Width / colorDesc.Width);
			y = static_cast<std::uint32_t>(static_cast<std::uint64_t>(y) * nativeDesc.Height / colorDesc.Height);
			width = static_cast<std::uint32_t>(right - x);
			height = static_cast<std::uint32_t>(bottom - y);
			return width && height;
		}

		void AppendRendererConditioningAvailability(OpenNRCaptureFeature::FrameInfo& info,
			std::uint32_t sourceX, std::uint32_t sourceY, std::uint32_t sourceWidth, std::uint32_t sourceHeight,
			ID3D11Resource* color = nullptr)
		{
			if (!globals::features::openNRCapture.settings.captureRendererConditionings || !globals::game::renderer)
				return;
			if (!MapConditioningRect(color, sourceX, sourceY, sourceWidth, sourceHeight))
				return;

			auto& targets = globals::game::renderer->GetRuntimeData().renderTargets;
			for (const auto& source : kRendererConditionings) {
				auto* texture = targets[source.target].texture;
				if (!IsValidCaptureRect(Util::AsReal(texture), sourceX, sourceY, sourceWidth, sourceHeight))
					continue;
				if (std::find(info.rendererConditioningsAvailable.begin(), info.rendererConditioningsAvailable.end(), source.stage) ==
					info.rendererConditioningsAvailable.end())
					info.rendererConditioningsAvailable.emplace_back(source.stage);
			}
		}

		void CaptureRendererConditionings(OpenNRCaptureFeature& capture, std::uint32_t sourceX, std::uint32_t sourceY,
			std::uint32_t sourceWidth, std::uint32_t sourceHeight, std::uint32_t eyeIndex, ID3D11Resource* color = nullptr)
		{
			if (!capture.settings.captureRendererConditionings)
				return;
			if (!MapConditioningRect(color, sourceX, sourceY, sourceWidth, sourceHeight)) {
				capture.RecordRendererConditioningDiagnostic({ { "eye", eyeIndex }, { "reason", "native_rect_mapping_failed" } });
				return;
			}
			if (!globals::game::renderer) {
				capture.RecordRendererConditioningDiagnostic({ { "eye", eyeIndex }, { "reason", "renderer_missing" } });
				return;
			}

			auto& targets = globals::game::renderer->GetRuntimeData().renderTargets;
			for (const auto& source : kRendererConditionings) {
				auto* texture = targets[source.target].texture;
				D3D11_TEXTURE2D_DESC desc{};
				const bool hasDesc = GetTextureDesc(Util::AsReal(texture), desc);
				const bool validRect = hasDesc && sourceWidth && sourceHeight &&
					static_cast<std::uint64_t>(sourceX) + sourceWidth <= desc.Width &&
					static_cast<std::uint64_t>(sourceY) + sourceHeight <= desc.Height;
				const bool queued = validRect && capture.CaptureTexture(Util::AsReal(texture), sourceX, sourceY,
					sourceWidth, sourceHeight, source.stage, eyeIndex, false, false);
				const char* reason = !texture ? "texture_missing" : !hasDesc ? "not_texture2d" :
					!validRect ? "source_rectangle_out_of_bounds" : !queued ? "copy_not_queued" : "copy_queued";
				auto* deferred = Deferred::GetSingleton();
				capture.RecordRendererConditioningDiagnostic({
					{ "stage", source.stage }, { "eye", eyeIndex }, { "target_slot", static_cast<unsigned>(source.target) },
					{ "texture_present", texture != nullptr }, { "reason", reason }, { "copy_queued", queued },
					{ "source_rect", { sourceX, sourceY, sourceWidth, sourceHeight } },
					{ "texture_desc", { { "width", desc.Width }, { "height", desc.Height },
						{ "array_size", desc.ArraySize }, { "mips", desc.MipLevels },
						{ "samples", desc.SampleDesc.Count }, { "format", static_cast<unsigned>(desc.Format) },
						{ "bind_flags", desc.BindFlags } } },
					{ "deferred_refresh_checks", deferred->conditioningRefreshChecks },
					{ "deferred_refresh_count", deferred->conditioningRefreshCount },
					{ "deferred_last_check_frame", deferred->conditioningLastCheckFrame },
					{ "deferred_refresh_status", deferred->conditioningRefreshStatus }
				});
			}
		}
	#endif

		bool Matches(const SharedTexture& texture, const D3D11_TEXTURE2D_DESC& desc)
		{
			return texture.resource11 && texture.desc.Width == desc.Width && texture.desc.Height == desc.Height &&
			       texture.desc.Format == desc.Format && texture.desc.ArraySize == desc.ArraySize &&
			       texture.desc.MipLevels == desc.MipLevels && texture.desc.SampleDesc.Count == desc.SampleDesc.Count;
		}

		bool MatchesResolved(const Microsoft::WRL::ComPtr<ID3D11Texture2D>& texture,
			const D3D11_TEXTURE2D_DESC& desc)
		{
			if (!texture)
				return false;
			D3D11_TEXTURE2D_DESC actual{};
			texture->GetDesc(&actual);
			return actual.Width == desc.Width && actual.Height == desc.Height &&
				actual.Format == desc.Format && actual.ArraySize == desc.ArraySize &&
				actual.MipLevels == desc.MipLevels && actual.SampleDesc.Count == desc.SampleDesc.Count;
		}

		std::uint32_t NormalizeModelResolution(std::uint32_t percent)
		{
			if (std::find(kResolutionTiers.begin(), kResolutionTiers.end(), percent) != kResolutionTiers.end())
				return percent;
			// Keep the renderer-side safety net aligned with FoveatedRender::ClampSettings.
			// Values below the experimental 33% floor use 33%; legacy/intermediate
			// values in the old 70%-floor range remain conservative at 70% rather
			// than silently re-enabling full-cost NR.
			if (percent < 33)
				return 33;
			if (percent < 70)
				return 70;
			return 100;
		}

		struct ModelResolveSettings
		{
			float transferStrength;
			float colourStrength;
			float maxRatio;
			float residualStrength;
		};

		struct alignas(16) AdaptiveHandoffConstants
		{
			std::uint32_t colorWidth = 0;
			std::uint32_t colorHeight = 0;
			std::uint32_t guideWidth = 0;
			std::uint32_t guideHeight = 0;
			float motionScaleX = 1.0f;
			float motionScaleY = 1.0f;
			float blendAlpha = 1.0f;
			float depthThreshold = 0.05f;
			std::uint32_t historyValid = 0;
			std::uint32_t useDepth = 1;
			std::uint32_t padding0 = 0;
			std::uint32_t padding1 = 0;
		};
		static_assert(sizeof(AdaptiveHandoffConstants) == 48);

		ModelResolveSettings GetModelResolveSettings(std::uint32_t modelResolution)
		{
			// Reduced Feature 18 output is temporally less reliable around fine
			// shadow/light transitions. Near-native model resolutions have enough
			// spatial support to carry a substantially larger contribution. The
			// Adaptive controls stop at the conservative 70% floor; 50% and 33%
			// remain fixed experimental tiers only.
			switch (modelResolution) {
			case 95:
				return { 1.00f, 0.92f, 1.75f, 0.95f };
			case 90:
				return { 1.00f, 0.80f, 1.60f, 0.90f };
			case 85:
				return { 0.98f, 0.70f, 1.55f, 0.84f };
			case 80:
				return { 0.95f, 0.61f, 1.52f, 0.80f };
			case 75:
				// Matched-residual calibration: the retained 75% study recovered
				// substantially more effect at strength 1.00 with only a small
				// reconstruction-error change.
				return { 0.90f, 0.52f, 1.50f, 1.00f };
			case 70:
				return { 0.86f, 0.45f, 1.45f, 0.72f };
			case 67:
				return { 0.83f, 0.40f, 1.42f, 0.70f };
			case 60:
				return { 0.76f, 0.30f, 1.38f, 0.66f };
			case 50:
				// Fixed experimental tier calibrated against the eight-sequence
				// native replay; keep the source bound and the full residual effect.
				return { 0.70f, 0.22f, 1.50f, 1.00f };
			case 33:
				// Same calibrated matched-residual contract for the high-headroom
				// fixed tier. This remains a live-test candidate, not a promotion.
				return { 0.60f, 0.18f, 1.50f, 1.00f };
			default:
				// Full resolution bypasses this resolve stage. Keep a safe default
				// here in case the helper is called independently in the future.
				return { 1.00f, 1.00f, 4.00f, 1.00f };
			}
		}

		std::uint32_t ScaleDimension(std::uint32_t dimension, std::uint32_t percent)
		{
			return std::max<std::uint32_t>(1, static_cast<std::uint32_t>(
				(static_cast<std::uint64_t>(dimension) * percent + 50) / 100));
		}

		D3D11_TEXTURE2D_DESC MakeSharedDesc(const D3D11_TEXTURE2D_DESC& source, std::uint32_t width,
			std::uint32_t height, UINT bindFlags)
		{
			auto desc = source;
			desc.Width = width;
			desc.Height = height;
			desc.MipLevels = 1;
			desc.ArraySize = 1;
			desc.SampleDesc.Count = 1;
			desc.SampleDesc.Quality = 0;
			desc.Usage = D3D11_USAGE_DEFAULT;
			desc.BindFlags = bindFlags;
			desc.CPUAccessFlags = 0;
			desc.MiscFlags = 0;
			return desc;
		}
	}

	class Renderer::State
	{
	public:
		ModelResolveSettings frameResolveSettings{ 1.0f, 1.0f, 4.0f, 1.0f };
		std::chrono::steady_clock::time_point resolveTimestamp{};
		std::uint32_t resolveFrame = UINT32_MAX;
		bool resolveInitialized = false;

		ModelResolveSettings FrameResolveSettings(std::uint32_t resolution, bool adaptive)
		{
			const auto target = GetModelResolveSettings(resolution);
			const auto now = std::chrono::steady_clock::now();
			const auto frame = globals::state ? globals::state->frameCount : 0;
			if (!adaptive || !resolveInitialized) {
				frameResolveSettings = target;
				resolveInitialized = adaptive;
			} else if (frame != resolveFrame) {
				const float dt = std::clamp(std::chrono::duration<float>(now - resolveTimestamp).count(), 0.0f, 0.05f);
				const float weight = 1.0f - std::exp(-dt / 0.20f);
				frameResolveSettings.transferStrength += (target.transferStrength - frameResolveSettings.transferStrength) * weight;
				frameResolveSettings.colourStrength += (target.colourStrength - frameResolveSettings.colourStrength) * weight;
				frameResolveSettings.maxRatio += (target.maxRatio - frameResolveSettings.maxRatio) * weight;
				frameResolveSettings.residualStrength += (target.residualStrength - frameResolveSettings.residualStrength) * weight;
			}
			if (frame != resolveFrame) {
				resolveFrame = frame;
				resolveTimestamp = now;
			}
			return frameResolveSettings;
		}
		struct TemporalTexture
		{
			Microsoft::WRL::ComPtr<ID3D11Texture2D> resource;
			Microsoft::WRL::ComPtr<ID3D11ShaderResourceView> srv;
			Microsoft::WRL::ComPtr<ID3D11UnorderedAccessView> uav;
		};

		struct TemporalEyeState
		{
			TemporalTexture base;
			TemporalTexture residual;
			TemporalTexture depth;
			std::array<TemporalTexture, 2> accumulatedMotion;
			std::uint32_t width = 0;
			std::uint32_t height = 0;
			std::uint32_t guideWidth = 0;
			std::uint32_t guideHeight = 0;
			// Source rectangle in the SBS destination. A crop-local history is only
			// valid while the same eye rectangle is being evaluated. Moving/gaze
			// crops must re-anchor before reuse rather than mixing coordinate spaces.
			std::uint32_t regionX = 0;
			std::uint32_t regionY = 0;
			std::uint32_t accumulatedMotionIndex = 0;
			bool valid = false;
		};

		struct ResultShapingEyeState
		{
			TemporalTexture output;
			// Ping-pong stabilized (unshaped) results: history[historyIndex] is the
			// previous frame, the other slot receives this frame. Swapping replaces a
			// full-eye history copy per eye per frame.
			std::array<TemporalTexture, 2> history;
			std::uint32_t historyIndex = 0;
			TemporalTexture previousBase;
			TemporalTexture previousDepth;
			std::uint32_t width = 0;
			std::uint32_t height = 0;
			std::uint32_t guideWidth = 0;
			std::uint32_t guideHeight = 0;
			std::uint32_t regionX = 0;
			std::uint32_t regionY = 0;
			std::uint32_t modelResolution = 0;
			std::uint32_t historyFrame = UINT32_MAX;
			std::uint32_t historyWidth = 0, historyHeight = 0, historyGuideWidth = 0, historyGuideHeight = 0;
			float transitionRemainingMs = 0.0f;
			DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
			bool valid = false;
			bool historyAllocationFailed = false;
		};

		struct ResultShapingConfigKey
		{
			std::array<float, 22> floats{};
			std::array<std::uint32_t, 6> integers{};
			bool enabled = false;
			bool stabilizeDetail = false;
			bool useAutoMask = false;
			bool uiCorrection = false;
			bool adaptiveResolution = false;
			bool adaptiveHandoff = false;
			bool singlePassLadder = false;
			bool operator==(const ResultShapingConfigKey&) const = default;
		};

		struct alignas(16) TemporalReuseConstants
		{
			std::uint32_t colorWidth = 0;
			std::uint32_t colorHeight = 0;
			std::uint32_t guideWidth = 0;
			std::uint32_t guideHeight = 0;
			float motionScaleX = 1.0f;
			float motionScaleY = 1.0f;
			float depthThreshold = 0.05f;
			float colorTolerance = 0.08f;
			std::uint32_t useDepth = 1;
			std::uint32_t useColor = 1;
			std::uint32_t padding0 = 0;
			std::uint32_t padding1 = 0;
		};
		static_assert(sizeof(TemporalReuseConstants) == 48);

		struct alignas(16) ResultShapingConstants
		{
			std::uint32_t colorWidth = 0;
			std::uint32_t colorHeight = 0;
			std::uint32_t guideWidth = 0;
			std::uint32_t guideHeight = 0;
			float motionScaleX = 1.0f;
			float motionScaleY = 1.0f;
			float frameDeltaSeconds = 1.0f / 90.0f;
			float stabilizeTimeMs = 60.0f;
			float editStrength = 1.0f;
			float brightening = 1.0f;
			float darkening = 1.0f;
			float colorStrength = 1.0f;
			float hueShiftStrength = 1.0f;
			float shadows = 1.0f;
			float midtones = 1.0f;
			float highlights = 1.0f;
			float largeScaleTone = 1.0f;
			float fineDetail = 1.0f;
			float detailRadius = 1.0f;
			float haloSuppression = 0.0f;
			float maxBrighteningStops = 0.0f;
			float maxDarkeningStops = 0.0f;
			float maxColorChangeStops = 0.0f;
			float depthThreshold = 0.05f;
			float colorTolerance = 0.08f;
			std::uint32_t shapeEnabled = 0;
			std::uint32_t stabilizeMode = 0;
			std::uint32_t stabilizeDetail = 0;
			float historyEdgeFadePixels = 0.0f;
			float transitionWeightScale = 1.0f;
			float nearBlackProtection = 0.0f;
			float nearBlackThreshold = 0.035f;
			std::array<std::uint32_t, 4> previousLayout{};
			std::array<float, 2> originDelta{};
			float nearBlackLiftSoftness = 0.001f;
			float resumeBlendAlpha = 1.0f;
		};
		static_assert(sizeof(ResultShapingConstants) == 160);

		ResultShapingConfigKey MakeResultShapingConfigKey(const Tuning& tuning)
		{
			return {
				.floats = {
					tuning.resultEditStrength, tuning.resultBrightening, tuning.resultDarkening, tuning.resultColor,
					tuning.resultHueShiftStrength, tuning.resultShadows, tuning.resultMidtones, tuning.resultHighlights,
					tuning.resultMaxBrighteningStops, tuning.resultMaxDarkeningStops, tuning.resultMaxColorChangeStops,
					tuning.resultLargeScaleTone, tuning.resultFineDetail, tuning.resultDetailRadius,
					tuning.resultHaloSuppression, tuning.stabilizeTimeMs, tuning.stabilizeDepthThreshold,
					tuning.stabilizeColorTolerance, tuning.intensity, tuning.localToneStrength,
					tuning.localStructureStrength, tuning.skinStructureStrength },
				.integers = { tuning.stabilizeMode, tuning.singlePassLadder ? 0u : tuning.modelResolutionPercent, tuning.modelResolveMode,
					tuning.multiPass, tuning.style, tuning.temporalReuseCadence },
				.enabled = tuning.resultShapingEnabled,
				.stabilizeDetail = tuning.stabilizeDetail,
				.useAutoMask = tuning.useAutoMask,
				.uiCorrection = tuning.uiCorrection,
				.adaptiveResolution = tuning.adaptiveResolution,
				.adaptiveHandoff = tuning.adaptiveHandoff,
				.singlePassLadder = tuning.singlePassLadder,
			};
		}

		bool HasResultShapingEffect(const Tuning& tuning)
		{
			return tuning.resultEditStrength != 1.0f || tuning.resultBrightening != 1.0f ||
				tuning.resultDarkening != 1.0f || tuning.resultColor != 1.0f ||
				tuning.resultHueShiftStrength != 1.0f || tuning.resultShadows != 1.0f ||
				tuning.resultMidtones != 1.0f || tuning.resultHighlights != 1.0f ||
				tuning.resultMaxBrighteningStops > 0.0f || tuning.resultMaxDarkeningStops > 0.0f ||
				tuning.resultMaxColorChangeStops > 0.0f || tuning.resultLargeScaleTone != 1.0f ||
				tuning.resultFineDetail != 1.0f || tuning.resultHaloSuppression > 0.0f;
		}

		struct HandoffTexture
		{
			Microsoft::WRL::ComPtr<ID3D11Texture2D> resource;
			Microsoft::WRL::ComPtr<ID3D11ShaderResourceView> srv;
			Microsoft::WRL::ComPtr<ID3D11UnorderedAccessView> uav;
		};

		struct HandoffEyeState
			{
				std::array<HandoffTexture, 2> color;
				HandoffTexture depth;
				std::uint32_t width = 0;
				std::uint32_t height = 0;
				std::uint32_t guideWidth = 0;
				std::uint32_t guideHeight = 0;
				std::uint32_t resourceWidth = 0;
				std::uint32_t resourceHeight = 0;
				std::uint32_t resourceGuideWidth = 0;
				std::uint32_t resourceGuideHeight = 0;
				std::uint32_t regionX = 0;
			std::uint32_t regionY = 0;
			std::uint32_t historyIndex = 0;
			bool valid = false;
		};

		struct TierResources
		{
			SharedTexture modelInput;
			std::array<SharedTexture, kCascadePassCount - 1> cascadeIntermediates;
			SharedTexture secondPassOutput;
			SharedTexture output;
			Microsoft::WRL::ComPtr<ID3D11Texture2D> resolved;
			Microsoft::WRL::ComPtr<ID3D11ShaderResourceView> resolvedSRV;
			Microsoft::WRL::ComPtr<ID3D11UnorderedAccessView> resolvedUAV;
			std::uint32_t modelResolution = 100;
			std::uint32_t passCount = 1;
			bool reducedResolution = false;
		};

		struct StereoAtlasResources
		{
			SharedTexture color;
			SharedTexture depth;
			SharedTexture motionVectors;
			SharedTexture output;
			std::uint32_t colorEyeWidth = 0;
			std::uint32_t colorEyeHeight = 0;
			std::uint32_t guideEyeWidth = 0;
			std::uint32_t guideEyeHeight = 0;
			std::uint32_t colorGuard = 0;
			std::uint32_t guideGuard = 0;
			bool valid = false;
		};

		struct EyeResources
			{
			SharedTexture color;
			SharedTexture depth;
			SharedTexture motionVectors;
			std::array<float, 4> modelSampling{ 1, 1, 0, 0 };
			std::array<float, 2> sceneColorMotionScale{};
			bool movingCrop = false;
			Microsoft::WRL::ComPtr<ID3D11Resource> alignmentMotionSource;
			Microsoft::WRL::ComPtr<ID3D11ShaderResourceView> alignmentMotionSRV;
			std::array<TierResources, kResolutionTierCount> tiers;
			TemporalEyeState temporal;
			ResultShapingEyeState resultShaping;
				std::uint32_t colorWidth = 0;
				std::uint32_t colorHeight = 0;
				std::uint32_t guideWidth = 0;
				std::uint32_t guideHeight = 0;
				std::uint32_t sharedColorWidth = 0;
				std::uint32_t sharedColorHeight = 0;
				std::uint32_t sharedGuideWidth = 0;
				std::uint32_t sharedGuideHeight = 0;
				bool sharedResourcesValid = false;
				TierResidency residency;
				HandoffEyeState handoff;
		};

		struct AdaptivePrewarmWork
		{
			bool valid = false;
			std::uint32_t candidateIndex = 0;
			std::uint32_t tierIndex = UINT32_MAX;
			std::uint32_t eyeIndex = 0;
		};

		State()
		{
			for (auto& eyeReset : resetPending)
				eyeReset.fill(true);
		}

		bool Apply(ID3D11Device* device, ID3D11DeviceContext* context, std::uint32_t eyeIndex,
			ID3D11Resource* color, ID3D11Resource* depth, ID3D11ShaderResourceView* depthSRV,
			ID3D11Resource* motionVectors,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			float motionVectorScaleX, float motionVectorScaleY, const Tuning& tuning)
		{
			RecoverIfReady(device);
			if (failureLatched || !device || !context || eyeIndex >= eyes.size() || !color || !depth || !depthSRV || !motionVectors)
				return false;
			SyncResultShapingConfig(tuning);
			CS_GPU_PASS("NeuralRendering::Evaluate");

			if (!interop.IsInitialized() && !InitializeInterop(device, context))
				return false;
			if (Runtime::Instance().Status() != RuntimeStatus::Initialized && !InitializeRuntime())
				return false;
			const std::uint32_t modelResolution = NormalizeModelResolution(tuning.modelResolutionPercent);
			const std::uint32_t modelWidth = ScaleDimension(colorWidth, modelResolution);
			const std::uint32_t modelHeight = ScaleDimension(colorHeight, modelResolution);
			const std::uint32_t passCount = GetPassCount(tuning);
			const std::uint32_t tierIndex = ResolutionTierIndex(modelResolution);
			const auto resolveSettings = FrameResolveSettings(modelResolution, tuning.adaptiveResolution);
			SyncTemporalReuseConfig(tuning, modelResolution, passCount);
			if (!EnsureResources(device, eyeIndex, color, depth, motionVectors, guideWidth, guideHeight,
				colorWidth, colorHeight, modelWidth, modelHeight, passCount, modelResolution, passCount > 1 ? tuning.secondPass.coveragePercent : 100u,
				tuning.adaptiveResolution, {}, tuning.adaptiveMemoryCeiling))
				return LatchFailure("shared resource creation", interop.LastError());

			auto& eye = eyes[eyeIndex];
			auto& tier = eye.tiers[tierIndex];
			eye.movingCrop = false;
			eye.sceneColorMotionScale = {};
			eye.modelSampling = FoveatedRenderImpl::CropGeometry::ModelSampling(colorWidth, colorHeight,
				modelWidth, modelHeight, modelResolution, 0, 0, false);
			if (!tuning.adaptiveResolution || !tuning.adaptiveHandoff)
				eye.handoff.valid = false;
			context->CopyResource(eye.color.resource11.Get(), color);
			if (tier.reducedResolution && !DispatchModelInput(device, context, eye, tier, colorWidth, colorHeight, modelWidth, modelHeight,
				 tuning.modelResolveMode == 1))
				return LatchFailure("model input downsample", E_FAIL);
			if (!CopyDepthGuide(context, depthSRV, eye.depth.uav11.Get(), guideWidth, guideHeight))
				return LatchFailure("depth guide conversion", E_FAIL);
			context->CopyResource(eye.motionVectors.resource11.Get(), motionVectors);

			const bool temporalCandidate = IsTemporalReuseSupported(tuning, tier) &&
				CanAttemptTemporalReuse(eye, colorWidth, colorHeight, guideWidth, guideHeight, 0, 0) &&
				!tuning.adaptiveResolution && !resetPending[eyeIndex][tierIndex] &&
				(temporalFrameIndex % tuning.temporalReuseCadence) != 0;
			ID3D11UnorderedAccessView* temporalOutputUAV = tier.reducedResolution ?
				tier.resolvedUAV.Get() : tier.output.uav11.Get();
			if (temporalCandidate && TryTemporalReuse(device, context, eye, temporalOutputUAV,
				colorWidth, colorHeight, guideWidth, guideHeight,
				motionVectorScaleX, motionVectorScaleY, tuning)) {
				ID3D11Resource* temporalOutput = tier.reducedResolution ?
					tier.resolved.Get() : tier.output.resource11.Get();
				ID3D11ShaderResourceView* temporalOutputSRV = tier.reducedResolution ?
					tier.resolvedSRV.Get() : tier.output.srv11.Get();
				ID3D11Resource* shapedOutput = ApplyResultShaping(device, context, eye, eyeIndex,
					temporalOutput, temporalOutputSRV, colorWidth, colorHeight, guideWidth, guideHeight,
					0, 0, motionVectorScaleX, motionVectorScaleY, tuning);
				context->CopyResource(color, shapedOutput);
				resetPending[eyeIndex][tierIndex] = false;
				temporalSkippedSinceFull = true;
				AdvanceTemporalFrame(tuning);
				LogTemporalReuseActive(tuning.temporalReuseCadence, false);
#if defined(OPENNR_CAPTURE_ENABLED)
				if (globals::features::openNRCapture.settings.enableCapture) {
					OpenNRCaptureFeature::FrameInfo captureInfo;
					captureInfo.hostFrame = globals::state ? globals::state->frameCount : 0;
					captureInfo.colorWidth = colorWidth;
					captureInfo.colorHeight = colorHeight;
					captureInfo.modelWidth = modelWidth;
					captureInfo.modelHeight = modelHeight;
					captureInfo.modelResolutionPercent = modelResolution;
					captureInfo.guideWidth = guideWidth;
					captureInfo.guideHeight = guideHeight;
					captureInfo.passCount = passCount;
					captureInfo.motionVectorScaleX[eyeIndex] = motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth;
					captureInfo.motionVectorScaleY[eyeIndex] = motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight;
					captureInfo.historyReset[eyeIndex] = false;
					captureInfo.temporalReuse = true;
					captureInfo.temporalFrameIndex = temporalFrameIndex;
					captureInfo.temporalSkippedSinceFull = temporalSkippedSinceFull;
					captureInfo.temporalNextAnchorReset = tuning.temporalReuseResetAfterSkip;
					captureInfo.intensity = tuning.intensity;
					captureInfo.localToneStrength = tuning.localToneStrength;
					captureInfo.localStructureStrength = tuning.localStructureStrength;
					captureInfo.skinStructureStrength = tuning.skinStructureStrength;
					captureInfo.style = tuning.style;
					captureInfo.useAutoMask = tuning.useAutoMask;
					captureInfo.uiCorrection = tuning.uiCorrection;
					captureInfo.route = "feature18_temporal_reuse";
					const bool captureFrame = globals::features::openNRCapture.BeginFrame(captureInfo);
					if (captureFrame) {
						logger::info("[DLSSNR][TemporalDiag] mode=reuse route=single hostFrame={} cadence=N{} temporalFrameIndex={} skippedSinceFull={} nextAnchorReset={}",
							captureInfo.hostFrame, tuning.temporalReuseCadence, captureInfo.temporalFrameIndex,
							captureInfo.temporalSkippedSinceFull, captureInfo.temporalNextAnchorReset);
						const bool writeColorPreview = globals::features::openNRCapture.settings.writeColorPreviews;
						if (globals::features::openNRCapture.settings.capturePreNR) {
							ID3D11Resource* modelInput = tier.reducedResolution ? tier.modelInput.resource11.Get() : eye.color.resource11.Get();
							const auto modelInputWidth = tier.reducedResolution ? modelWidth : colorWidth;
							const auto modelInputHeight = tier.reducedResolution ? modelHeight : colorHeight;
							globals::features::openNRCapture.CaptureTexture(modelInput, 0, 0,
								modelInputWidth, modelInputHeight, "input", eyeIndex, false, writeColorPreview);
							if (globals::features::openNRCapture.IsFullFrameValidationFrame())
								globals::features::openNRCapture.CaptureTexture(modelInput, 0, 0,
									modelInputWidth, modelInputHeight, "input", eyeIndex, true);
						}
						if (globals::features::openNRCapture.settings.captureDepth) {
							globals::features::openNRCapture.CaptureTexture(eye.depth.resource11.Get(), 0, 0,
								guideWidth, guideHeight, "depth", eyeIndex, false, false);
							if (globals::features::openNRCapture.IsFullFrameValidationFrame())
								globals::features::openNRCapture.CaptureTexture(eye.depth.resource11.Get(), 0, 0,
									guideWidth, guideHeight, "depth", eyeIndex, true, false);
						}
						if (globals::features::openNRCapture.settings.captureMotionVectors) {
							globals::features::openNRCapture.CaptureTexture(eye.motionVectors.resource11.Get(), 0, 0,
								guideWidth, guideHeight, "motion_vectors", eyeIndex, false, false);
							if (globals::features::openNRCapture.IsFullFrameValidationFrame())
								globals::features::openNRCapture.CaptureTexture(eye.motionVectors.resource11.Get(), 0, 0,
									guideWidth, guideHeight, "motion_vectors", eyeIndex, true, false);
						}
						if (globals::features::openNRCapture.settings.capturePostNR) {
							globals::features::openNRCapture.CaptureTexture(temporalOutput, 0, 0,
								colorWidth, colorHeight, "temporal_output", eyeIndex, false, writeColorPreview);
							if (globals::features::openNRCapture.IsFullFrameValidationFrame())
								globals::features::openNRCapture.CaptureTexture(temporalOutput, 0, 0,
									colorWidth, colorHeight, "temporal_output", eyeIndex, true);
						}
						globals::features::openNRCapture.EndFrame();
					}
				}
#endif
				return true;
			}

			const bool resetForAnchor = resetPending[eyeIndex][tierIndex] ||
				(temporalSkippedSinceFull && tuning.temporalReuseResetAfterSkip);
#if defined(OPENNR_CAPTURE_ENABLED)
			bool captureFrame = false;
			if (globals::features::openNRCapture.settings.enableCapture) {
				OpenNRCaptureFeature::FrameInfo captureInfo;
				captureInfo.hostFrame = globals::state ? globals::state->frameCount : 0;
				captureInfo.colorWidth = colorWidth;
				captureInfo.colorHeight = colorHeight;
				captureInfo.modelWidth = modelWidth;
				captureInfo.modelHeight = modelHeight;
				captureInfo.modelResolutionPercent = modelResolution;
				captureInfo.guideWidth = guideWidth;
				captureInfo.guideHeight = guideHeight;
				captureInfo.passCount = passCount;
				captureInfo.motionVectorScaleX[eyeIndex] = motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth;
				captureInfo.motionVectorScaleY[eyeIndex] = motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight;
				captureInfo.historyReset[eyeIndex] = resetForAnchor;
				captureInfo.temporalReuse = false;
				captureInfo.temporalFrameIndex = temporalFrameIndex;
				captureInfo.temporalSkippedSinceFull = temporalSkippedSinceFull;
				captureInfo.temporalNextAnchorReset = false;
				captureInfo.intensity = tuning.intensity;
				captureInfo.localToneStrength = tuning.localToneStrength;
				captureInfo.localStructureStrength = tuning.localStructureStrength;
				captureInfo.skinStructureStrength = tuning.skinStructureStrength;
				captureInfo.style = tuning.style;
				captureInfo.useAutoMask = tuning.useAutoMask;
				captureInfo.uiCorrection = tuning.uiCorrection;
				captureInfo.route = "feature18";
			#if defined(OPENNR_CAPTURE_ENABLED)
			AppendRendererConditioningAvailability(captureInfo, 0, 0, colorWidth, colorHeight);
			#endif
				captureFrame = globals::features::openNRCapture.BeginFrame(captureInfo);
				if (captureFrame)
					logger::info("[DLSSNR][TemporalDiag] mode=anchor route=single hostFrame={} cadence=N{} resetSent={} temporalFrameIndex={} skippedSinceFull={}",
						captureInfo.hostFrame, tuning.temporalReuseCadence,
						resetForAnchor,
						captureInfo.temporalFrameIndex, captureInfo.temporalSkippedSinceFull);
			}
			if (captureFrame && globals::features::openNRCapture.settings.capturePreNR) {
				const bool writeColorPreview = globals::features::openNRCapture.settings.writeColorPreviews;
				ID3D11Resource* modelInput = tier.reducedResolution ? tier.modelInput.resource11.Get() : eye.color.resource11.Get();
				const auto modelInputWidth = tier.reducedResolution ? modelWidth : colorWidth;
				const auto modelInputHeight = tier.reducedResolution ? modelHeight : colorHeight;
				globals::features::openNRCapture.CaptureTexture(modelInput, 0, 0,
					modelInputWidth, modelInputHeight, "input", eyeIndex, false, writeColorPreview);
				if (tier.reducedResolution)
					globals::features::openNRCapture.CaptureTexture(eye.color.resource11.Get(), 0, 0,
						colorWidth, colorHeight, "input_source", eyeIndex, false, writeColorPreview);
				if (globals::features::openNRCapture.IsFullFrameValidationFrame())
					globals::features::openNRCapture.CaptureTexture(modelInput, 0, 0,
						modelInputWidth, modelInputHeight, "input", eyeIndex, true);
				if (tier.reducedResolution && globals::features::openNRCapture.IsFullFrameValidationFrame())
					globals::features::openNRCapture.CaptureTexture(eye.color.resource11.Get(), 0, 0,
						colorWidth, colorHeight, "input_source", eyeIndex, true);
			}
			if (captureFrame && globals::features::openNRCapture.settings.captureDepth) {
				globals::features::openNRCapture.CaptureTexture(eye.depth.resource11.Get(), 0, 0,
					guideWidth, guideHeight, "depth", eyeIndex, false, false);
				if (globals::features::openNRCapture.IsFullFrameValidationFrame())
					globals::features::openNRCapture.CaptureTexture(eye.depth.resource11.Get(), 0, 0,
						guideWidth, guideHeight, "depth", eyeIndex, true, false);
			}
			if (captureFrame && globals::features::openNRCapture.settings.captureMotionVectors) {
				globals::features::openNRCapture.CaptureTexture(eye.motionVectors.resource11.Get(), 0, 0,
					guideWidth, guideHeight, "motion_vectors", eyeIndex, false, false);
				if (globals::features::openNRCapture.IsFullFrameValidationFrame())
					globals::features::openNRCapture.CaptureTexture(eye.motionVectors.resource11.Get(), 0, 0,
						guideWidth, guideHeight, "motion_vectors", eyeIndex, true, false);
			}
			#if defined(OPENNR_CAPTURE_ENABLED)
			if (captureFrame)
				CaptureRendererConditionings(globals::features::openNRCapture, 0, 0, colorWidth, colorHeight, eyeIndex);
			#endif
#endif

			ID3D12GraphicsCommandList* commandList = nullptr;
			if (!interop.BeginD3D12(&commandList)) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("BeginD3D12", interop.LastError());
			}
			const bool succeeded = ExecuteCascade(commandList, eyeIndex, tierIndex,
				tier.reducedResolution ? tier.modelInput.resource12.Get() : eye.color.resource12.Get(),
				eye.depth.resource12.Get(), eye.motionVectors.resource12.Get(),
				std::array<ID3D12Resource*, kCascadePassCount - 1>{
					tier.cascadeIntermediates[0].resource12.Get(), tier.cascadeIntermediates[1].resource12.Get() },
				tier.secondPassOutput.resource12.Get(), tier.output.resource12.Get(),
				tier.reducedResolution ? modelWidth : colorWidth,
				tier.reducedResolution ? modelHeight : colorHeight,
				guideWidth, guideHeight, modelWidth, modelHeight,
				tier.reducedResolution ? modelWidth : colorWidth,
				tier.reducedResolution ? modelHeight : colorHeight,
				modelWidth, modelHeight,
				motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth,
				motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight,
				tuning, passCount, resetForAnchor);
			if (!interop.EndD3D12()) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("EndD3D12", interop.LastError());
			}
			if (!succeeded) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("Feature 18", static_cast<HRESULT>(Runtime::Instance().NgxResult()));
			}
			if (passCount == 2 && tuning.secondPass.coveragePercent < 100) {
				const auto pass2Coverage = std::clamp(tuning.secondPass.coveragePercent, 50u, 100u);
				const auto pass2Width = ScaleDimension(modelWidth, pass2Coverage);
				const auto pass2Height = ScaleDimension(modelHeight, pass2Coverage);
				if (!CompositeSequentialPass(device, context, tier, modelWidth, modelHeight,
					pass2Width, pass2Height, tuning))
					return LatchFailure("second-pass composite", E_FAIL);
			}
			if (tier.reducedResolution && !DispatchModelResolve(device, context, eye, tier, colorWidth, colorHeight, resolveSettings,
					tuning.modelResolveMode == 1)) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("model output resolve", E_FAIL);
			}
			if (!tuning.adaptiveResolution && IsTemporalReuseSupported(tuning, tier)) {
				ID3D11ShaderResourceView* teacherSRV = tier.reducedResolution ?
					tier.resolvedSRV.Get() : tier.output.srv11.Get();
				if (!RecordTemporalHistory(device, context, eye, teacherSRV,
					colorWidth, colorHeight, guideWidth, guideHeight, 0, 0))
					InvalidateTemporalHistory();
			}
			temporalSkippedSinceFull = false;
			AdvanceTemporalFrame(tuning);
#if defined(OPENNR_CAPTURE_ENABLED)
			if (captureFrame) {
				if (globals::features::openNRCapture.settings.capturePostNR) {
					const bool writeColorPreview = globals::features::openNRCapture.settings.writeColorPreviews;
					ID3D11Resource* teacher = tier.reducedResolution ? tier.resolved.Get() : tier.output.resource11.Get();
					globals::features::openNRCapture.CaptureTexture(teacher, 0, 0, colorWidth, colorHeight, "teacher", eyeIndex,
						false, writeColorPreview);
					if (tier.reducedResolution && globals::features::openNRCapture.settings.captureRawTeacher)
						globals::features::openNRCapture.CaptureTexture(tier.output.resource11.Get(), 0, 0,
							modelWidth, modelHeight, "teacher_raw", eyeIndex, false, writeColorPreview);
					if (globals::features::openNRCapture.IsFullFrameValidationFrame())
						globals::features::openNRCapture.CaptureTexture(teacher, 0, 0, colorWidth, colorHeight,
							"teacher", eyeIndex, true);
				}
				globals::features::openNRCapture.EndFrame();
			}
#endif
			ID3D11Resource* neuralOutput = tier.reducedResolution ? tier.resolved.Get() : tier.output.resource11.Get();
			ID3D11ShaderResourceView* neuralOutputSRV = tier.reducedResolution ? tier.resolvedSRV.Get() : tier.output.srv11.Get();
			ID3D11Resource* shapedOutput = ApplyResultShaping(device, context, eye, eyeIndex, neuralOutput,
				neuralOutputSRV, colorWidth, colorHeight, guideWidth, guideHeight, 0, 0,
				motionVectorScaleX, motionVectorScaleY, tuning);
			ID3D11ShaderResourceView* shapedOutputSRV = shapedOutput == neuralOutput ? neuralOutputSRV : eye.resultShaping.output.srv.Get();
			ID3D11Resource* writeback = shapedOutput;
			if (tuning.adaptiveResolution && tuning.adaptiveHandoff)
				writeback = ApplyAdaptiveHandoff(device, context, eyeIndex, eye, shapedOutput, shapedOutputSRV,
					colorWidth, colorHeight, guideWidth, guideHeight, motionVectorScaleX, motionVectorScaleY,
					0, 0, tuning);
			context->CopyResource(color, writeback ? writeback : neuralOutput);
			resetPending[eyeIndex][tierIndex] = false;
			return true;
		}

		bool ApplyStereo(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Resource* color,
			const std::array<StereoEyeInput, 2>& inputs,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorWidth, std::uint32_t colorHeight, const Tuning& tuning,
			ID3D11Resource* destination, ID3D11UnorderedAccessView* destinationUAV,
			bool blendSubrect, const StereoResourceEnvelope& resourceEnvelope)
		{
			RecoverIfReady(device);
			if (failureLatched || !device || !context || !color)
				return false;
			SyncResultShapingConfig(tuning);
			ID3D11Resource* writeback = destination ? destination : color;
			if (!writeback)
				return false;
			CS_GPU_PASS("NeuralRendering::EvaluateStereo");

			if (!interop.IsInitialized() && !InitializeInterop(device, context))
				return false;
			if (Runtime::Instance().Status() != RuntimeStatus::Initialized && !InitializeRuntime())
				return false;

			D3D11_TEXTURE2D_DESC colorDesc{};
			if (!GetTextureDesc(color, colorDesc))
				return false;
			const std::uint32_t modelResolution = NormalizeModelResolution(tuning.modelResolutionPercent);
			const std::uint32_t modelWidth = ScaleDimension(colorWidth, modelResolution);
			const std::uint32_t modelHeight = ScaleDimension(colorHeight, modelResolution);
			const bool stableEnvelope = resourceEnvelope.IsValid();
			const std::uint32_t stableColorWidth = stableEnvelope ? resourceEnvelope.colorWidth : colorWidth;
			const std::uint32_t stableColorHeight = stableEnvelope ? resourceEnvelope.colorHeight : colorHeight;
			const std::uint32_t stableGuideWidth = stableEnvelope ? resourceEnvelope.guideWidth : guideWidth;
			const std::uint32_t stableGuideHeight = stableEnvelope ? resourceEnvelope.guideHeight : guideHeight;
			const std::uint32_t stableModelWidth = ScaleDimension(stableColorWidth, modelResolution);
			const std::uint32_t stableModelHeight = ScaleDimension(stableColorHeight, modelResolution);
			const std::uint32_t stableFeatureInputWidth = modelResolution == 100 ? stableColorWidth : stableModelWidth;
			const std::uint32_t stableFeatureInputHeight = modelResolution == 100 ? stableColorHeight : stableModelHeight;
			const std::uint32_t passCount = GetPassCount(tuning);
			const std::uint32_t tierIndex = ResolutionTierIndex(modelResolution);
			const auto resolveSettings = FrameResolveSettings(modelResolution, tuning.adaptiveResolution);
			SyncTemporalReuseConfig(tuning, modelResolution, passCount);
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				const auto& input = inputs[eyeIndex];
				if (!input.depth || !input.depthSRV || !input.motionVectors)
					return false;
				if (!EnsureResources(device, eyeIndex, color, input.depth, input.motionVectors,
						guideWidth, guideHeight, colorWidth, colorHeight, modelWidth, modelHeight, passCount, modelResolution, passCount > 1 ? tuning.secondPass.coveragePercent : 100u,
						tuning.adaptiveResolution, resourceEnvelope, tuning.adaptiveMemoryCeiling))
					return LatchFailure("shared resource creation", interop.LastError());

				D3D11_BOX sourceBox{
					input.sourceX, input.sourceY, 0,
					input.sourceX + colorWidth, input.sourceY + colorHeight, 1
				};
				auto& eye = eyes[eyeIndex];
				auto& tier = eye.tiers[tierIndex];
				eye.movingCrop = input.compensateCropMotion;
				eye.sceneColorMotionScale = input.sceneColorMotionScale;
				eye.modelSampling = FoveatedRenderImpl::CropGeometry::ModelSampling(colorWidth, colorHeight,
					modelWidth, modelHeight, modelResolution, input.sourceX, input.sourceY,
					tuning.singlePassLadder && input.compensateCropMotion);
				if (!tuning.adaptiveResolution || !tuning.adaptiveHandoff)
					eye.handoff.valid = false;
				context->CopySubresourceRegion(eye.color.resource11.Get(), 0, 0, 0, 0, color, 0, &sourceBox);
				if (tier.reducedResolution && !DispatchModelInput(device, context, eye, tier, colorWidth, colorHeight, modelWidth, modelHeight,
					 tuning.modelResolveMode == 1))
					return LatchFailure("model input downsample stereo", E_FAIL);
				auto guideInput = input;
				if (input.compensateCropMotion && !tuning.singlePassLadder) {
					bool reset = stereoAtlasActiveLastFrame ? stereoAtlasResetPending : resetPending[eyeIndex][tierIndex];
					ID3D11Resource* nrMotion = FoveatedRenderImpl::CropMotion::Prepare(2 + eyeIndex, input.motionVectors,
						{ input.sourceX, input.sourceY, colorWidth, colorHeight }, guideWidth, guideHeight,
						{ input.sceneColorMotionScale[0] > 0 ? input.sceneColorMotionScale[0] / colorWidth : input.motionVectorScaleX / guideWidth,
						  input.sceneColorMotionScale[1] > 0 ? input.sceneColorMotionScale[1] / colorHeight : input.motionVectorScaleY / guideHeight },
						globals::state->frameCount, reset);
					if (!nrMotion)
						return LatchFailure("crop motion preparation", E_FAIL);
					if (stereoAtlasActiveLastFrame) {
						// A true crop-history discontinuity must reset atlas Feature18, but the
						// deliberately armed dormant per-eye reset flag must not suppress
						// ordinary atlas crop-motion compensation.
						if (reset)
							stereoAtlasResetPending = true;
					} else {
						resetPending[eyeIndex][tierIndex] = reset;
					}
					guideInput.motionVectors = nrMotion;
				}
				if (!CopyStereoGuides(context, guideInput, eye, guideWidth, guideHeight))
					return LatchFailure("depth/motion guide copy", E_FAIL);
			}

			const auto adaptivePrewarm = PrepareAdjacentPrewarmResources(device, tierIndex,
				colorWidth, colorHeight, guideWidth, guideHeight, passCount, modelResolution,
				stableColorWidth, stableColorHeight, tuning);

			const bool temporalTierSupported = IsTemporalReuseSupported(tuning, eyes[0].tiers[tierIndex]) &&
				IsTemporalReuseSupported(tuning, eyes[1].tiers[tierIndex]);
			const bool fullEyeTemporalLayout = IsFullEyeTemporalLayout(colorDesc, inputs, colorWidth, colorHeight);
			const bool stableTemporalLayout = IsTemporalLayoutStable(colorDesc, inputs, colorWidth, colorHeight);
			bool temporalLayoutChanged = false;
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				const auto& temporal = eyes[eyeIndex].temporal;
				if (temporal.valid &&
					(temporal.regionX != inputs[eyeIndex].sourceX || temporal.regionY != inputs[eyeIndex].sourceY)) {
					temporalLayoutChanged = true;
					break;
				}
			}
			if (temporalLayoutChanged && IsTemporalReuseConfigured(tuning)) {
				// A moving crop changes the meaning of every local history sample. The
				// first frame at the new region must be a native anchor for both eyes.
				InvalidateTemporalHistory();
				resetPending[0][tierIndex] = true;
				resetPending[1][tierIndex] = true;
			}
			const bool cropTemporalLayout = stableTemporalLayout && !fullEyeTemporalLayout;
			// Eye-staggered N2: one native eye per frame keeps the Feature 18 cost flat
			// instead of alternating a two-eye frame with a two-eye skip frame.
			const bool staggerConfigured = tuning.temporalReuseStaggerEyes && tuning.temporalReuseCadence == 2 &&
				temporalTierSupported && stableTemporalLayout && !tuning.adaptiveResolution;
			if (staggerConfigured) {
				const std::uint32_t nativeEye = StaggeredNativeEye(temporalFrameIndex);
				const std::uint32_t reuseEye = nativeEye ^ 1u;
				const bool reuseReady = CanAttemptTemporalReuse(eyes[reuseEye], colorWidth, colorHeight,
						guideWidth, guideHeight, inputs[reuseEye].sourceX, inputs[reuseEye].sourceY) &&
					!resetPending[reuseEye][tierIndex] && !resetPending[nativeEye][tierIndex];
				if (reuseReady) {
					const auto staggered = ApplyStaggeredStereo(device, context, inputs, nativeEye, tierIndex,
						colorWidth, colorHeight, guideWidth, guideHeight, modelWidth, modelHeight,
						stableFeatureInputWidth, stableFeatureInputHeight, stableModelWidth, stableModelHeight,
						resolveSettings, tuning, writeback, destinationUAV, blendSubrect);
					if (staggered != StaggerResult::FallBack)
						return staggered == StaggerResult::Applied;
				}
			}
			const bool temporalCandidate = !staggerConfigured && temporalTierSupported && stableTemporalLayout &&
				CanAttemptTemporalReuse(eyes[0], colorWidth, colorHeight, guideWidth, guideHeight,
					inputs[0].sourceX, inputs[0].sourceY) &&
				CanAttemptTemporalReuse(eyes[1], colorWidth, colorHeight, guideWidth, guideHeight,
					inputs[1].sourceX, inputs[1].sourceY) &&
				!tuning.adaptiveResolution && !resetPending[0][tierIndex] && !resetPending[1][tierIndex] &&
				(temporalFrameIndex % tuning.temporalReuseCadence) != 0;
			if (temporalCandidate) {
				bool reused = true;
				for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
					const auto& input = inputs[eyeIndex];
					auto& eye = eyes[eyeIndex];
					auto& tier = eye.tiers[tierIndex];
					ID3D11UnorderedAccessView* temporalOutputUAV = tier.reducedResolution ?
						tier.resolvedUAV.Get() : tier.output.uav11.Get();
					if (!TryTemporalReuse(device, context, eye, temporalOutputUAV,
						colorWidth, colorHeight, guideWidth, guideHeight,
						input.motionVectorScaleX, input.motionVectorScaleY, tuning)) {
						reused = false;
						break;
					}
				}
				if (reused) {
					const D3D11_BOX outputBox{ 0, 0, 0, colorWidth, colorHeight, 1 };
					for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
						const auto& input = inputs[eyeIndex];
						auto& eye = eyes[eyeIndex];
						auto& tier = eye.tiers[tierIndex];
						ID3D11Resource* temporalOutput = tier.reducedResolution ?
							tier.resolved.Get() : tier.output.resource11.Get();
						ID3D11ShaderResourceView* temporalOutputSRV = tier.reducedResolution ?
							tier.resolvedSRV.Get() : tier.output.srv11.Get();
						ID3D11Resource* shapedOutput = ApplyResultShaping(device, context, eye, eyeIndex,
							temporalOutput, temporalOutputSRV, colorWidth, colorHeight, guideWidth, guideHeight,
							input.sourceX, input.sourceY, input.motionVectorScaleX, input.motionVectorScaleY, tuning);
						if (blendSubrect && destinationUAV) {
							FoveatedRenderImpl::Ops::BlendSubrectToOutput(shapedOutput,
								writeback, destinationUAV, input.sourceX, input.sourceY, colorWidth, colorHeight);
						} else {
							context->CopySubresourceRegion(writeback, 0, input.sourceX, input.sourceY, 0,
								shapedOutput, 0, &outputBox);
						}
						resetPending[eyeIndex][tierIndex] = false;
					}
					temporalSkippedSinceFull = true;
					AdvanceTemporalFrame(tuning);
					LogTemporalReuseActive(tuning.temporalReuseCadence, cropTemporalLayout);
#if defined(OPENNR_CAPTURE_ENABLED)
					if (globals::features::openNRCapture.settings.enableCapture) {
						OpenNRCaptureFeature::FrameInfo captureInfo;
						captureInfo.hostFrame = globals::state ? globals::state->frameCount : 0;
						captureInfo.colorWidth = colorWidth;
						captureInfo.colorHeight = colorHeight;
						captureInfo.modelWidth = modelWidth;
						captureInfo.modelHeight = modelHeight;
						captureInfo.modelResolutionPercent = modelResolution;
						captureInfo.guideWidth = guideWidth;
						captureInfo.guideHeight = guideHeight;
						captureInfo.passCount = passCount;
						for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
							captureInfo.motionVectorScaleX[eyeIndex] = inputs[eyeIndex].motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth;
							captureInfo.motionVectorScaleY[eyeIndex] = inputs[eyeIndex].motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight;
							captureInfo.historyReset[eyeIndex] = false;
						}
						captureInfo.temporalReuse = true;
						captureInfo.temporalFrameIndex = temporalFrameIndex;
						captureInfo.temporalSkippedSinceFull = temporalSkippedSinceFull;
						captureInfo.temporalNextAnchorReset = tuning.temporalReuseResetAfterSkip;
						captureInfo.intensity = tuning.intensity;
						captureInfo.localToneStrength = tuning.localToneStrength;
						captureInfo.localStructureStrength = tuning.localStructureStrength;
						captureInfo.skinStructureStrength = tuning.skinStructureStrength;
						captureInfo.style = tuning.style;
						captureInfo.useAutoMask = tuning.useAutoMask;
						captureInfo.uiCorrection = tuning.uiCorrection;
						captureInfo.route = cropTemporalLayout ?
							"feature18_crop_temporal_reuse" : "feature18_stereo_temporal_reuse";
						const bool captureFrame = globals::features::openNRCapture.BeginFrame(captureInfo);
						if (captureFrame) {
							logger::info("[DLSSNR][TemporalDiag] mode=reuse route={} hostFrame={} cadence=N{} temporalFrameIndex={} skippedSinceFull={} nextAnchorReset={}",
								captureInfo.route, captureInfo.hostFrame, tuning.temporalReuseCadence, captureInfo.temporalFrameIndex,
								captureInfo.temporalSkippedSinceFull, captureInfo.temporalNextAnchorReset);
							const bool writeColorPreview = globals::features::openNRCapture.settings.writeColorPreviews;
							for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
								auto& eye = eyes[eyeIndex];
								auto& tier = eye.tiers[tierIndex];
								ID3D11Resource* temporalOutput = tier.reducedResolution ? tier.resolved.Get() : tier.output.resource11.Get();
								if (globals::features::openNRCapture.settings.capturePreNR) {
									ID3D11Resource* modelInput = tier.reducedResolution ? tier.modelInput.resource11.Get() : eye.color.resource11.Get();
									const auto modelInputWidth = tier.reducedResolution ? modelWidth : colorWidth;
									const auto modelInputHeight = tier.reducedResolution ? modelHeight : colorHeight;
									globals::features::openNRCapture.CaptureTexture(modelInput, 0, 0,
										modelInputWidth, modelInputHeight, "input", eyeIndex, false, writeColorPreview);
									if (globals::features::openNRCapture.IsFullFrameValidationFrame())
										globals::features::openNRCapture.CaptureTexture(modelInput, 0, 0,
											modelInputWidth, modelInputHeight, "input", eyeIndex, true);
								}
								if (globals::features::openNRCapture.settings.captureDepth) {
									globals::features::openNRCapture.CaptureTexture(eye.depth.resource11.Get(), 0, 0,
										guideWidth, guideHeight, "depth", eyeIndex, false, false);
									if (globals::features::openNRCapture.IsFullFrameValidationFrame())
										globals::features::openNRCapture.CaptureTexture(eye.depth.resource11.Get(), 0, 0,
											guideWidth, guideHeight, "depth", eyeIndex, true, false);
								}
								if (globals::features::openNRCapture.settings.captureMotionVectors) {
									globals::features::openNRCapture.CaptureTexture(eye.motionVectors.resource11.Get(), 0, 0,
										guideWidth, guideHeight, "motion_vectors", eyeIndex, false, false);
									if (globals::features::openNRCapture.IsFullFrameValidationFrame())
										globals::features::openNRCapture.CaptureTexture(eye.motionVectors.resource11.Get(), 0, 0,
											guideWidth, guideHeight, "motion_vectors", eyeIndex, true, false);
								}
								if (globals::features::openNRCapture.settings.capturePostNR) {
									globals::features::openNRCapture.CaptureTexture(temporalOutput, 0, 0,
										colorWidth, colorHeight, "temporal_output", eyeIndex, false, writeColorPreview);
									if (globals::features::openNRCapture.IsFullFrameValidationFrame())
										globals::features::openNRCapture.CaptureTexture(temporalOutput, 0, 0,
											colorWidth, colorHeight, "temporal_output", eyeIndex, true);
								}
							}
							globals::features::openNRCapture.EndFrame();
						}
					}
#endif
					return true;
				}
			}

#if defined(OPENNR_CAPTURE_ENABLED)
			bool captureFrame = false;
			if (globals::features::openNRCapture.settings.enableCapture) {
				OpenNRCaptureFeature::FrameInfo captureInfo;
				captureInfo.hostFrame = globals::state ? globals::state->frameCount : 0;
				captureInfo.colorWidth = colorWidth;
				captureInfo.colorHeight = colorHeight;
				captureInfo.modelWidth = modelWidth;
				captureInfo.modelHeight = modelHeight;
				captureInfo.modelResolutionPercent = modelResolution;
				captureInfo.guideWidth = guideWidth;
				captureInfo.guideHeight = guideHeight;
				captureInfo.passCount = passCount;
				for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
					captureInfo.motionVectorScaleX[eyeIndex] = inputs[eyeIndex].motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth;
					captureInfo.motionVectorScaleY[eyeIndex] = inputs[eyeIndex].motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight;
					captureInfo.historyReset[eyeIndex] = resetPending[eyeIndex][tierIndex] ||
						(temporalSkippedSinceFull && tuning.temporalReuseResetAfterSkip);
				}
				captureInfo.intensity = tuning.intensity;
				captureInfo.localToneStrength = tuning.localToneStrength;
				captureInfo.localStructureStrength = tuning.localStructureStrength;
				captureInfo.skinStructureStrength = tuning.skinStructureStrength;
				captureInfo.style = tuning.style;
				captureInfo.useAutoMask = tuning.useAutoMask;
				captureInfo.uiCorrection = tuning.uiCorrection;
				captureInfo.route = cropTemporalLayout ? "feature18_crop" : "feature18_stereo";
				#if defined(OPENNR_CAPTURE_ENABLED)
				for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex)
					AppendRendererConditioningAvailability(captureInfo, inputs[eyeIndex].sourceX, inputs[eyeIndex].sourceY,
						colorWidth, colorHeight, color);
				#endif
				captureFrame = globals::features::openNRCapture.BeginFrame(captureInfo);
			}
			if (captureFrame && globals::features::openNRCapture.settings.capturePreNR) {
				const bool writeColorPreview = globals::features::openNRCapture.settings.writeColorPreviews;
				for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
					auto& eye = eyes[eyeIndex];
					auto& tier = eye.tiers[tierIndex];
					ID3D11Resource* modelInput = tier.reducedResolution ? tier.modelInput.resource11.Get() : eye.color.resource11.Get();
					const auto modelInputWidth = tier.reducedResolution ? modelWidth : colorWidth;
					const auto modelInputHeight = tier.reducedResolution ? modelHeight : colorHeight;
					globals::features::openNRCapture.CaptureTexture(modelInput, 0, 0,
						modelInputWidth, modelInputHeight, "input", eyeIndex, false, writeColorPreview);
					if (tier.reducedResolution)
						globals::features::openNRCapture.CaptureTexture(eye.color.resource11.Get(), 0, 0,
							colorWidth, colorHeight, "input_source", eyeIndex, false, writeColorPreview);
					if (globals::features::openNRCapture.IsFullFrameValidationFrame())
						globals::features::openNRCapture.CaptureTexture(modelInput, 0, 0,
							modelInputWidth, modelInputHeight, "input", eyeIndex, true);
					if (tier.reducedResolution && globals::features::openNRCapture.IsFullFrameValidationFrame())
						globals::features::openNRCapture.CaptureTexture(eye.color.resource11.Get(), 0, 0,
							colorWidth, colorHeight, "input_source", eyeIndex, true);
				}
			}
			if (captureFrame && globals::features::openNRCapture.settings.captureDepth) {
				for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
					auto& eye = eyes[eyeIndex];
					globals::features::openNRCapture.CaptureTexture(eye.depth.resource11.Get(), 0, 0,
						guideWidth, guideHeight, "depth", eyeIndex, false, false);
					if (globals::features::openNRCapture.IsFullFrameValidationFrame())
						globals::features::openNRCapture.CaptureTexture(eye.depth.resource11.Get(), 0, 0,
							guideWidth, guideHeight, "depth", eyeIndex, true, false);
				}
			}
			if (captureFrame && globals::features::openNRCapture.settings.captureMotionVectors) {
				for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
					auto& eye = eyes[eyeIndex];
					globals::features::openNRCapture.CaptureTexture(eye.motionVectors.resource11.Get(), 0, 0,
						guideWidth, guideHeight, "motion_vectors", eyeIndex, false, false);
					if (globals::features::openNRCapture.IsFullFrameValidationFrame())
						globals::features::openNRCapture.CaptureTexture(eye.motionVectors.resource11.Get(), 0, 0,
							guideWidth, guideHeight, "motion_vectors", eyeIndex, true, false);
				}
			}
			#if defined(OPENNR_CAPTURE_ENABLED)
			if (captureFrame && globals::features::openNRCapture.settings.captureRendererConditionings) {
				for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex)
					CaptureRendererConditionings(globals::features::openNRCapture, inputs[eyeIndex].sourceX,
						inputs[eyeIndex].sourceY, colorWidth, colorHeight, eyeIndex, color);
			}
			#endif
#endif

			bool nativeEvaluationDone = false;
			const auto atlasResult = ApplyStereoAtlasNative(device, context, inputs, tierIndex,
				colorWidth, colorHeight, guideWidth, guideHeight, modelWidth, modelHeight,
				modelResolution, passCount, tuning);
			if (atlasResult == StereoAtlasResult::Failed || (tuning.stereoAtlas && atlasResult != StereoAtlasResult::Applied)) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("stereo atlas", E_FAIL);
			}
			nativeEvaluationDone = atlasResult == StereoAtlasResult::Applied;

			if (!nativeEvaluationDone) {
			ID3D12GraphicsCommandList* commandList = nullptr;
			if (!interop.BeginD3D12(&commandList)) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("BeginD3D12 stereo", interop.LastError());
			}
			ExecuteAdaptivePrewarm(commandList, adaptivePrewarm, stableGuideWidth, stableGuideHeight,
				stableColorWidth, stableColorHeight);

			bool succeeded = true;
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				auto& eye = eyes[eyeIndex];
				auto& tier = eye.tiers[tierIndex];
				const auto& input = inputs[eyeIndex];
				const bool eyeSucceeded = ExecuteCascade(commandList, eyeIndex, tierIndex,
					tier.reducedResolution ? tier.modelInput.resource12.Get() : eye.color.resource12.Get(),
					eye.depth.resource12.Get(), eye.motionVectors.resource12.Get(),
					std::array<ID3D12Resource*, kCascadePassCount - 1>{
						tier.cascadeIntermediates[0].resource12.Get(), tier.cascadeIntermediates[1].resource12.Get() },
					tier.secondPassOutput.resource12.Get(), tier.output.resource12.Get(),
					tier.reducedResolution ? modelWidth : colorWidth,
					tier.reducedResolution ? modelHeight : colorHeight,
					guideWidth, guideHeight, modelWidth, modelHeight,
					stableFeatureInputWidth, stableFeatureInputHeight,
					stableModelWidth, stableModelHeight,
					input.motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth,
					input.motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight,
						tuning, passCount, resetPending[eyeIndex][tierIndex] ||
						(temporalSkippedSinceFull && tuning.temporalReuseResetAfterSkip));
				if (!eyeSucceeded) {
					succeeded = false;
					break;
				}
			}

			if (!interop.EndD3D12()) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("EndD3D12 stereo", interop.LastError());
			}
			if (!succeeded) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("Feature 18 stereo", static_cast<HRESULT>(Runtime::Instance().NgxResult()));
			}
			}

			D3D11_BOX outputBox{ 0, 0, 0, colorWidth, colorHeight, 1 };
			std::array<ID3D11Resource*, 2> preparedWriteback{};
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				const auto& input = inputs[eyeIndex];
				auto& eye = eyes[eyeIndex];
				auto& tier = eye.tiers[tierIndex];
				if (!nativeEvaluationDone && passCount == 2 && tuning.secondPass.coveragePercent < 100) {
					const auto pass2Coverage = std::clamp(tuning.secondPass.coveragePercent, 50u, 100u);
					const auto pass2Width = ScaleDimension(modelWidth, pass2Coverage);
					const auto pass2Height = ScaleDimension(modelHeight, pass2Coverage);
					if (!CompositeSequentialPass(device, context, tier, modelWidth, modelHeight,
						pass2Width, pass2Height, tuning))
						return LatchFailure("second-pass stereo composite", E_FAIL);
				}
				if (tier.reducedResolution && !DispatchModelResolve(device, context, eye, tier, colorWidth, colorHeight, resolveSettings,
						tuning.modelResolveMode == 1)) {
#if defined(OPENNR_CAPTURE_ENABLED)
					if (captureFrame)
						globals::features::openNRCapture.AbortFrame();
#endif
					return LatchFailure("model output resolve stereo", E_FAIL);
				}
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame && globals::features::openNRCapture.settings.capturePostNR) {
					const bool writeColorPreview = globals::features::openNRCapture.settings.writeColorPreviews;
					ID3D11Resource* teacher = tier.reducedResolution ? tier.resolved.Get() : tier.output.resource11.Get();
					globals::features::openNRCapture.CaptureTexture(teacher, 0, 0, colorWidth, colorHeight, "teacher", eyeIndex,
						false, writeColorPreview);
					if (tier.reducedResolution && globals::features::openNRCapture.settings.captureRawTeacher)
						globals::features::openNRCapture.CaptureTexture(tier.output.resource11.Get(), 0, 0,
							modelWidth, modelHeight, "teacher_raw", eyeIndex, false, writeColorPreview);
					if (globals::features::openNRCapture.IsFullFrameValidationFrame())
						globals::features::openNRCapture.CaptureTexture(teacher, 0, 0, colorWidth, colorHeight,
							"teacher", eyeIndex, true);
				}
#endif
				ID3D11Resource* neuralOutput = tier.reducedResolution ? tier.resolved.Get() : tier.output.resource11.Get();
				ID3D11ShaderResourceView* neuralOutputSRV = tier.reducedResolution ? tier.resolvedSRV.Get() : tier.output.srv11.Get();
				ID3D11Resource* shapedOutput = ApplyResultShaping(device, context, eye, eyeIndex,
					neuralOutput, neuralOutputSRV, colorWidth, colorHeight, guideWidth, guideHeight,
					input.sourceX, input.sourceY, input.motionVectorScaleX, input.motionVectorScaleY, tuning);
				if (failureLatched) return false;
				ID3D11ShaderResourceView* shapedOutputSRV = shapedOutput == neuralOutput ?
					neuralOutputSRV : eye.resultShaping.output.srv.Get();
				ID3D11Resource* writebackOutput = shapedOutput;
				if (tuning.adaptiveResolution && tuning.adaptiveHandoff)
					writebackOutput = ApplyAdaptiveHandoff(device, context, eyeIndex, eye, shapedOutput, shapedOutputSRV,
						colorWidth, colorHeight, guideWidth, guideHeight,
						input.motionVectorScaleX, input.motionVectorScaleY,
						input.sourceX, input.sourceY, tuning);
				preparedWriteback[eyeIndex] = writebackOutput;
			}
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				const auto& input = inputs[eyeIndex];
				ID3D11Resource* writebackOutput = preparedWriteback[eyeIndex];
				if (blendSubrect && destinationUAV) {
					// Keep the original background in `writeback` and composite the NR
					// crop over it with the same edge treatment as standard foveated DLSS.
					if (!FoveatedRenderImpl::Ops::BlendSubrectToOutput(writebackOutput, writeback, destinationUAV,
						input.sourceX, input.sourceY, colorWidth, colorHeight))
						return LatchFailure("stereo crop writeback", E_FAIL);
				} else {
					context->CopySubresourceRegion(writeback, 0, input.sourceX, input.sourceY, 0,
						writebackOutput, 0, &outputBox);
				}
				resetPending[eyeIndex][tierIndex] = nativeEvaluationDone;
			}
			if (temporalTierSupported) {
				bool recorded = true;
				for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
					auto& eye = eyes[eyeIndex];
					auto& tier = eye.tiers[tierIndex];
					ID3D11ShaderResourceView* teacherSRV = tier.reducedResolution ?
						tier.resolvedSRV.Get() : tier.output.srv11.Get();
					recorded = RecordTemporalHistory(device, context, eye, teacherSRV,
						colorWidth, colorHeight, guideWidth, guideHeight,
						inputs[eyeIndex].sourceX, inputs[eyeIndex].sourceY) && recorded;
				}
				if (!recorded)
					InvalidateTemporalHistory();
			}
			temporalSkippedSinceFull = false;
			staggerSkippedLastFrame = {};
			AdvanceTemporalFrame(tuning);
#if defined(OPENNR_CAPTURE_ENABLED)
			if (captureFrame)
				globals::features::openNRCapture.EndFrame();
#endif
			return true;
		}

		enum class StaggerResult
		{
			Applied,
			Failed,
			FallBack,
		};

		// One native Feature 18 eye plus one residual-reuse eye. Returns FallBack when
		// the reuse eye cannot be reprojected so the caller runs a full stereo frame.
		StaggerResult ApplyStaggeredStereo(ID3D11Device* device, ID3D11DeviceContext* context,
			const std::array<StereoEyeInput, 2>& inputs, std::uint32_t nativeEye, std::uint32_t tierIndex,
			std::uint32_t colorWidth, std::uint32_t colorHeight, std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t modelWidth, std::uint32_t modelHeight,
			std::uint32_t stableFeatureInputWidth, std::uint32_t stableFeatureInputHeight,
			std::uint32_t stableModelWidth, std::uint32_t stableModelHeight,
			const ModelResolveSettings& resolveSettings, const Tuning& tuning,
			ID3D11Resource* writeback, ID3D11UnorderedAccessView* destinationUAV, bool blendSubrect)
		{
			const std::uint32_t reuseEye = nativeEye ^ 1u;
			{
				auto& eye = eyes[reuseEye];
				auto& tier = eye.tiers[tierIndex];
				ID3D11UnorderedAccessView* reuseUAV = tier.reducedResolution ? tier.resolvedUAV.Get() : tier.output.uav11.Get();
				if (!TryTemporalReuse(device, context, eye, reuseUAV, colorWidth, colorHeight, guideWidth, guideHeight,
						inputs[reuseEye].motionVectorScaleX, inputs[reuseEye].motionVectorScaleY, tuning))
					return StaggerResult::FallBack;
			}

			ID3D12GraphicsCommandList* commandList = nullptr;
			if (!interop.BeginD3D12(&commandList)) {
				LatchFailure("BeginD3D12 staggered", interop.LastError());
				return StaggerResult::Failed;
			}
			{
				auto& eye = eyes[nativeEye];
				auto& tier = eye.tiers[tierIndex];
				const auto& input = inputs[nativeEye];
				const bool reset = resetPending[nativeEye][tierIndex] ||
					(tuning.temporalReuseResetAfterSkip && staggerSkippedLastFrame[nativeEye]);
				const bool succeeded = ExecuteCascade(commandList, nativeEye, tierIndex,
					tier.reducedResolution ? tier.modelInput.resource12.Get() : eye.color.resource12.Get(),
					eye.depth.resource12.Get(), eye.motionVectors.resource12.Get(),
					std::array<ID3D12Resource*, kCascadePassCount - 1>{
						tier.cascadeIntermediates[0].resource12.Get(), tier.cascadeIntermediates[1].resource12.Get() },
					tier.secondPassOutput.resource12.Get(), tier.output.resource12.Get(),
					tier.reducedResolution ? modelWidth : colorWidth,
					tier.reducedResolution ? modelHeight : colorHeight,
					guideWidth, guideHeight, modelWidth, modelHeight,
					stableFeatureInputWidth, stableFeatureInputHeight, stableModelWidth, stableModelHeight,
					input.motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth,
					input.motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight,
					tuning, 1, reset);
				if (!interop.EndD3D12()) {
					LatchFailure("EndD3D12 staggered", interop.LastError());
					return StaggerResult::Failed;
				}
				if (!succeeded) {
					LatchFailure("Feature 18 staggered", static_cast<HRESULT>(Runtime::Instance().NgxResult()));
					return StaggerResult::Failed;
				}
				if (tier.reducedResolution && !DispatchModelResolve(device, context, eye, tier, colorWidth, colorHeight,
						resolveSettings, tuning.modelResolveMode == 1)) {
					LatchFailure("model output resolve staggered", E_FAIL);
					return StaggerResult::Failed;
				}
			}

			const D3D11_BOX outputBox{ 0, 0, 0, colorWidth, colorHeight, 1 };
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				auto& eye = eyes[eyeIndex];
				auto& tier = eye.tiers[tierIndex];
				const auto& input = inputs[eyeIndex];
				ID3D11Resource* output = tier.reducedResolution ? tier.resolved.Get() : tier.output.resource11.Get();
				ID3D11ShaderResourceView* outputSRV = tier.reducedResolution ? tier.resolvedSRV.Get() : tier.output.srv11.Get();
				ID3D11Resource* shaped = ApplyResultShaping(device, context, eye, eyeIndex, output, outputSRV,
					colorWidth, colorHeight, guideWidth, guideHeight, input.sourceX, input.sourceY,
					input.motionVectorScaleX, input.motionVectorScaleY, tuning);
				if (blendSubrect && destinationUAV)
					FoveatedRenderImpl::Ops::BlendSubrectToOutput(shaped, writeback, destinationUAV,
						input.sourceX, input.sourceY, colorWidth, colorHeight);
				else
					context->CopySubresourceRegion(writeback, 0, input.sourceX, input.sourceY, 0, shaped, 0, &outputBox);
			}

			{
				auto& eye = eyes[nativeEye];
				auto& tier = eye.tiers[tierIndex];
				ID3D11ShaderResourceView* teacherSRV = tier.reducedResolution ? tier.resolvedSRV.Get() : tier.output.srv11.Get();
				if (!RecordTemporalHistory(device, context, eye, teacherSRV, colorWidth, colorHeight,
						guideWidth, guideHeight, inputs[nativeEye].sourceX, inputs[nativeEye].sourceY))
					InvalidateTemporalHistory();
			}
			resetPending[0][tierIndex] = false;
			resetPending[1][tierIndex] = false;
			staggerSkippedLastFrame[nativeEye] = false;
			staggerSkippedLastFrame[reuseEye] = true;
			temporalSkippedSinceFull = true;
			AdvanceTemporalFrame(tuning);
			if (!temporalReuseStaggerLogged) {
				logger::info("[DLSSNR] experimental eye-staggered temporal reuse active (one native eye per frame)");
				temporalReuseStaggerLogged = true;
			}
			return StaggerResult::Applied;
		}



		bool Reset(bool manual = true)
		{
			if (!interop.WaitForIdle()) {
				failureLatched = true;
				recoverableFailure = false;
				logger::error("[DLSSNR] Reset deferred: GPU work has not completed; resources retained");
				return false;
			}
			if (manual)
				recoveryAttempted = false;
			resolveInitialized = false;
			resolveFrame = UINT32_MAX;
			Runtime::Instance().Shutdown();
			interop.Shutdown();
			eyes = {};
			for (auto& eyeReset : resetPending)
				eyeReset.fill(true);
			ResetAdaptivePrewarmState();
			failureLatched = false;
			failureOperation.clear();
			copyDepthGuideCS.Reset();
			alignGuidesCS.Reset();
			alignGuidesCB.Reset();
			modelResolutionCS.Reset();
			temporalSnapshotCS.Reset();
			temporalAccumulateCS.Reset();
			temporalReprojectCS.Reset();
			adaptiveHandoffCS.Reset();
			resultShapingCS.Reset();
			sequentialCompositeCS.Reset();
			stereoAtlasColorPackCS.Reset();
			stereoAtlasDepthPackCS.Reset();
			stereoAtlasMotionPackCS.Reset();
			ladderAtlasGuidesCS.Reset();
			ladderAtlasGeometry.valid = false;
			sequentialCompositeCB.Reset();
			stereoAtlasPackCB.Reset();
			ladderAtlasCB.Reset();
			stereoAtlas = {};
			stereoAtlasResetPending = true;
			stereoAtlasActiveLastFrame = false;
			stereoAtlasActiveLogged = false;
			stereoAtlasFallbackLogged = false;
			modelResolutionCB.Reset();
			modelResolutionSampler.Reset();
			temporalReuseCB.Reset();
			temporalReuseSampler.Reset();
			resultShapingCB.Reset();
			resultShapingSampler.Reset();
			temporalConfigInitialized = false;
			resultShapingConfigInitialized = false;
			temporalFrameIndex = 0;
			temporalSkippedSinceFull = false;
			staggerSkippedLastFrame = {};
			temporalReuseStaggerLogged = false;
			temporalReuseActiveLogged = false;
			temporalReuseCropActiveLogged = false;
			temporalReuseWarningLogged = false;
			resultShapingFailureLogged = false;
			resultStabilizationFailureLogged = false;
			return true;
		}

		void ResetHistory()
		{
			stereoAtlasResetPending = true;
			for (auto& eyeReset : resetPending)
				eyeReset.fill(true);
			for (auto& eye : eyes)
				eye.resultShaping.historyAllocationFailed = false;
			resultStabilizationFailureLogged = false;
			InvalidateTemporalHistory();
		}

		void ClearShaderCache()
		{
			copyDepthGuideCS.Reset();
			alignGuidesCS.Reset();
			alignGuidesCB.Reset();
			modelResolutionCS.Reset();
			temporalSnapshotCS.Reset();
			temporalAccumulateCS.Reset();
			temporalReprojectCS.Reset();
			adaptiveHandoffCS.Reset();
			resultShapingCS.Reset();
			sequentialCompositeCS.Reset();
			stereoAtlasColorPackCS.Reset();
			stereoAtlasDepthPackCS.Reset();
			stereoAtlasMotionPackCS.Reset();
			ladderAtlasGuidesCS.Reset();
			ladderAtlasGeometry.valid = false;
			for (auto& eye : eyes)
				eye.resultShaping.valid = false;
		}

		[[nodiscard]] const char* StatusText() const { return failureLatched ? failureOperation.c_str() : ToString(Runtime::Instance().Status()); }
		[[nodiscard]] bool IsStereoAtlasActive() const { return stereoAtlasActiveLastFrame && !failureLatched; }
		[[nodiscard]] bool IsOutputTransitioning() const
		{
			return std::any_of(eyes.begin(), eyes.end(), [](const auto& eye) { return eye.resultShaping.transitionRemainingMs > 0.0f; });
		}
		[[nodiscard]] bool IsFailureLatched() const { return failureLatched; }
		[[nodiscard]] bool IsFailureRecoverable() const { return failureLatched && recoverableFailure; }
		[[nodiscard]] bool IsRecoveryLimited() const { return recoveryAttempted; }

		[[nodiscard]] bool IsAdaptiveTierReady(std::uint32_t modelResolution) const
		{
			if (recoveryAttempted)
				return false;

			const auto normalizedResolution = NormalizeModelResolution(modelResolution);
			const auto tierIndex = ResolutionTierIndex(normalizedResolution);
			for (std::uint32_t eyeIndex = 0; eyeIndex < eyes.size(); ++eyeIndex) {
				const auto& eye = eyes[eyeIndex];
				const auto& tier = eye.tiers[tierIndex];
				if (!eye.sharedResourcesValid || tier.modelResolution != normalizedResolution ||
					tier.passCount != 1 || tier.reducedResolution != (normalizedResolution != 100) ||
					!tier.output.resource11 || !Runtime::Instance().HasFeature(FeatureSlot(eyeIndex, tierIndex, 0)))
					return false;
			}
			return true;
		}

		void RecoverIfReady(ID3D11Device* device)
		{
			if (!failureLatched || recoveryAttempted || !recoverableFailure || !device ||
				std::chrono::steady_clock::now() - failureTime < std::chrono::seconds(2))
				return;
			recoveryAttempted = true;
			if (FAILED(device->GetDeviceRemovedReason()) || !interop.WaitForIdle()) {
				logger::error("[DLSSNR] Recovery stopped: device or GPU fence is unhealthy");
				return;
			}
			logger::warn("[DLSSNR] Retrying NR once after cooldown; adaptive upshifts held until manual Reset");
			Reset(false);
		}

	private:
		bool IsTemporalReuseConfigured(const Tuning& tuning) const
		{
			return tuning.temporalReuseCadence >= kTemporalReuseMinCadence &&
				tuning.temporalReuseCadence <= kTemporalReuseMaxCadence;
		}

		bool IsTemporalReuseSupported(const Tuning& tuning, const TierResources& tier) const
		{
			if (!IsTemporalReuseConfigured(tuning) || tier.passCount != 1)
				return false;
			// A reduced tier has no native full-resolution output to snapshot. Its
			// temporal history is therefore valid only after the matched-residual
			// resolve has produced a full-eye image in tier.resolved.
			return !tier.reducedResolution || tuning.modelResolveMode == 1;
		}

		void SyncTemporalReuseConfig(const Tuning& tuning, std::uint32_t modelResolution, std::uint32_t passCount)
		{
			const TemporalHistoryConfig next{ tuning.adaptiveResolution, tuning.singlePassLadder ? 100u : modelResolution, tuning.temporalReuseCadence,
				tuning.temporalReuseDepthThreshold, tuning.temporalReuseColorTolerance, passCount };
			if (temporalConfigInitialized && temporalConfig == next)
				return;
			const bool preserveHandoff = temporalConfigInitialized && temporalConfig.PreservesHandoff(next);
			temporalConfigInitialized = true;
			temporalConfig = next;
			InvalidateTemporalHistory(preserveHandoff);
		}

		bool CanAttemptTemporalReuse(const EyeResources& eye,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t regionX, std::uint32_t regionY) const
		{
			return eye.temporal.valid &&
				eye.temporal.width == colorWidth && eye.temporal.height == colorHeight &&
				eye.temporal.guideWidth == guideWidth && eye.temporal.guideHeight == guideHeight &&
				eye.temporal.regionX == regionX && eye.temporal.regionY == regionY &&
				eye.temporal.base.resource && eye.temporal.base.srv && eye.temporal.base.uav &&
				eye.temporal.residual.resource && eye.temporal.residual.srv && eye.temporal.residual.uav &&
				eye.temporal.depth.resource && eye.temporal.depth.srv &&
				eye.temporal.accumulatedMotion[0].resource && eye.temporal.accumulatedMotion[0].srv &&
				eye.temporal.accumulatedMotion[0].uav &&
				eye.temporal.accumulatedMotion[1].resource && eye.temporal.accumulatedMotion[1].srv &&
				eye.temporal.accumulatedMotion[1].uav;
		}

		bool IsFullEyeTemporalLayout(const D3D11_TEXTURE2D_DESC& colorDesc,
			const std::array<StereoEyeInput, 2>& inputs,
			std::uint32_t colorWidth, std::uint32_t colorHeight) const
		{
			if (!colorWidth || !colorHeight || colorDesc.Width != colorWidth * 2 || colorDesc.Height != colorHeight)
				return false;
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				if (inputs[eyeIndex].sourceX != eyeIndex * colorWidth || inputs[eyeIndex].sourceY != 0)
					return false;
			}
			return true;
		}

		bool IsTemporalLayoutStable(const D3D11_TEXTURE2D_DESC& colorDesc,
			const std::array<StereoEyeInput, 2>& inputs,
			std::uint32_t colorWidth, std::uint32_t colorHeight) const
		{
			if (!colorWidth || !colorHeight || colorDesc.Width == 0 || colorDesc.Height == 0 ||
				(colorDesc.Width % 2) != 0)
				return false;
			const std::uint32_t eyeWidth = colorDesc.Width / 2;
			if (colorWidth > eyeWidth || colorHeight > colorDesc.Height)
				return false;
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				const auto& input = inputs[eyeIndex];
				const std::uint64_t eyeStart = static_cast<std::uint64_t>(eyeIndex) * eyeWidth;
				const std::uint64_t eyeEnd = eyeStart + eyeWidth;
				const std::uint64_t sourceEndX = static_cast<std::uint64_t>(input.sourceX) + colorWidth;
				const std::uint64_t sourceEndY = static_cast<std::uint64_t>(input.sourceY) + colorHeight;
				if (input.sourceX < eyeStart || sourceEndX > eyeEnd || sourceEndY > colorDesc.Height)
					return false;
			}
			return true;
		}

		bool EnsureTemporalTexture(ID3D11Device* device, std::uint32_t width, std::uint32_t height,
			DXGI_FORMAT format, TemporalTexture& texture, const char* name)
		{
			if (!device || !width || !height || !name)
				return false;

			D3D11_TEXTURE2D_DESC desc{};
			desc.Width = width;
			desc.Height = height;
			desc.MipLevels = 1;
			desc.ArraySize = 1;
			desc.Format = format;
			desc.SampleDesc.Count = 1;
			desc.Usage = D3D11_USAGE_DEFAULT;
			desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
			if (FAILED(device->CreateTexture2D(&desc, nullptr, texture.resource.GetAddressOf())))
				return false;

			D3D11_SHADER_RESOURCE_VIEW_DESC srvDesc{};
			srvDesc.Format = format;
			srvDesc.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
			srvDesc.Texture2D.MostDetailedMip = 0;
			srvDesc.Texture2D.MipLevels = 1;
			if (FAILED(device->CreateShaderResourceView(texture.resource.Get(), &srvDesc, texture.srv.GetAddressOf())))
				return false;

			D3D11_UNORDERED_ACCESS_VIEW_DESC uavDesc{};
			uavDesc.Format = format;
			uavDesc.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
			uavDesc.Texture2D.MipSlice = 0;
			if (FAILED(device->CreateUnorderedAccessView(texture.resource.Get(), &uavDesc, texture.uav.GetAddressOf())))
				return false;

			Util::SetResourceName(texture.resource.Get(), name);
			return true;
		}

		bool EnsureTemporalEyeResources(ID3D11Device* device, EyeResources& eye,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight)
		{
			if (!device || !colorWidth || !colorHeight || !guideWidth || !guideHeight)
				return false;
			if (eye.temporal.width == colorWidth && eye.temporal.height == colorHeight &&
				eye.temporal.guideWidth == guideWidth && eye.temporal.guideHeight == guideHeight &&
				eye.temporal.base.resource && eye.temporal.residual.resource &&
				eye.temporal.depth.resource && eye.temporal.accumulatedMotion[0].resource &&
				eye.temporal.accumulatedMotion[1].resource)
				return true;

			eye.temporal = {};
			eye.temporal.width = colorWidth;
			eye.temporal.height = colorHeight;
			eye.temporal.guideWidth = guideWidth;
			eye.temporal.guideHeight = guideHeight;
			return EnsureTemporalTexture(device, colorWidth, colorHeight, DXGI_FORMAT_R16G16B16A16_FLOAT,
				eye.temporal.base, "NeuralRendering::TemporalBase") &&
			EnsureTemporalTexture(device, colorWidth, colorHeight, DXGI_FORMAT_R16G16B16A16_FLOAT,
				eye.temporal.residual, "NeuralRendering::TemporalResidual") &&
			EnsureTemporalTexture(device, guideWidth, guideHeight, DXGI_FORMAT_R32_FLOAT,
				eye.temporal.depth, "NeuralRendering::TemporalDepth") &&
			EnsureTemporalTexture(device, colorWidth, colorHeight, DXGI_FORMAT_R16G16_FLOAT,
				eye.temporal.accumulatedMotion[0], "NeuralRendering::TemporalAccumulatedMotion0") &&
			EnsureTemporalTexture(device, colorWidth, colorHeight, DXGI_FORMAT_R16G16_FLOAT,
				eye.temporal.accumulatedMotion[1], "NeuralRendering::TemporalAccumulatedMotion1");
		}

		bool EnsureResultShapingTexture(ID3D11Device* device, std::uint32_t width, std::uint32_t height,
			DXGI_FORMAT format, TemporalTexture& texture, const char* name)
		{
			if (!EnsureTemporalTexture(device, width, height, format, texture, name))
				return false;
			Util::SetResourceName(texture.srv.Get(), (std::string(name) + " SRV").c_str());
			Util::SetResourceName(texture.uav.Get(), (std::string(name) + " UAV").c_str());
			return true;
		}

		bool EnsureResultShapingResources(ID3D11Device* device, EyeResources& eye,
			std::uint32_t eyeIndex, std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t regionX, std::uint32_t regionY, std::uint32_t modelResolution,
			bool needHistory, bool preserveCropMotion, bool stableHistory)
		{
			if (!device || !colorWidth || !colorHeight || !guideWidth || !guideHeight)
				return false;

			const auto resourceWidth = stableHistory ? eye.color.desc.Width : colorWidth;
			const auto resourceHeight = stableHistory ? eye.color.desc.Height : colorHeight;
			const auto resourceGuideWidth = stableHistory ? eye.depth.desc.Width : guideWidth;
			const auto resourceGuideHeight = stableHistory ? eye.depth.desc.Height : guideHeight;
			const DXGI_FORMAT colorFormat = eye.color.desc.Format;
			auto& state = eye.resultShaping;
			const bool outputMatches = state.width == resourceWidth && state.height == resourceHeight &&
				state.guideWidth == resourceGuideWidth && state.guideHeight == resourceGuideHeight && state.format == colorFormat &&
				state.output.resource && state.output.srv && state.output.uav;
			if (!outputMatches) {
				ResultShapingEyeState replacement;
				replacement.width = resourceWidth;
				replacement.height = resourceHeight;
				replacement.guideWidth = resourceGuideWidth;
				replacement.guideHeight = resourceGuideHeight;
				replacement.regionX = regionX;
				replacement.regionY = regionY;
				replacement.modelResolution = modelResolution;
				replacement.format = colorFormat;
				const std::string suffix = eyeIndex == 0 ? "Left" : "Right";
				if (!EnsureResultShapingTexture(device, resourceWidth, resourceHeight, colorFormat,
					replacement.output, ("NeuralRendering::ResultShapingOutput" + suffix).c_str()))
					return false;
				state = std::move(replacement);
			} else if (state.regionX != regionX || state.regionY != regionY ||
				state.modelResolution != modelResolution) {
				if (!preserveCropMotion || (!stableHistory && state.modelResolution != modelResolution) ||
					std::uint32_t(globals::state->frameCount - state.historyFrame) != 1u)
					state.valid = false;
				state.regionX = regionX;
				state.regionY = regionY;
				state.modelResolution = modelResolution;
			}

			if (state.valid && std::uint32_t(globals::state->frameCount - state.historyFrame) != 1u)
				state.valid = false;

			if (needHistory && !HasResultShapingHistory(state) && !state.historyAllocationFailed) {
				std::array<TemporalTexture, 2> history;
				TemporalTexture previousBase;
				TemporalTexture previousDepth;
				const std::string suffix = eyeIndex == 0 ? "Left" : "Right";
				const bool historyCreated =
					EnsureResultShapingTexture(device, resourceWidth, resourceHeight, colorFormat,
						history[0], ("NeuralRendering::ResultShapingHistoryA" + suffix).c_str()) &&
					EnsureResultShapingTexture(device, resourceWidth, resourceHeight, colorFormat,
						history[1], ("NeuralRendering::ResultShapingHistoryB" + suffix).c_str()) &&
					EnsureResultShapingTexture(device, resourceWidth, resourceHeight, colorFormat,
						previousBase, ("NeuralRendering::ResultShapingBase" + suffix).c_str()) &&
					EnsureResultShapingTexture(device, resourceGuideWidth, resourceGuideHeight, DXGI_FORMAT_R32_FLOAT,
						previousDepth, ("NeuralRendering::ResultShapingDepth" + suffix).c_str());
				if (historyCreated) {
					state.history = std::move(history);
					state.historyIndex = 0;
					state.previousBase = std::move(previousBase);
					state.previousDepth = std::move(previousDepth);
					state.valid = false;
				} else {
					state.history = {};
					state.previousBase = {};
					state.previousDepth = {};
					state.historyAllocationFailed = true;
					state.valid = false;
				}
			}
			return true;
		}

		static bool HasResultShapingHistory(const ResultShapingEyeState& state)
		{
			for (const auto& history : state.history)
				if (!history.resource || !history.srv || !history.uav)
					return false;
			return state.previousBase.resource && state.previousBase.srv && state.previousBase.uav &&
				state.previousDepth.resource && state.previousDepth.srv && state.previousDepth.uav;
		}

		bool EnsureResultShapingShader(ID3D11Device* device)
		{
			if (!device)
				return false;
			if (!resultShapingCS.Get(L"Data\\Shaders\\Upscaling\\NeuralRendering\\ResultShapingCS.hlsl", {},
				"cs_5_0", "main", "NeuralRendering::ResultShapingCS"))
				return false;

			if (!resultShapingCB) {
				D3D11_BUFFER_DESC bufferDesc{};
				bufferDesc.ByteWidth = sizeof(ResultShapingConstants);
				bufferDesc.Usage = D3D11_USAGE_DEFAULT;
				bufferDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&bufferDesc, nullptr, resultShapingCB.GetAddressOf())))
					return false;
				Util::SetResourceName(resultShapingCB.Get(), "NeuralRendering::ResultShapingCB");
			}

			if (!resultShapingSampler) {
				D3D11_SAMPLER_DESC samplerDesc{};
				samplerDesc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
				samplerDesc.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.MinLOD = 0.0f;
				samplerDesc.MaxLOD = std::numeric_limits<float>::max();
				if (FAILED(device->CreateSamplerState(&samplerDesc, resultShapingSampler.GetAddressOf())))
					return false;
				Util::SetResourceName(resultShapingSampler.Get(), "NeuralRendering::ResultShapingSampler");
			}
			return true;
		}

		void ClearResultShapingBindings(ID3D11DeviceContext* context)
		{
			if (!context)
				return;
			std::array<ID3D11ShaderResourceView*, 7> nullSources{};
			std::array<ID3D11UnorderedAccessView*, 2> nullTargets{};
			ID3D11Buffer* nullBuffer = nullptr;
			ID3D11SamplerState* nullSampler = nullptr;
			context->CSSetShaderResources(0, static_cast<UINT>(nullSources.size()), nullSources.data());
			context->CSSetUnorderedAccessViews(0, static_cast<UINT>(nullTargets.size()), nullTargets.data(), nullptr);
			context->CSSetConstantBuffers(0, 1, &nullBuffer);
			context->CSSetSamplers(0, 1, &nullSampler);
			context->CSSetShader(nullptr, nullptr, 0);
		}

		ID3D11Resource* ApplyResultShaping(ID3D11Device* device, ID3D11DeviceContext* context,
			EyeResources& eye, std::uint32_t eyeIndex, ID3D11Resource* nrOutput,
			ID3D11ShaderResourceView* nrOutputSRV, std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t regionX, std::uint32_t regionY, float motionScaleX, float motionScaleY,
			const Tuning& tuning)
		{
			const bool stabilizeConfigured = tuning.stabilizeMode != 0 || tuning.singlePassLadder;
			const bool stabilizeAllowed = stabilizeConfigured && tuning.temporalReuseCadence == 0;
			if ((!tuning.resultShapingEnabled || !HasResultShapingEffect(tuning)) && !stabilizeAllowed && !(tuning.nearBlackProtection > 0.0f))
				return nrOutput;

			auto& state = eye.resultShaping;
			const bool cropMoved = state.regionX != regionX || state.regionY != regionY;
			const auto previousLayout = std::array<std::uint32_t, 4>{ state.historyWidth, state.historyHeight, state.historyGuideWidth, state.historyGuideHeight };
			const auto originDelta = std::array<float, 2>{ float(double(regionX) - state.regionX), float(double(regionY) - state.regionY) };
			const bool layoutChanged = state.historyWidth != colorWidth || state.historyHeight != colorHeight || state.modelResolution != tuning.modelResolutionPercent;
			if (tuning.singlePassLadder && layoutChanged && state.valid)
				state.transitionRemainingMs = tuning.ladderHandoffMs;
			const bool bridgeActive = tuning.singlePassLadder && state.transitionRemainingMs > 0.0f;
			const bool hasDepth = eye.depth.srv11 && eye.depth.resource11;
			std::uint32_t stabilizeMode = stabilizeAllowed && hasDepth ? (bridgeActive ? 2u : tuning.stabilizeMode) : 0u;
			if (eye.movingCrop && stabilizeMode == 1u)
				stabilizeMode = 2u;
			if (stabilizeMode == 2u && (!eye.motionVectors.srv11 || !std::isfinite(motionScaleX) || !std::isfinite(motionScaleY)))
				stabilizeMode = 0;
			if (!nrOutput || !nrOutputSRV || !eye.color.srv11 || !context ||
				!EnsureResultShapingResources(device, eye, eyeIndex, colorWidth, colorHeight,
					guideWidth, guideHeight, regionX, regionY, tuning.modelResolutionPercent, stabilizeAllowed, stabilizeMode == 2u || tuning.singlePassLadder, tuning.singlePassLadder) ||
				!EnsureResultShapingShader(device)) {
				state.valid = false;
				if (tuning.singlePassLadder) LatchFailure("ladder residual handoff", E_FAIL);
				if (!resultShapingFailureLogged) {
					logger::warn("[DLSSNR] result shaping unavailable; using the unmodified NR output");
					resultShapingFailureLogged = true;
				}
				return nrOutput;
			}

			const bool historyAvailable = HasResultShapingHistory(state);
			if (stabilizeMode != 0 && !historyAvailable) {
				if (!resultStabilizationFailureLogged) {
					logger::warn("[DLSSNR] result stabilization history unavailable; keeping result shaping active without temporal smoothing");
					resultStabilizationFailureLogged = true;
				}
				stabilizeMode = 0;
			}
			if (stabilizeMode != 0 && !state.valid)
				stabilizeMode = 0;
			float frameDeltaSeconds = globals::game::deltaTime ? *globals::game::deltaTime : (1.0f / 90.0f);
			if (!std::isfinite(frameDeltaSeconds) || frameDeltaSeconds <= 0.0f)
				frameDeltaSeconds = 1.0f / 90.0f;
			frameDeltaSeconds = std::clamp(frameDeltaSeconds, 1.0f / 240.0f, 0.25f);

			ResultShapingConstants constants{};
			constants.colorWidth = colorWidth;
			constants.colorHeight = colorHeight;
			constants.guideWidth = guideWidth;
			constants.guideHeight = guideHeight;
			// Motion stabilization offsets color-pixel positions; convert from guide pixels.
			constants.motionScaleX = eye.sceneColorMotionScale[0] > 0 ? eye.sceneColorMotionScale[0] : GuideToColorMotionScale(motionScaleX, colorWidth, guideWidth);
			constants.motionScaleY = eye.sceneColorMotionScale[1] > 0 ? eye.sceneColorMotionScale[1] : GuideToColorMotionScale(motionScaleY, colorHeight, guideHeight);
			constants.frameDeltaSeconds = frameDeltaSeconds;
			constants.stabilizeTimeMs = bridgeActive ? tuning.ladderHandoffMs : tuning.stabilizeTimeMs;
			constants.editStrength = tuning.resultEditStrength;
			constants.brightening = tuning.resultBrightening;
			constants.darkening = tuning.resultDarkening;
			constants.colorStrength = tuning.resultColor;
			constants.hueShiftStrength = tuning.resultHueShiftStrength;
			constants.shadows = tuning.resultShadows;
			constants.midtones = tuning.resultMidtones;
			constants.highlights = tuning.resultHighlights;
			constants.largeScaleTone = tuning.resultLargeScaleTone;
			constants.fineDetail = tuning.resultFineDetail;
			constants.detailRadius = tuning.resultDetailRadius;
			constants.haloSuppression = tuning.resultHaloSuppression;
			constants.maxBrighteningStops = tuning.resultMaxBrighteningStops;
			constants.maxDarkeningStops = tuning.resultMaxDarkeningStops;
			constants.maxColorChangeStops = tuning.resultMaxColorChangeStops;
			constants.depthThreshold = tuning.stabilizeDepthThreshold;
			constants.colorTolerance = tuning.stabilizeColorTolerance;
			constants.resumeBlendAlpha = std::clamp(tuning.resumeBlendAlpha, 0.0f, 1.0f);
			constants.nearBlackProtection = std::clamp(std::isfinite(tuning.nearBlackProtection) ? tuning.nearBlackProtection : 0.0f, 0.0f, 2.0f);
			constants.nearBlackThreshold = std::clamp(std::isfinite(tuning.nearBlackThreshold) ? tuning.nearBlackThreshold : 0.035f, 0.001f, 0.25f);
			constants.nearBlackLiftSoftness = std::clamp(std::isfinite(tuning.nearBlackLiftSoftness) ? tuning.nearBlackLiftSoftness : 0.001f, 0.00001f, 0.05f);
			constants.shapeEnabled = tuning.resultShapingEnabled ? 1u : 0u;
			constants.stabilizeMode = stabilizeMode;
			constants.stabilizeDetail = bridgeActive || tuning.stabilizeDetail ? 1u : 0u;
			constants.historyEdgeFadePixels = cropMoved || bridgeActive ? 2.0f : 0.0f;
			constants.previousLayout = previousLayout;
			if (!tuning.singlePassLadder)
				constants.previousLayout = { colorWidth, colorHeight, guideWidth, guideHeight };
			constants.originDelta = tuning.singlePassLadder ? originDelta : std::array<float, 2>{};
			constants.transitionWeightScale = bridgeActive ? std::clamp(state.transitionRemainingMs / std::max(tuning.ladderHandoffMs, 1.0f), 0.0f, 1.0f) : 1.0f;

			CS_GPU_PASS("NeuralRendering::ResultShaping");
			context->UpdateSubresource(resultShapingCB.Get(), 0, nullptr, &constants, 0, 0);
			std::array<ID3D11ShaderResourceView*, 7> sources{};
			sources[0] = eye.color.srv11.Get();
			sources[1] = nrOutputSRV;
			sources[2] = eye.depth.srv11.Get();
			sources[3] = eye.motionVectors.srv11.Get();
			const bool recordHistory = stabilizeAllowed && historyAvailable && eye.depth.resource11;
			const std::uint32_t previousIndex = state.historyIndex & 1u;
			const std::uint32_t nextIndex = previousIndex ^ 1u;
			if (stabilizeMode != 0) {
				sources[4] = state.history[previousIndex].srv.Get();
				sources[5] = state.previousBase.srv.Get();
				sources[6] = state.previousDepth.srv.Get();
			}
			std::array<ID3D11UnorderedAccessView*, 2> targets{
				state.output.uav.Get(), recordHistory ? state.history[nextIndex].uav.Get() : nullptr };
			ID3D11Buffer* constantBuffer = resultShapingCB.Get();
			ID3D11SamplerState* sampler = resultShapingSampler.Get();
			context->CSSetShader(resultShapingCS.get(), nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &constantBuffer);
			context->CSSetShaderResources(0, static_cast<UINT>(sources.size()), sources.data());
			context->CSSetUnorderedAccessViews(0, static_cast<UINT>(targets.size()), targets.data(), nullptr);
			context->CSSetSamplers(0, 1, &sampler);
			context->Dispatch((colorWidth + 7) / 8, (colorHeight + 7) / 8, 1);
			ClearResultShapingBindings(context);

			if (recordHistory) {
				// The stabilized result already sits in the next history slot; only the
				// per-frame input and depth guides need a copy.
				state.historyIndex = nextIndex;
				state.historyFrame = globals::state->frameCount;
				state.historyWidth = colorWidth;
				state.historyHeight = colorHeight;
				state.historyGuideWidth = guideWidth;
				state.historyGuideHeight = guideHeight;
				state.transitionRemainingMs = std::max(0.0f, state.transitionRemainingMs - frameDeltaSeconds * 1000.0f);
				const D3D11_BOX baseBox{ 0, 0, 0, colorWidth, colorHeight, 1 };
				const D3D11_BOX depthBox{ 0, 0, 0, guideWidth, guideHeight, 1 };
				context->CopySubresourceRegion(state.previousBase.resource.Get(), 0, 0, 0, 0, eye.color.resource11.Get(), 0, &baseBox);
				context->CopySubresourceRegion(state.previousDepth.resource.Get(), 0, 0, 0, 0, eye.depth.resource11.Get(), 0, &depthBox);
				state.valid = true;
			} else {
				state.valid = false;
			}
			return state.output.resource.Get();
		}

		bool EnsureTemporalReuseShaders(ID3D11Device* device)
		{
			if (!device)
				return false;
			const wchar_t* shaderPath = L"Data\\Shaders\\Upscaling\\NeuralRendering\\TemporalReuseCS.hlsl";
			if (!temporalSnapshotCS.Get(shaderPath, {}, "cs_5_0", "Snapshot", "NeuralRendering::TemporalReuseSnapshotCS") ||
				!temporalAccumulateCS.Get(shaderPath, {}, "cs_5_0", "Accumulate", "NeuralRendering::TemporalReuseAccumulateCS") ||
				!temporalReprojectCS.Get(shaderPath, {}, "cs_5_0", "Reproject", "NeuralRendering::TemporalReuseReprojectCS"))
				return false;

			if (!temporalReuseCB) {
				D3D11_BUFFER_DESC bufferDesc{};
				bufferDesc.ByteWidth = sizeof(TemporalReuseConstants);
				bufferDesc.Usage = D3D11_USAGE_DEFAULT;
				bufferDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&bufferDesc, nullptr, temporalReuseCB.GetAddressOf())))
					return false;
				Util::SetResourceName(temporalReuseCB.Get(), "NeuralRendering::TemporalReuseCB");
			}

			if (!temporalReuseSampler) {
				D3D11_SAMPLER_DESC samplerDesc{};
				samplerDesc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
				samplerDesc.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.MinLOD = 0.0f;
				samplerDesc.MaxLOD = std::numeric_limits<float>::max();
				if (FAILED(device->CreateSamplerState(&samplerDesc, temporalReuseSampler.GetAddressOf())))
					return false;
				Util::SetResourceName(temporalReuseSampler.Get(), "NeuralRendering::TemporalReuseSampler");
			}
			return true;
		}

		void ClearTemporalReuseBindings(ID3D11DeviceContext* context)
		{
			if (!context)
				return;
			std::array<ID3D11ShaderResourceView*, 8> nullSources{};
			std::array<ID3D11UnorderedAccessView*, 4> nullTargets{};
			ID3D11Buffer* nullBuffer = nullptr;
			ID3D11SamplerState* nullSampler = nullptr;
			context->CSSetShaderResources(0, static_cast<UINT>(nullSources.size()), nullSources.data());
			context->CSSetUnorderedAccessViews(0, static_cast<UINT>(nullTargets.size()), nullTargets.data(), nullptr);
			context->CSSetConstantBuffers(0, 1, &nullBuffer);
			context->CSSetSamplers(0, 1, &nullSampler);
			context->CSSetShader(nullptr, nullptr, 0);
		}

		bool DispatchTemporalSnapshot(ID3D11Device* device, ID3D11DeviceContext* context,
			const EyeResources& eye, ID3D11ShaderResourceView* teacherSRV,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight)
		{
			if (!EnsureTemporalReuseShaders(device) || !context || !eye.color.srv11 || !teacherSRV ||
				!eye.temporal.base.uav || !eye.temporal.residual.uav)
				return false;
			CS_GPU_PASS("NeuralRendering::TemporalReuseSnapshot");
			const TemporalReuseConstants constants{
				.colorWidth = colorWidth,
				.colorHeight = colorHeight,
				.guideWidth = guideWidth,
				.guideHeight = guideHeight,
			};
			context->UpdateSubresource(temporalReuseCB.Get(), 0, nullptr, &constants, 0, 0);
			std::array<ID3D11ShaderResourceView*, 8> sources{};
			sources[0] = eye.color.srv11.Get();
			sources[1] = teacherSRV;
			std::array<ID3D11UnorderedAccessView*, 4> targets{};
			targets[0] = eye.temporal.base.uav.Get();
			targets[1] = eye.temporal.residual.uav.Get();
			ID3D11Buffer* constantBuffer = temporalReuseCB.Get();
			ID3D11SamplerState* sampler = temporalReuseSampler.Get();
			context->CSSetShader(temporalSnapshotCS.get(), nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &constantBuffer);
			context->CSSetShaderResources(0, static_cast<UINT>(sources.size()), sources.data());
			context->CSSetUnorderedAccessViews(0, static_cast<UINT>(targets.size()), targets.data(), nullptr);
			context->CSSetSamplers(0, 1, &sampler);
			context->Dispatch((colorWidth + 7) / 8, (colorHeight + 7) / 8, 1);
			ClearTemporalReuseBindings(context);
			return true;
		}

		bool DispatchTemporalAccumulation(ID3D11Device* device, ID3D11DeviceContext* context,
			const EyeResources& eye, const TemporalTexture& previousAccumulated,
			const TemporalTexture& nextAccumulated, std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			float motionScaleX, float motionScaleY)
		{
			if (!EnsureTemporalReuseShaders(device) || !context || !eye.motionVectors.srv11 ||
				!previousAccumulated.srv || !nextAccumulated.uav)
				return false;
			CS_GPU_PASS("NeuralRendering::TemporalReuseAccumulate");
			const TemporalReuseConstants constants{
				.colorWidth = colorWidth,
				.colorHeight = colorHeight,
				.guideWidth = guideWidth,
				.guideHeight = guideHeight,
				// The shader offsets color-pixel positions; convert from guide pixels.
				.motionScaleX = GuideToColorMotionScale(motionScaleX, colorWidth, guideWidth),
				.motionScaleY = GuideToColorMotionScale(motionScaleY, colorHeight, guideHeight),
			};
			context->UpdateSubresource(temporalReuseCB.Get(), 0, nullptr, &constants, 0, 0);
			std::array<ID3D11ShaderResourceView*, 8> sources{};
			sources[6] = eye.motionVectors.srv11.Get();
			sources[7] = previousAccumulated.srv.Get();
			std::array<ID3D11UnorderedAccessView*, 4> targets{};
			targets[2] = nextAccumulated.uav.Get();
			ID3D11Buffer* constantBuffer = temporalReuseCB.Get();
			ID3D11SamplerState* sampler = temporalReuseSampler.Get();
			context->CSSetShader(temporalAccumulateCS.get(), nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &constantBuffer);
			context->CSSetShaderResources(0, static_cast<UINT>(sources.size()), sources.data());
			context->CSSetUnorderedAccessViews(0, static_cast<UINT>(targets.size()), targets.data(), nullptr);
			context->CSSetSamplers(0, 1, &sampler);
			context->Dispatch((colorWidth + 7) / 8, (colorHeight + 7) / 8, 1);
			ClearTemporalReuseBindings(context);
			return true;
		}

		bool DispatchTemporalReprojection(ID3D11Device* device, ID3D11DeviceContext* context,
			const EyeResources& eye, ID3D11UnorderedAccessView* outputUAV,
			const TemporalEyeState& temporal,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			float depthThreshold, float colorTolerance)
		{
			if (!EnsureTemporalReuseShaders(device) || !context || !eye.color.srv11 || !eye.depth.srv11 ||
				!outputUAV || !temporal.base.srv || !temporal.depth.srv || !temporal.residual.srv ||
				!temporal.accumulatedMotion[temporal.accumulatedMotionIndex].srv)
				return false;
			CS_GPU_PASS("NeuralRendering::TemporalReuseReproject");
			const TemporalReuseConstants constants{
				.colorWidth = colorWidth,
				.colorHeight = colorHeight,
				.guideWidth = guideWidth,
				.guideHeight = guideHeight,
				.depthThreshold = depthThreshold,
				.colorTolerance = colorTolerance,
			};
			context->UpdateSubresource(temporalReuseCB.Get(), 0, nullptr, &constants, 0, 0);
			std::array<ID3D11ShaderResourceView*, 8> sources{};
			sources[0] = eye.color.srv11.Get();
			sources[2] = eye.depth.srv11.Get();
			sources[3] = temporal.base.srv.Get();
			sources[4] = temporal.depth.srv.Get();
			sources[5] = temporal.residual.srv.Get();
			sources[7] = temporal.accumulatedMotion[temporal.accumulatedMotionIndex].srv.Get();
			std::array<ID3D11UnorderedAccessView*, 4> targets{};
			targets[3] = outputUAV;
			ID3D11Buffer* constantBuffer = temporalReuseCB.Get();
			ID3D11SamplerState* sampler = temporalReuseSampler.Get();
			context->CSSetShader(temporalReprojectCS.get(), nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &constantBuffer);
			context->CSSetShaderResources(0, static_cast<UINT>(sources.size()), sources.data());
			context->CSSetUnorderedAccessViews(0, static_cast<UINT>(targets.size()), targets.data(), nullptr);
			context->CSSetSamplers(0, 1, &sampler);
			context->Dispatch((colorWidth + 7) / 8, (colorHeight + 7) / 8, 1);
			ClearTemporalReuseBindings(context);
			return true;
		}

		bool RecordTemporalHistory(ID3D11Device* device, ID3D11DeviceContext* context, EyeResources& eye,
			ID3D11ShaderResourceView* teacherSRV,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t regionX, std::uint32_t regionY)
		{
			if (!EnsureTemporalEyeResources(device, eye, colorWidth, colorHeight, guideWidth, guideHeight) ||
				!DispatchTemporalSnapshot(device, context, eye, teacherSRV,
					colorWidth, colorHeight, guideWidth, guideHeight) ||
				!eye.depth.resource11 || !eye.temporal.depth.resource)
				return false;
			context->CopyResource(eye.temporal.depth.resource.Get(), eye.depth.resource11.Get());
			const float clearValue[4]{};
			context->ClearUnorderedAccessViewFloat(eye.temporal.accumulatedMotion[0].uav.Get(), clearValue);
			context->ClearUnorderedAccessViewFloat(eye.temporal.accumulatedMotion[1].uav.Get(), clearValue);
			eye.temporal.regionX = regionX;
			eye.temporal.regionY = regionY;
			eye.temporal.accumulatedMotionIndex = 0;
			eye.temporal.valid = true;
			return true;
		}

		bool TryTemporalReuse(ID3D11Device* device, ID3D11DeviceContext* context, EyeResources& eye,
			ID3D11UnorderedAccessView* outputUAV,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			float motionScaleX, float motionScaleY, const Tuning& tuning)
		{
			if (!eye.temporal.valid || !EnsureTemporalEyeResources(device, eye, colorWidth, colorHeight, guideWidth, guideHeight))
				return false;
			const std::uint32_t previousIndex = eye.temporal.accumulatedMotionIndex;
			const std::uint32_t nextIndex = previousIndex ^ 1u;
			if (!DispatchTemporalAccumulation(device, context, eye,
				eye.temporal.accumulatedMotion[previousIndex], eye.temporal.accumulatedMotion[nextIndex],
				colorWidth, colorHeight, guideWidth, guideHeight, motionScaleX, motionScaleY)) {
				LogTemporalReuseFailure("motion accumulation");
				InvalidateTemporalHistory();
				return false;
			}
			eye.temporal.accumulatedMotionIndex = nextIndex;
			if (!DispatchTemporalReprojection(device, context, eye, outputUAV, eye.temporal,
				colorWidth, colorHeight, guideWidth, guideHeight,
				tuning.temporalReuseDepthThreshold, tuning.temporalReuseColorTolerance)) {
				LogTemporalReuseFailure("residual reprojection");
				InvalidateTemporalHistory();
				return false;
			}
			return true;
		}

		void SyncResultShapingConfig(const Tuning& tuning)
		{
			const auto next = MakeResultShapingConfigKey(tuning);
			if (resultShapingConfigInitialized && resultShapingConfig == next)
				return;
			resultShapingConfig = next;
			resultShapingConfigInitialized = true;
			for (auto& eye : eyes) {
				eye.resultShaping.valid = false;
				eye.resultShaping.historyAllocationFailed = false;
			}
		}

		void InvalidateTemporalHistory(bool preserveHandoff = false)
		{
			for (auto& eye : eyes) {
				eye.temporal.valid = false;
				eye.temporal.accumulatedMotionIndex = 0;
				eye.resultShaping.valid = false;
				if (!preserveHandoff)
					eye.handoff.valid = false;
			}
			temporalFrameIndex = 0;
			// Keep this marker separate from the private residual buffers. If a
			// skipped-frame dispatch fails, the next native Feature 18 call still
			// must reset NGX history before the renderer falls back to the full path.
		}

		void AdvanceTemporalFrame(const Tuning& tuning)
		{
			if (IsTemporalReuseConfigured(tuning))
				++temporalFrameIndex;
			else
				temporalFrameIndex = 0;
		}

		void LogTemporalReuseFailure(const char* operation)
		{
			if (temporalReuseWarningLogged)
				return;
			temporalReuseWarningLogged = true;
			logger::warn("[DLSSNR] temporal residual reuse unavailable during {}; falling back to full Feature 18", operation);
		}

		void LogTemporalReuseActive(std::uint32_t cadence, bool cropLocal)
		{
			bool& routeLogged = cropLocal ? temporalReuseCropActiveLogged : temporalReuseActiveLogged;
			if (routeLogged)
				return;
			routeLogged = true;
			logger::info("[DLSSNR] experimental temporal residual reuse active cadence=N{} route={} exact-MV stable-layout", cadence,
				cropLocal ? "crop-local" : "full-eye");
		}

		bool ExecuteCascade(ID3D12GraphicsCommandList* commandList, std::uint32_t eyeIndex, std::uint32_t tierIndex,
			ID3D12Resource* initialInput, ID3D12Resource* depth, ID3D12Resource* motionVectors,
			const std::array<ID3D12Resource*, kCascadePassCount - 1>& intermediates,
			ID3D12Resource* secondPassOutput, ID3D12Resource* finalOutput,
			std::uint32_t firstInputWidth, std::uint32_t firstInputHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t outputWidth, std::uint32_t outputHeight,
			std::uint32_t creationFirstInputWidth, std::uint32_t creationFirstInputHeight,
			std::uint32_t creationOutputWidth, std::uint32_t creationOutputHeight,
			float motionVectorScaleX, float motionVectorScaleY,
			const Tuning& tuning, std::uint32_t passCount, bool reset)
		{
			if (!commandList || !initialInput || !depth || !motionVectors || !finalOutput ||
				passCount == 0 || passCount > kCascadePassCount)
				return false;
			for (std::uint32_t intermediateIndex = 0; intermediateIndex + 1 < passCount; ++intermediateIndex) {
				if (!intermediates[intermediateIndex])
					return false;
			}
			const std::uint32_t pass2Coverage = passCount > 1 ? std::clamp(tuning.secondPass.coveragePercent, 50u, 100u) : 100u;
			const bool croppedSecondPass = passCount > 1 && pass2Coverage < 100;
			if (croppedSecondPass && !secondPassOutput)
				return false;

			for (std::uint32_t passIndex = 0; passIndex < passCount; ++passIndex) {
				ID3D12Resource* input = passIndex == 0 ? initialInput : intermediates[passIndex - 1];
				ID3D12Resource* output = (passIndex == 1 && croppedSecondPass) ? secondPassOutput :
					((passIndex + 1 == passCount) ? finalOutput : intermediates[passIndex]);
				if (!input || !output || input == output)
					return false;

				CS_GPU_PASS_SELECT3(passIndex,
					"NeuralRendering::EvaluatePass0", "NeuralRendering::EvaluatePass1", "NeuralRendering::EvaluatePass2");
				TransitionEvaluationResources(commandList, input, depth, motionVectors, output, true);
				Feature18GuideContract guide{};
				guide.colorWidth = passIndex == 0 ? firstInputWidth : outputWidth;
				guide.colorHeight = passIndex == 0 ? firstInputHeight : outputHeight;
				guide.depthWidth = guideWidth;
				guide.depthHeight = guideHeight;
				guide.motionWidth = guideWidth;
				guide.motionHeight = guideHeight;
				guide.outputWidth = outputWidth;
				guide.outputHeight = outputHeight;
				guide.creationInputWidth = passIndex == 0 ? creationFirstInputWidth : creationOutputWidth;
				guide.creationInputHeight = passIndex == 0 ? creationFirstInputHeight : creationOutputHeight;
				guide.creationOutputWidth = creationOutputWidth;
				guide.creationOutputHeight = creationOutputHeight;
				if (passIndex == 1 && croppedSecondPass) {
					const auto colorW = ScaleDimension(outputWidth, pass2Coverage);
					const auto colorH = ScaleDimension(outputHeight, pass2Coverage);
					const auto guideW = ScaleDimension(guideWidth, pass2Coverage);
					const auto guideH = ScaleDimension(guideHeight, pass2Coverage);
					guide.colorBaseX = (outputWidth - colorW) / 2;
					guide.colorBaseY = (outputHeight - colorH) / 2;
					guide.colorWidth = colorW;
					guide.colorHeight = colorH;
					guide.depthBaseX = (guideWidth - guideW) / 2;
					guide.depthBaseY = (guideHeight - guideH) / 2;
					guide.depthWidth = guideW;
					guide.depthHeight = guideH;
					guide.motionBaseX = guide.depthBaseX;
					guide.motionBaseY = guide.depthBaseY;
					guide.motionWidth = guideW;
					guide.motionHeight = guideH;
					guide.outputBaseX = (outputWidth - colorW) / 2;
					guide.outputBaseY = (outputHeight - colorH) / 2;
					guide.outputWidth = colorW;
					guide.outputHeight = colorH;
					// Only the valid rectangle changes. Feature18 remains created against
					// the same full-size P1/P2 envelope at every coverage setting.
					guide.creationInputWidth = creationOutputWidth;
					guide.creationInputHeight = creationOutputHeight;
					guide.creationOutputWidth = creationOutputWidth;
					guide.creationOutputHeight = creationOutputHeight;
				}
				guide.motionVectorScaleX = motionVectorScaleX;
				guide.motionVectorScaleY = motionVectorScaleY;
				guide.motionVectorsLowResolution =
					guide.motionWidth <= guide.colorWidth && guide.motionHeight <= guide.colorHeight;
				const Tuning passTuning = TuningForCascadePass(tuning, passIndex);
				const bool succeeded = Runtime::Instance().Execute(commandList, FeatureSlot(eyeIndex, tierIndex, passIndex),
					input, depth, motionVectors, output, guide, passTuning, reset);
				TransitionEvaluationResources(commandList, input, depth, motionVectors, output, false);
				if (!succeeded) {
					logger::warn("[DLSSNR] cascade pass failed eye={} pass={} of {} coverage={}%", eyeIndex, passIndex + 1, passCount,
						passIndex == 1 ? pass2Coverage : 100u);
					return false;
				}
			}
			return true;
		}

		struct ModelResolutionConstants
		{
			std::uint32_t mode = 0;
			std::uint32_t width = 0;
			std::uint32_t height = 0;
			std::uint32_t sourceWidth = 0;
			std::uint32_t sourceHeight = 0;
			float transferStrength = 1.0f;
			float colourStrength = 1.0f;
			float maxRatio = 4.0f;
			float residualStrength = 1.0f;
			float padding0 = 0.0f;
			float padding1 = 0.0f;
			float padding2 = 0.0f;
			std::array<float, 2> sampleScale{ 1, 1 };
			std::array<float, 2> sampleOffset{};
		};
		static_assert(sizeof(ModelResolutionConstants) % 16 == 0);

		bool EnsureModelResolutionResources(ID3D11Device* device)
		{
			if (!device)
				return false;
			if (!modelResolutionCS.Get(
				L"Data\\Shaders\\Upscaling\\NeuralRendering\\ModelResolutionCS.hlsl", {}, "cs_5_0",
				"main", "NeuralRendering::ModelResolutionCS"))
				return false;

			if (!modelResolutionCB) {
				D3D11_BUFFER_DESC bufferDesc{};
				bufferDesc.ByteWidth = sizeof(ModelResolutionConstants);
				bufferDesc.Usage = D3D11_USAGE_DEFAULT;
				bufferDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&bufferDesc, nullptr, modelResolutionCB.GetAddressOf())))
					return false;
				Util::SetResourceName(modelResolutionCB.Get(), "NeuralRendering::ModelResolutionCB");
			}

			if (!modelResolutionSampler) {
				D3D11_SAMPLER_DESC samplerDesc{};
				samplerDesc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
				samplerDesc.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.MinLOD = 0.0f;
				samplerDesc.MaxLOD = std::numeric_limits<float>::max();
				if (FAILED(device->CreateSamplerState(&samplerDesc, modelResolutionSampler.GetAddressOf())))
					return false;
				Util::SetResourceName(modelResolutionSampler.Get(), "NeuralRendering::ModelResolutionSampler");
			}
			return true;
		}

		bool DispatchModelInput(ID3D11Device* device, ID3D11DeviceContext* context, const EyeResources& eye,
			const TierResources& tier,
			std::uint32_t sourceWidth, std::uint32_t sourceHeight,
			std::uint32_t modelWidth, std::uint32_t modelHeight, bool exactArea)
		{
			if (!EnsureModelResolutionResources(device) || !context || !eye.color.srv11 || !tier.modelInput.uav11)
				return false;
			CS_GPU_PASS("NeuralRendering::ModelDownsample");
			ModelResolutionConstants constants{
				.mode = exactArea ? 2u : 0u,
				.width = modelWidth,
				.height = modelHeight,
				.sourceWidth = sourceWidth,
				.sourceHeight = sourceHeight,
			};
			constants.sampleScale = { eye.modelSampling[0], eye.modelSampling[1] };
			constants.sampleOffset = { eye.modelSampling[2], eye.modelSampling[3] };
			context->UpdateSubresource(modelResolutionCB.Get(), 0, nullptr, &constants, 0, 0);
			ID3D11ShaderResourceView* source = eye.color.srv11.Get();
			ID3D11UnorderedAccessView* target = tier.modelInput.uav11.Get();
			ID3D11Buffer* constantBuffer = modelResolutionCB.Get();
			ID3D11SamplerState* sampler = modelResolutionSampler.Get();
			context->CSSetShader(modelResolutionCS.get(), nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &constantBuffer);
			context->CSSetShaderResources(0, 1, &source);
			context->CSSetUnorderedAccessViews(0, 1, &target, nullptr);
			context->CSSetSamplers(0, 1, &sampler);
			context->Dispatch((modelWidth + 7) / 8, (modelHeight + 7) / 8, 1);
			ClearModelResolutionBindings(context, 1);
			return true;
		}

		bool DispatchModelResolve(ID3D11Device* device, ID3D11DeviceContext* context, const EyeResources& eye,
			const TierResources& tier,
			std::uint32_t width, std::uint32_t height, const ModelResolveSettings& resolveSettings,
			bool matchedResidual)
		{
			if (!EnsureModelResolutionResources(device) || !context || !eye.color.srv11 || !tier.modelInput.srv11 ||
				!tier.output.srv11 || !tier.resolvedUAV)
				return false;
			CS_GPU_PASS("NeuralRendering::ModelResolve");
			ModelResolutionConstants constants{
				.mode = matchedResidual ? 3u : 1u,
				.width = width,
				.height = height,
				.sourceWidth = ScaleDimension(width, tier.modelResolution),
				.sourceHeight = ScaleDimension(height, tier.modelResolution),
				.transferStrength = resolveSettings.transferStrength,
				.colourStrength = resolveSettings.colourStrength,
				.maxRatio = resolveSettings.maxRatio,
				.residualStrength = resolveSettings.residualStrength,
			};
			constants.sampleScale = { 1.0f / eye.modelSampling[0], 1.0f / eye.modelSampling[1] };
			constants.sampleOffset = { -eye.modelSampling[2] / eye.modelSampling[0], -eye.modelSampling[3] / eye.modelSampling[1] };
			context->UpdateSubresource(modelResolutionCB.Get(), 0, nullptr, &constants, 0, 0);
			ID3D11ShaderResourceView* sources[3]{
				tier.modelInput.srv11.Get(), tier.output.srv11.Get(), eye.color.srv11.Get()
			};
			ID3D11UnorderedAccessView* target = tier.resolvedUAV.Get();
			ID3D11Buffer* constantBuffer = modelResolutionCB.Get();
			ID3D11SamplerState* sampler = modelResolutionSampler.Get();
			context->CSSetShader(modelResolutionCS.get(), nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &constantBuffer);
			context->CSSetShaderResources(0, 3, sources);
			context->CSSetUnorderedAccessViews(0, 1, &target, nullptr);
			context->CSSetSamplers(0, 1, &sampler);
			context->Dispatch((width + 7) / 8, (height + 7) / 8, 1);
			ClearModelResolutionBindings(context, 3);
			return true;
		}

		bool EnsureAdaptiveHandoffShaders(ID3D11Device* device)
		{
			if (!device)
				return false;
			if (!adaptiveHandoffCS.Get(
				L"Data\\Shaders\\Upscaling\\NeuralRendering\\AdaptiveHandoffCS.hlsl", {}, "cs_5_0",
				"main", "NeuralRendering::AdaptiveHandoffCS"))
				return false;

			if (!adaptiveHandoffCB) {
				D3D11_BUFFER_DESC bufferDesc{};
				bufferDesc.ByteWidth = sizeof(AdaptiveHandoffConstants);
				bufferDesc.Usage = D3D11_USAGE_DEFAULT;
				bufferDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&bufferDesc, nullptr, adaptiveHandoffCB.GetAddressOf())))
					return false;
				Util::SetResourceName(adaptiveHandoffCB.Get(), "NeuralRendering::AdaptiveHandoffCB");
			}

			if (!adaptiveHandoffSampler) {
				D3D11_SAMPLER_DESC samplerDesc{};
				samplerDesc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
				samplerDesc.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
				samplerDesc.MinLOD = 0.0f;
				samplerDesc.MaxLOD = std::numeric_limits<float>::max();
				if (FAILED(device->CreateSamplerState(&samplerDesc, adaptiveHandoffSampler.GetAddressOf())))
					return false;
				Util::SetResourceName(adaptiveHandoffSampler.Get(), "NeuralRendering::AdaptiveHandoffSampler");
			}
			return true;
		}

		bool EnsureAdaptiveHandoffTexture(ID3D11Device* device, const D3D11_TEXTURE2D_DESC& sourceDesc,
			HandoffTexture& texture, const char* name)
		{
			if (!device || sourceDesc.Width == 0 || sourceDesc.Height == 0 || !name)
				return false;

			D3D11_TEXTURE2D_DESC desc = MakeSharedDesc(sourceDesc, sourceDesc.Width, sourceDesc.Height,
				D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS);
			HandoffTexture replacement;
			if (FAILED(device->CreateTexture2D(&desc, nullptr, replacement.resource.GetAddressOf())) ||
				FAILED(device->CreateShaderResourceView(replacement.resource.Get(), nullptr, replacement.srv.GetAddressOf())) ||
				FAILED(device->CreateUnorderedAccessView(replacement.resource.Get(), nullptr, replacement.uav.GetAddressOf())))
				return false;
			Util::SetResourceName(replacement.resource.Get(), name);
			Util::SetResourceName(replacement.srv.Get(), (std::string(name) + " SRV").c_str());
			Util::SetResourceName(replacement.uav.Get(), (std::string(name) + " UAV").c_str());
			texture = std::move(replacement);
			return true;
		}

		bool EnsureAdaptiveHandoffResources(ID3D11Device* device, std::uint32_t eyeIndex, EyeResources& eye)
		{
			if (!device || !eye.sharedResourcesValid || !eye.color.resource11 || !eye.depth.resource11 ||
				eye.colorWidth == 0 || eye.colorHeight == 0 || eye.guideWidth == 0 || eye.guideHeight == 0)
				return false;

			auto& handoff = eye.handoff;
			const bool matches = handoff.resourceWidth == eye.sharedColorWidth &&
					handoff.resourceHeight == eye.sharedColorHeight &&
					handoff.resourceGuideWidth == eye.sharedGuideWidth &&
					handoff.resourceGuideHeight == eye.sharedGuideHeight &&
					handoff.color[0].resource && handoff.color[0].srv && handoff.color[0].uav &&
					handoff.color[1].resource && handoff.color[1].srv && handoff.color[1].uav &&
					handoff.depth.resource && handoff.depth.srv && handoff.depth.uav;
				if (matches) {
					return true;
				}

			const std::string suffix = eyeIndex == 0 ? "Left" : "Right";
			D3D11_TEXTURE2D_DESC colorDesc = eye.color.desc;
			D3D11_TEXTURE2D_DESC guideDesc = eye.depth.desc;
			HandoffEyeState replacement;
			if (!EnsureAdaptiveHandoffTexture(device, colorDesc, replacement.color[0],
				("NeuralRendering::AdaptiveHandoffColor" + suffix + "A").c_str()) ||
				!EnsureAdaptiveHandoffTexture(device, colorDesc, replacement.color[1],
				("NeuralRendering::AdaptiveHandoffColor" + suffix + "B").c_str()) ||
				!EnsureAdaptiveHandoffTexture(device, guideDesc, replacement.depth,
				("NeuralRendering::AdaptiveHandoffDepth" + suffix).c_str()))
				return false;
			replacement.width = eye.colorWidth;
			replacement.height = eye.colorHeight;
			replacement.guideWidth = eye.guideWidth;
			replacement.guideHeight = eye.guideHeight;
			replacement.resourceWidth = eye.sharedColorWidth;
			replacement.resourceHeight = eye.sharedColorHeight;
			replacement.resourceGuideWidth = eye.sharedGuideWidth;
			replacement.resourceGuideHeight = eye.sharedGuideHeight;
			handoff = std::move(replacement);
			return true;
		}

		bool DispatchAdaptiveHandoff(ID3D11Device* device, ID3D11DeviceContext* context,
			const EyeResources& eye, HandoffEyeState& handoff,
			ID3D11ShaderResourceView* currentSRV, std::uint32_t previousIndex, std::uint32_t targetIndex,
			float motionVectorScaleX, float motionVectorScaleY, const Tuning& tuning)
		{
			if (!EnsureAdaptiveHandoffShaders(device) || !context || !currentSRV ||
				previousIndex >= handoff.color.size() || targetIndex >= handoff.color.size() ||
				!handoff.color[previousIndex].srv || !handoff.color[targetIndex].uav ||
				!eye.depth.srv11 || !handoff.depth.srv || !eye.motionVectors.srv11)
				return false;
			CS_GPU_PASS("NeuralRendering::AdaptiveHandoff");
			AdaptiveHandoffConstants constants{
				.colorWidth = handoff.width,
				.colorHeight = handoff.height,
				.guideWidth = handoff.guideWidth,
				.guideHeight = handoff.guideHeight,
				.motionScaleX = motionVectorScaleX,
				.motionScaleY = motionVectorScaleY,
				.blendAlpha = std::clamp(tuning.adaptiveHandoffAlpha, 0.0f, 1.0f),
				.depthThreshold = std::clamp(tuning.adaptiveDepthThreshold, 0.0f, 1.0f),
				.historyValid = handoff.valid ? 1u : 0u,
				.useDepth = 1u,
			};
			context->UpdateSubresource(adaptiveHandoffCB.Get(), 0, nullptr, &constants, 0, 0);
			ID3D11ShaderResourceView* sources[] = {
				currentSRV,
				handoff.color[previousIndex].srv.Get(),
				eye.depth.srv11.Get(),
				handoff.depth.srv.Get(),
				eye.motionVectors.srv11.Get(),
			};
			ID3D11UnorderedAccessView* target = handoff.color[targetIndex].uav.Get();
			ID3D11Buffer* constantBuffer = adaptiveHandoffCB.Get();
			ID3D11SamplerState* sampler = adaptiveHandoffSampler.Get();
			context->CSSetShader(adaptiveHandoffCS.get(), nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &constantBuffer);
			context->CSSetShaderResources(0, static_cast<UINT>(std::size(sources)), sources);
			context->CSSetUnorderedAccessViews(0, 1, &target, nullptr);
			context->CSSetSamplers(0, 1, &sampler);
			context->Dispatch((handoff.width + 7) / 8, (handoff.height + 7) / 8, 1);
			std::array<ID3D11ShaderResourceView*, 5> nullSources{};
			ID3D11UnorderedAccessView* nullTarget = nullptr;
			ID3D11Buffer* nullBuffer = nullptr;
			ID3D11SamplerState* nullSampler = nullptr;
			context->CSSetShaderResources(0, static_cast<UINT>(nullSources.size()), nullSources.data());
			context->CSSetUnorderedAccessViews(0, 1, &nullTarget, nullptr);
			context->CSSetConstantBuffers(0, 1, &nullBuffer);
			context->CSSetSamplers(0, 1, &nullSampler);
			context->CSSetShader(nullptr, nullptr, 0);
			return true;
		}

		ID3D11Resource* ApplyAdaptiveHandoff(ID3D11Device* device, ID3D11DeviceContext* context,
			std::uint32_t eyeIndex, EyeResources& eye, ID3D11Resource* currentOutput, ID3D11ShaderResourceView* currentSRV,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			float motionVectorScaleX, float motionVectorScaleY,
			std::uint32_t regionX, std::uint32_t regionY, const Tuning& tuning)
		{
			if (!currentOutput || !tuning.adaptiveResolution) {
				eye.handoff.valid = false;
				return currentOutput;
			}
			if (!EnsureAdaptiveHandoffResources(device, eyeIndex, eye))
				return currentOutput;

			auto& handoff = eye.handoff;
			const bool regionChanged = handoff.valid &&
				(handoff.regionX != regionX || handoff.regionY != regionY ||
					handoff.width != colorWidth || handoff.height != colorHeight ||
					handoff.guideWidth != guideWidth || handoff.guideHeight != guideHeight);
			if (regionChanged)
				handoff.valid = false;
			handoff.width = colorWidth;
			handoff.height = colorHeight;
			handoff.guideWidth = guideWidth;
			handoff.guideHeight = guideHeight;

			if (!handoff.valid) {
				context->CopyResource(handoff.color[0].resource.Get(), currentOutput);
				context->CopyResource(handoff.depth.resource.Get(), eye.depth.resource11.Get());
				handoff.historyIndex = 0;
				handoff.regionX = regionX;
				handoff.regionY = regionY;
				handoff.valid = true;
				return currentOutput;
			}

			const std::uint32_t previousIndex = handoff.historyIndex;
			const std::uint32_t targetIndex = 1u - previousIndex;
			if (tuning.adaptiveHandoffAlpha < 0.999f &&
				DispatchAdaptiveHandoff(device, context, eye, handoff, currentSRV,
					previousIndex, targetIndex, motionVectorScaleX, motionVectorScaleY, tuning)) {
				context->CopyResource(handoff.depth.resource.Get(), eye.depth.resource11.Get());
				handoff.historyIndex = targetIndex;
				return handoff.color[targetIndex].resource.Get();
			}

			context->CopyResource(handoff.color[targetIndex].resource.Get(), currentOutput);
			context->CopyResource(handoff.depth.resource.Get(), eye.depth.resource11.Get());
			handoff.historyIndex = targetIndex;
			return currentOutput;
		}

		void ClearModelResolutionBindings(ID3D11DeviceContext* context, UINT sourceCount)
		{
			std::array<ID3D11ShaderResourceView*, 3> nullSources{};
			ID3D11UnorderedAccessView* nullTarget = nullptr;
			ID3D11Buffer* nullBuffer = nullptr;
			ID3D11SamplerState* nullSampler = nullptr;
			context->CSSetShaderResources(0, sourceCount, nullSources.data());
			context->CSSetUnorderedAccessViews(0, 1, &nullTarget, nullptr);
			context->CSSetConstantBuffers(0, 1, &nullBuffer);
			context->CSSetSamplers(0, 1, &nullSampler);
			context->CSSetShader(nullptr, nullptr, 0);
		}

		static bool IsR32DepthFormat(DXGI_FORMAT format)
		{
			return format == DXGI_FORMAT_R32_TYPELESS || format == DXGI_FORMAT_R32_FLOAT;
		}

		// Copies this eye's guide region into the shared Feature 18 guides. A 32-bit
		// float depth source (the VR per-eye intermediates) is copied directly, which
		// also supports the NR-only coverage offset; other depth formats keep the
		// conversion dispatch and must start at the origin.
		struct GuideAlignmentConstants
		{
			std::array<std::uint32_t, 2> extent{}, sourceOffset{};
			std::array<float, 2> scale{}, offset{};
		};
		static_assert(sizeof(GuideAlignmentConstants) == 32);

		bool AlignStereoGuides(ID3D11DeviceContext* context, const StereoEyeInput& input,
			EyeResources& eye, std::uint32_t width, std::uint32_t height)
		{
			auto* device = globals::d3d::device;
			auto* shader = alignGuidesCS.Get(L"Data\\Shaders\\Upscaling\\NeuralRendering\\AlignGuidesCS.hlsl", {},
				"cs_5_0", "main", "NeuralRendering::AlignGuides");
			if (!device || !shader || !input.depthSRV) return false;
			if (!alignGuidesCB) {
				D3D11_BUFFER_DESC desc{};
				desc.ByteWidth = sizeof(GuideAlignmentConstants);
				desc.Usage = D3D11_USAGE_DEFAULT;
				desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&desc, nullptr, alignGuidesCB.GetAddressOf()))) return false;
				Util::SetResourceName(alignGuidesCB.Get(), "NeuralRendering::GuideAlignmentCB");
			}
			if (eye.alignmentMotionSource.Get() != input.motionVectors || !eye.alignmentMotionSRV) {
				eye.alignmentMotionSRV.Reset();
				if (FAILED(device->CreateShaderResourceView(input.motionVectors, nullptr, eye.alignmentMotionSRV.GetAddressOf()))) return false;
				eye.alignmentMotionSource = input.motionVectors;
				Util::SetResourceName(eye.alignmentMotionSRV.Get(), "NeuralRendering::AlignmentMotion SRV");
			}
			CS_GPU_PASS("NeuralRendering::AlignGuides");
			const GuideAlignmentConstants data{ { width, height }, { input.guideSourceX, input.guideSourceY }, input.guideScale, input.guideOffset };
			context->UpdateSubresource(alignGuidesCB.Get(), 0, nullptr, &data, 0, 0);
			ID3D11Buffer* cb = alignGuidesCB.Get();
			ID3D11ShaderResourceView* sources[]{ input.depthSRV, eye.alignmentMotionSRV.Get() };
			ID3D11UnorderedAccessView* targets[]{ eye.depth.uav11.Get(), eye.motionVectors.uav11.Get() };
			context->CSSetShader(shader, nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &cb);
			context->CSSetShaderResources(0, 2, sources);
			context->CSSetUnorderedAccessViews(0, 2, targets, nullptr);
			context->Dispatch((width + 7) / 8, (height + 7) / 8, 1);
			ID3D11ShaderResourceView* nullSources[2]{};
			ID3D11UnorderedAccessView* nullTargets[2]{};
			context->CSSetShaderResources(0, 2, nullSources);
			context->CSSetUnorderedAccessViews(0, 2, nullTargets, nullptr);
			ID3D11Buffer* nullCB = nullptr;
			context->CSSetConstantBuffers(0, 1, &nullCB);
			context->CSSetShader(nullptr, nullptr, 0);
			return true;
		}

		bool CopyStereoGuides(ID3D11DeviceContext* context, const StereoEyeInput& input, EyeResources& eye,
			std::uint32_t guideWidth, std::uint32_t guideHeight)
		{
			D3D11_TEXTURE2D_DESC depthDesc{}, motionDesc{};
			if (!GetTextureDesc(input.depth, depthDesc) || !GetTextureDesc(input.motionVectors, motionDesc))
				return false;
			const std::uint64_t right = static_cast<std::uint64_t>(input.guideSourceX) + guideWidth;
			const std::uint64_t bottom = static_cast<std::uint64_t>(input.guideSourceY) + guideHeight;
			if (right > depthDesc.Width || bottom > depthDesc.Height || right > motionDesc.Width || bottom > motionDesc.Height)
				return false;
			if (input.guideScale != std::array<float, 2>{ 1, 1 } || input.guideOffset != std::array<float, 2>{})
				return AlignStereoGuides(context, input, eye, guideWidth, guideHeight);
			const D3D11_BOX box{ input.guideSourceX, input.guideSourceY, 0,
				static_cast<UINT>(right), static_cast<UINT>(bottom), 1 };
			if (IsR32DepthFormat(depthDesc.Format) && depthDesc.SampleDesc.Count == 1) {
				context->CopySubresourceRegion(eye.depth.resource11.Get(), 0, 0, 0, 0, input.depth, 0, &box);
			} else {
				if (input.guideSourceX != 0 || input.guideSourceY != 0)
					return false;
				if (!CopyDepthGuide(context, input.depthSRV, eye.depth.uav11.Get(), guideWidth, guideHeight))
					return false;
			}
			context->CopySubresourceRegion(eye.motionVectors.resource11.Get(), 0, 0, 0, 0, input.motionVectors, 0, &box);
			return true;
		}

		bool CopyDepthGuide(ID3D11DeviceContext* context, ID3D11ShaderResourceView* source,
			ID3D11UnorderedAccessView* destination, std::uint32_t width, std::uint32_t height)
		{
			auto* shader = copyDepthGuideCS.Get(
				L"Data\\Shaders\\Upscaling\\NeuralRendering\\CopyDepthGuideCS.hlsl", {}, "cs_5_0",
				"main", "NeuralRendering::CopyDepthGuideCS");
			if (!shader || !destination)
				return false;
			context->CSSetShader(shader, nullptr, 0);
			context->CSSetShaderResources(0, 1, &source);
			context->CSSetUnorderedAccessViews(0, 1, &destination, nullptr);
			context->Dispatch((width + 7) / 8, (height + 7) / 8, 1);
			ID3D11ShaderResourceView* nullSRV = nullptr;
			ID3D11UnorderedAccessView* nullUAV = nullptr;
			context->CSSetShaderResources(0, 1, &nullSRV);
			context->CSSetUnorderedAccessViews(0, 1, &nullUAV, nullptr);
			context->CSSetShader(nullptr, nullptr, 0);
			return true;
		}

		bool InitializeInterop(ID3D11Device* device, ID3D11DeviceContext* context)
		{
			Microsoft::WRL::ComPtr<IDXGIDevice> dxgiDevice;
			Microsoft::WRL::ComPtr<IDXGIAdapter> adapter;
			HRESULT result = device->QueryInterface(IID_PPV_ARGS(&dxgiDevice));
			if (SUCCEEDED(result)) result = dxgiDevice->GetAdapter(&adapter);
			if (FAILED(result) || !interop.Initialize(adapter.Get(), device, context))
				return LatchFailure("D3D12 interop initialization", FAILED(result) ? result : interop.LastError());
			return true;
		}

		bool InitializeRuntime()
		{
			auto& runtime = Runtime::Instance();
			if (!runtime.Probe() || !runtime.Initialize(interop.Device()))
				return LatchFailure("runtime initialization", static_cast<HRESULT>(runtime.NgxResult()));
			logger::info("[DLSSNR] initialized version={} appId=0x{:08X} api=0x{:X}",
				runtime.Version(), runtime.ApplicationId(), runtime.ApiVersion());
			return true;
		}

		void ResetAdaptivePrewarmState()
		{
			adaptivePrewarmTier = UINT32_MAX;
			adaptivePrewarmResolution = 0;
			adaptivePrewarmDirection = 0;
			adaptivePrewarmPassCount = 0;
			adaptivePrewarmStableFrames = 0;
			adaptivePrewarmCandidate = 0;
			adaptivePrewarmEye = 0;
			adaptivePrewarmColorWidth = 0;
			adaptivePrewarmColorHeight = 0;
			adaptivePrewarmGuideWidth = 0;
			adaptivePrewarmGuideHeight = 0;
			adaptivePrewarmResourcesReady.fill(false);
			adaptivePrewarmRejected.fill(false);
		}

		AdaptivePrewarmWork PrepareAdjacentPrewarmResources(ID3D11Device* device,
			std::uint32_t tierIndex, std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight, std::uint32_t passCount,
			std::uint32_t modelResolution, std::uint32_t stableColorWidth, std::uint32_t stableColorHeight,
			const Tuning& tuning)
		{
			// Prewarming is deliberately limited to the single-pass adaptive path.
			// Multi-pass and recovery paths retain their smaller resource budget and
			// continue to create only the selected tier on demand.
			if (!device || !tuning.adaptiveResolution || passCount != 1 || recoveryAttempted ||
				tuning.adaptiveHandoffAlpha < 0.999f || tuning.adaptivePrewarmDirection == 0 ||
				tierIndex >= kResolutionTierCount)
			{
				ResetAdaptivePrewarmState();
				return {};
			}

			if (adaptivePrewarmTier != tierIndex || adaptivePrewarmResolution != modelResolution ||
				adaptivePrewarmDirection != tuning.adaptivePrewarmDirection ||
				adaptivePrewarmPassCount != passCount || adaptivePrewarmColorWidth != stableColorWidth ||
				adaptivePrewarmColorHeight != stableColorHeight || adaptivePrewarmGuideWidth != guideWidth ||
				adaptivePrewarmGuideHeight != guideHeight)
			{
				ResetAdaptivePrewarmState();
				adaptivePrewarmTier = tierIndex;
				adaptivePrewarmResolution = modelResolution;
				adaptivePrewarmDirection = tuning.adaptivePrewarmDirection;
				adaptivePrewarmPassCount = passCount;
				adaptivePrewarmColorWidth = stableColorWidth;
				adaptivePrewarmColorHeight = stableColorHeight;
				adaptivePrewarmGuideWidth = guideWidth;
				adaptivePrewarmGuideHeight = guideHeight;
			}

			++adaptivePrewarmStableFrames;
			if (adaptivePrewarmStableFrames < 8)
				return {};

			const std::array<std::uint32_t, 2> candidates{
				tuning.adaptivePrewarmDirection < 0 && tierIndex + 1 < kResolutionTierCount ? tierIndex + 1 : UINT32_MAX,
				tuning.adaptivePrewarmDirection > 0 && tierIndex > 0 ? tierIndex - 1 : UINT32_MAX,
			};
			while (adaptivePrewarmCandidate < candidates.size()) {
				const auto candidate = candidates[adaptivePrewarmCandidate];
				if (candidate == UINT32_MAX ||
					kResolutionTiers[candidate] < kAdaptiveMinimumResolution ||
					(kResolutionTiers[candidate] > tuning.adaptiveMemoryCeiling && candidate < tierIndex) ||
					adaptivePrewarmRejected[adaptivePrewarmCandidate]) {
					++adaptivePrewarmCandidate;
					adaptivePrewarmEye = 0;
					continue;
				}
				if (!adaptivePrewarmResourcesReady[adaptivePrewarmCandidate]) {
					const auto candidateResolution = kResolutionTiers[candidate];
					const auto candidateModelWidth = ScaleDimension(colorWidth, candidateResolution);
					const auto candidateModelHeight = ScaleDimension(colorHeight, candidateResolution);
					bool resourcesReady = true;
					for (std::uint32_t eyeIndex = 0; eyeIndex < eyes.size(); ++eyeIndex) {
						if (!EnsureTierResources(device, eyeIndex, eyes[eyeIndex], candidate,
							candidateModelWidth, candidateModelHeight, passCount, candidateResolution, 100u,
							stableColorWidth, stableColorHeight)) {
							resourcesReady = false;
							break;
						}
					}
					if (!resourcesReady) {
						logger::warn("[DLSSNR] adaptive prewarm resource allocation failed tier={} resolution={}%; continuing with on-demand creation",
							candidate, candidateResolution);
						adaptivePrewarmRejected[adaptivePrewarmCandidate] = true;
						++adaptivePrewarmCandidate;
						adaptivePrewarmEye = 0;
						continue;
					}
					adaptivePrewarmResourcesReady[adaptivePrewarmCandidate] = true;
				}
				if (adaptivePrewarmEye >= eyes.size()) {
					++adaptivePrewarmCandidate;
					adaptivePrewarmEye = 0;
					adaptivePrewarmResourcesReady[adaptivePrewarmCandidate - 1] = false;
					continue;
				}
				return { true, adaptivePrewarmCandidate, candidate, adaptivePrewarmEye };
			}
			return {};
		}

		void ExecuteAdaptivePrewarm(ID3D12GraphicsCommandList* commandList, const AdaptivePrewarmWork& work,
			std::uint32_t stableGuideWidth, std::uint32_t stableGuideHeight,
			std::uint32_t stableColorWidth, std::uint32_t stableColorHeight)
		{
			if (!work.valid || !commandList || work.tierIndex >= kResolutionTierCount || work.eyeIndex >= eyes.size())
				return;
			const auto resolution = kResolutionTiers[work.tierIndex];
			const auto outputWidth = ScaleDimension(stableColorWidth, resolution);
			const auto outputHeight = ScaleDimension(stableColorHeight, resolution);
			const auto inputWidth = resolution == 100 ? stableColorWidth : outputWidth;
			const auto inputHeight = resolution == 100 ? stableColorHeight : outputHeight;
			Feature18GuideContract guide{};
			guide.colorWidth = inputWidth;
			guide.colorHeight = inputHeight;
			guide.depthWidth = stableGuideWidth;
			guide.depthHeight = stableGuideHeight;
			guide.motionWidth = stableGuideWidth;
			guide.motionHeight = stableGuideHeight;
			guide.outputWidth = outputWidth;
			guide.outputHeight = outputHeight;
			guide.creationInputWidth = inputWidth;
			guide.creationInputHeight = inputHeight;
			guide.creationOutputWidth = outputWidth;
			guide.creationOutputHeight = outputHeight;
			guide.motionVectorsLowResolution = stableGuideWidth <= inputWidth && stableGuideHeight <= inputHeight;
			const auto slot = FeatureSlot(work.eyeIndex, work.tierIndex, 0);
			bool succeeded = Runtime::Instance().HasFeature(slot);
			if (!succeeded)
				succeeded = Runtime::Instance().PrewarmFeature(commandList, slot, guide);
			if (!succeeded) {
				logger::warn("[DLSSNR] adaptive prewarm Feature 18 failed eye={} tier={} resolution={}%; continuing with on-demand creation result=0x{:08X}",
					work.eyeIndex, work.tierIndex, resolution, Runtime::Instance().NgxResult());
				adaptivePrewarmRejected[work.candidateIndex] = true;
				adaptivePrewarmEye = static_cast<std::uint32_t>(eyes.size());
			} else {
				++adaptivePrewarmEye;
			}
			if (adaptivePrewarmEye >= eyes.size() || adaptivePrewarmRejected[work.candidateIndex]) {
				++adaptivePrewarmCandidate;
				adaptivePrewarmEye = 0;
				adaptivePrewarmResourcesReady[work.candidateIndex] = false;
			}
		}

		bool EnsureTierResources(ID3D11Device* device, std::uint32_t eyeIndex, EyeResources& eye,
			std::uint32_t tierIndex, std::uint32_t modelWidth, std::uint32_t modelHeight,
			std::uint32_t passCount, std::uint32_t modelResolution, std::uint32_t secondPassCoverage,
			std::uint32_t resourceColorWidth, std::uint32_t resourceColorHeight)
		{
			if (!device || eyeIndex >= eyes.size() || tierIndex >= kResolutionTierCount ||
				modelWidth == 0 || modelHeight == 0 || passCount == 0 || passCount > kCascadePassCount ||
				resourceColorWidth == 0 || resourceColorHeight == 0 || !eye.sharedResourcesValid)
				return false;

			// The valid crop can be smaller than the stable backing resource even
			// at the native NR tier. Tier identity, not the transient crop extent,
			// decides whether a model-input resolve is required.
			const bool reducedResolution = modelResolution != 100;
			const bool multiPass = passCount > 1;
			const std::uint32_t pass2Coverage = multiPass ? std::clamp(secondPassCoverage, 50u, 100u) : 100u;
			const bool croppedSecondPass = multiPass && pass2Coverage < 100;
			const UINT sharedFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
			const auto resourceModelWidth = ScaleDimension(resourceColorWidth, modelResolution);
			const auto resourceModelHeight = ScaleDimension(resourceColorHeight, modelResolution);
			const auto modelInputDesc = MakeSharedDesc(eye.color.desc, resourceModelWidth, resourceModelHeight, sharedFlags);
			const auto outputDesc = MakeSharedDesc(eye.color.desc, resourceModelWidth, resourceModelHeight, sharedFlags);
			const auto pass2OutputDesc = outputDesc;
			const auto resolvedDesc = MakeSharedDesc(eye.color.desc, resourceColorWidth, resourceColorHeight, sharedFlags);
			auto& tier = eye.tiers[tierIndex];
			const bool intermediatesMatch = !multiPass ||
				(Matches(tier.cascadeIntermediates[0], outputDesc) &&
				 (passCount < 3 || Matches(tier.cascadeIntermediates[1], outputDesc)));
			const bool resourcesMatch = tier.modelResolution == modelResolution && tier.passCount == passCount &&
				tier.reducedResolution == reducedResolution &&
				(!reducedResolution || Matches(tier.modelInput, modelInputDesc)) &&
				Matches(tier.output, outputDesc) && intermediatesMatch &&
				(!reducedResolution || (MatchesResolved(tier.resolved, resolvedDesc) && tier.resolvedSRV && tier.resolvedUAV));
			if (resourcesMatch) {
				// At 100% P2 the normal full-size final output is used directly. If the
				// user later selects <100%, allocate only a full-size P2 scratch; do not
				// rebuild the tier or retire otherwise-compatible Feature18 histories.
				if (croppedSecondPass && !Matches(tier.secondPassOutput, pass2OutputDesc)) {
					if (tier.secondPassOutput.resource11 && !interop.WaitForIdle())
						return false;
					tier.secondPassOutput = {};
					if (!interop.CreateSharedTexture(pass2OutputDesc, tier.secondPassOutput,
						("NeuralRendering::SecondPassOutput" + std::to_string(eyeIndex) + "_" + std::to_string(modelResolution)).c_str()))
						return false;
				}
				return true;
			}

			if (tier.output.resource11 || tier.secondPassOutput.resource11 || tier.modelInput.resource11 || tier.resolved) {
				if (!interop.WaitForIdle())
					return false;
				for (std::uint32_t passIndex = 0; passIndex < kCascadePassCount; ++passIndex)
					Runtime::Instance().ResetFeature(FeatureSlot(eyeIndex, tierIndex, passIndex));
			}
			tier = {};
			const std::string suffix = eyeIndex == 0 ? "Left" : "Right";
			const std::string tierSuffix = suffix + "_" + std::to_string(modelResolution);
			if ((reducedResolution && !interop.CreateSharedTexture(modelInputDesc, tier.modelInput,
				("NeuralRendering::ModelInput" + tierSuffix).c_str())) ||
				(multiPass && !interop.CreateSharedTexture(outputDesc, tier.cascadeIntermediates[0],
				("NeuralRendering::CascadeIntermediate0" + tierSuffix).c_str())) ||
				(passCount > 2 && !interop.CreateSharedTexture(outputDesc, tier.cascadeIntermediates[1],
				("NeuralRendering::CascadeIntermediate1" + tierSuffix).c_str())) ||
				(croppedSecondPass && !interop.CreateSharedTexture(pass2OutputDesc, tier.secondPassOutput,
				("NeuralRendering::SecondPassOutput" + tierSuffix).c_str())) ||
				!interop.CreateSharedTexture(outputDesc, tier.output, ("NeuralRendering::Output" + tierSuffix).c_str()))
				return false;
			if (reducedResolution) {
				if (FAILED(device->CreateTexture2D(&resolvedDesc, nullptr, tier.resolved.GetAddressOf())) ||
					FAILED(device->CreateShaderResourceView(tier.resolved.Get(), nullptr, tier.resolvedSRV.GetAddressOf())) ||
					FAILED(device->CreateUnorderedAccessView(tier.resolved.Get(), nullptr, tier.resolvedUAV.GetAddressOf())))
					return false;
				Util::SetResourceName(tier.resolved.Get(), ("NeuralRendering::Resolved" + tierSuffix).c_str());
				Util::SetResourceName(tier.resolvedSRV.Get(), ("NeuralRendering::Resolved" + tierSuffix + " SRV").c_str());
				Util::SetResourceName(tier.resolvedUAV.Get(), ("NeuralRendering::Resolved" + tierSuffix + " UAV").c_str());
			}
			tier.modelResolution = modelResolution;
			tier.passCount = passCount;
			tier.reducedResolution = reducedResolution;
			resetPending[eyeIndex][tierIndex] = true;
			const float modelAreaPercent = 100.0f *
				(static_cast<float>(modelWidth) / static_cast<float>(eye.colorWidth)) *
				(static_cast<float>(modelHeight) / static_cast<float>(eye.colorHeight));
			const auto resolveSettings = GetModelResolveSettings(modelResolution);
			logger::info("[DLSSNR] resources eye={} tier={} guides={}x{} color={}x{} model={}x{} modelPercent={}% modelArea={:.1f}% passes={} resolve=transfer:{:.2f},colour:{:.2f},maxRatio:{:.2f},residual:{:.2f}",
				eyeIndex, modelResolution, eye.guideWidth, eye.guideHeight, eye.colorWidth, eye.colorHeight,
				modelWidth, modelHeight, modelResolution, modelAreaPercent, passCount,
				resolveSettings.transferStrength, resolveSettings.colourStrength,
				resolveSettings.maxRatio, resolveSettings.residualStrength);
			return true;
		}

		bool EnsureResources(ID3D11Device* device, std::uint32_t eyeIndex, ID3D11Resource* color, ID3D11Resource* depth,
			ID3D11Resource* motionVectors, std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t modelWidth, std::uint32_t modelHeight, std::uint32_t passCount,
			std::uint32_t modelResolution, std::uint32_t secondPassCoverage, bool prewarmAdaptive,
			const StereoResourceEnvelope& resourceEnvelope, std::uint32_t memoryCeiling)
		{
			if (!device || eyeIndex >= eyes.size() || guideWidth == 0 || guideHeight == 0 ||
				colorWidth == 0 || colorHeight == 0 || modelWidth == 0 || modelHeight == 0 ||
				passCount == 0 || passCount > kCascadePassCount)
				return false;
			if (resourceEnvelope.enabled && (!resourceEnvelope.IsValid() ||
				resourceEnvelope.guideWidth < guideWidth || resourceEnvelope.guideHeight < guideHeight ||
				resourceEnvelope.colorWidth < colorWidth || resourceEnvelope.colorHeight < colorHeight))
				return false;
			D3D11_TEXTURE2D_DESC colorSource{}, depthSource{}, motionSource{};
			if (!GetTextureDesc(color, colorSource) || !GetTextureDesc(depth, depthSource) ||
				!GetTextureDesc(motionVectors, motionSource))
				return false;

			const bool useEnvelope = resourceEnvelope.IsValid();
			const std::uint32_t sharedColorWidth = useEnvelope ? resourceEnvelope.colorWidth : colorWidth;
			const std::uint32_t sharedColorHeight = useEnvelope ? resourceEnvelope.colorHeight : colorHeight;
			const std::uint32_t sharedGuideWidth = useEnvelope ? resourceEnvelope.guideWidth : guideWidth;
			const std::uint32_t sharedGuideHeight = useEnvelope ? resourceEnvelope.guideHeight : guideHeight;
			if (depthSource.Width < sharedGuideWidth || depthSource.Height < sharedGuideHeight ||
				motionSource.Width < sharedGuideWidth || motionSource.Height < sharedGuideHeight)
				return false;

			const UINT sharedFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
			const auto colorDesc = MakeSharedDesc(colorSource, sharedColorWidth, sharedColorHeight, sharedFlags);
			auto depthDesc = MakeSharedDesc(depthSource, sharedGuideWidth, sharedGuideHeight, sharedFlags);
			depthDesc.Format = DXGI_FORMAT_R32_FLOAT;
			const auto motionDesc = MakeSharedDesc(motionSource, sharedGuideWidth, sharedGuideHeight, sharedFlags);
			auto& eye = eyes[eyeIndex];
			const bool sharedMatch = eye.sharedResourcesValid && eye.sharedColorWidth == sharedColorWidth &&
				eye.sharedColorHeight == sharedColorHeight && eye.sharedGuideWidth == sharedGuideWidth &&
				eye.sharedGuideHeight == sharedGuideHeight && Matches(eye.color, colorDesc) &&
				Matches(eye.depth, depthDesc) && Matches(eye.motionVectors, motionDesc);
			if (!sharedMatch) {
				if (eye.sharedResourcesValid) {
					if (!interop.WaitForIdle())
						return false;
					for (std::uint32_t oldTier = 0; oldTier < kResolutionTierCount; ++oldTier)
						for (std::uint32_t passIndex = 0; passIndex < kCascadePassCount; ++passIndex)
							Runtime::Instance().ResetFeature(FeatureSlot(eyeIndex, oldTier, passIndex));
				}
				ResetAdaptivePrewarmState();
				eye = {};
				const std::string suffix = eyeIndex == 0 ? "Left" : "Right";
				if (!interop.CreateSharedTexture(colorDesc, eye.color, ("NeuralRendering::Color" + suffix).c_str()) ||
					!interop.CreateSharedTexture(depthDesc, eye.depth, ("NeuralRendering::Depth" + suffix).c_str()) ||
					!interop.CreateSharedTexture(motionDesc, eye.motionVectors, ("NeuralRendering::Motion" + suffix).c_str()))
					return false;
				eye.sharedColorWidth = sharedColorWidth;
				eye.sharedColorHeight = sharedColorHeight;
				eye.sharedGuideWidth = sharedGuideWidth;
				eye.sharedGuideHeight = sharedGuideHeight;
				eye.sharedResourcesValid = true;
				resetPending[eyeIndex].fill(true);
			}

			// The resource dimensions may be stable at the envelope while these
			// fields track the current valid crop. Keep them current even when the
			// backing resources are reused; tier selection depends on this distinction.
			eye.colorWidth = colorWidth;
			eye.colorHeight = colorHeight;
			eye.guideWidth = guideWidth;
			eye.guideHeight = guideHeight;

			const auto tierIndex = ResolutionTierIndex(modelResolution);
			const bool retainAdjacentTiers = prewarmAdaptive && !recoveryAttempted && passCount == 1;
			const bool tierChanged = eye.residency.Select(tierIndex, retainAdjacentTiers);
			bool waited = false;
			for (std::uint32_t resident = 0; resident < kResolutionTierCount; ++resident) {
				const bool adjacent = resident + 1 == tierIndex ||
					(tierIndex + 1 < kResolutionTierCount && resident == tierIndex + 1);
				// Re-entry above the learned ceiling still needs the next lower tier to descend.
				const bool aboveMemoryCeiling = prewarmAdaptive && kResolutionTiers[resident] > memoryCeiling &&
					resident != tierIndex + 1;
				if (resident == tierIndex || (!aboveMemoryCeiling &&
					(eye.residency.Contains(resident) || (retainAdjacentTiers && adjacent))))
					continue;
				if (!eye.tiers[resident].output.resource11)
					continue;
				if (!waited && !interop.WaitForIdle())
					return false;
				waited = true;
				for (std::uint32_t pass = 0; pass < kCascadePassCount; ++pass)
					Runtime::Instance().ResetFeature(FeatureSlot(eyeIndex, resident, pass));
				eye.tiers[resident] = {};
				resetPending[eyeIndex][resident] = true;
			}
			if (!EnsureTierResources(device, eyeIndex, eye, tierIndex, modelWidth, modelHeight, passCount, modelResolution,
				secondPassCoverage, sharedColorWidth, sharedColorHeight))
				return false;
			if (tierChanged)
				resetPending[eyeIndex][tierIndex] = true;
			const std::uint32_t resourceModelWidth = useEnvelope ?
				ScaleDimension(sharedColorWidth, modelResolution) : modelWidth;
			const std::uint32_t resourceModelHeight = useEnvelope ?
				ScaleDimension(sharedColorHeight, modelResolution) : modelHeight;
			const std::uint32_t featureInputWidth = modelResolution == 100 ? sharedColorWidth : resourceModelWidth;
			const std::uint32_t featureInputHeight = modelResolution == 100 ? sharedColorHeight : resourceModelHeight;
			const std::uint32_t pass2Coverage = passCount > 1 ? std::clamp(secondPassCoverage, 50u, 100u) : 100u;
			for (std::uint32_t pass = 0; pass < passCount; ++pass) {
				const bool croppedPass2 = pass == 1 && pass2Coverage < 100;
				const std::uint32_t expectedInputWidth = pass == 0 ? featureInputWidth : resourceModelWidth;
				const std::uint32_t expectedInputHeight = pass == 0 ? featureInputHeight : resourceModelHeight;
				const std::uint32_t expectedOutputWidth = resourceModelWidth;
				const std::uint32_t expectedOutputHeight = resourceModelHeight;
				const std::uint32_t evalColorWidth = croppedPass2 ? ScaleDimension(resourceModelWidth, pass2Coverage) : expectedInputWidth;
				const std::uint32_t evalColorHeight = croppedPass2 ? ScaleDimension(resourceModelHeight, pass2Coverage) : expectedInputHeight;
				const std::uint32_t evalGuideWidth = croppedPass2 ? ScaleDimension(sharedGuideWidth, pass2Coverage) : sharedGuideWidth;
				const std::uint32_t evalGuideHeight = croppedPass2 ? ScaleDimension(sharedGuideHeight, pass2Coverage) : sharedGuideHeight;
				const bool lowResolutionMotion = evalGuideWidth <= evalColorWidth && evalGuideHeight <= evalColorHeight;
				const auto slot = FeatureSlot(eyeIndex, tierIndex, pass);
				if (!Runtime::Instance().NeedsRecreation(slot, expectedInputWidth, expectedInputHeight,
					expectedOutputWidth, expectedOutputHeight, lowResolutionMotion))
					continue;
				if (!waited && !interop.WaitForIdle())
					return false;
				waited = true;
				Runtime::Instance().ResetFeature(slot);
				resetPending[eyeIndex][tierIndex] = true;
			}
			return true;
		}

		struct SequentialCompositeConstants
		{
			std::uint32_t fullWidth = 0;
			std::uint32_t fullHeight = 0;
			std::uint32_t pass2OffsetX = 0;
			std::uint32_t pass2OffsetY = 0;
			std::uint32_t pass2Width = 0;
			std::uint32_t pass2Height = 0;
			std::uint32_t blendMode = 1;
			std::uint32_t maskMode = 1;
			std::uint32_t frameIndex = 0;
			float featherWidth = 64.0f;
			float ditherStrength = 1.0f;
			float falloffCurve = 1.0f;
			float pad0 = 0.0f;
			float pad1 = 0.0f;
			float pad2 = 0.0f;
			float pad3 = 0.0f;
		};
		static_assert(sizeof(SequentialCompositeConstants) == 64);

		bool EnsureSequentialCompositeResources(ID3D11Device* device)
		{
			if (!device)
				return false;
			if (!sequentialCompositeCS.Get(
				L"Data\\Shaders\\Upscaling\\NeuralRendering\\SequentialCompositeCS.hlsl", {},
				"cs_5_0", "main", "NeuralRendering::SequentialCompositeCS"))
				return false;
			if (!sequentialCompositeCB) {
				D3D11_BUFFER_DESC desc{};
				desc.ByteWidth = sizeof(SequentialCompositeConstants);
				desc.Usage = D3D11_USAGE_DEFAULT;
				desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&desc, nullptr, sequentialCompositeCB.GetAddressOf())))
					return false;
				Util::SetResourceName(sequentialCompositeCB.Get(), "NeuralRendering::SequentialCompositeCB");
			}
			return true;
		}

		void ClearSequentialCompositeBindings(ID3D11DeviceContext* context)
		{
			if (!context)
				return;
			ID3D11ShaderResourceView* nullSRVs[2]{};
			ID3D11UnorderedAccessView* nullUAV = nullptr;
			ID3D11Buffer* nullCB = nullptr;
			context->CSSetShaderResources(0, 2, nullSRVs);
			context->CSSetUnorderedAccessViews(0, 1, &nullUAV, nullptr);
			context->CSSetConstantBuffers(0, 1, &nullCB);
			context->CSSetShader(nullptr, nullptr, 0);
		}

		bool CompositeSequentialPass(ID3D11Device* device, ID3D11DeviceContext* context,
			TierResources& tier, std::uint32_t fullWidth, std::uint32_t fullHeight,
			std::uint32_t pass2Width, std::uint32_t pass2Height, const Tuning& tuning)
		{
			if (!device || !context || !fullWidth || !fullHeight || !pass2Width || !pass2Height ||
				pass2Width > fullWidth || pass2Height > fullHeight ||
				!tier.cascadeIntermediates[0].srv11 || !tier.secondPassOutput.srv11 || !tier.output.uav11 ||
				!EnsureSequentialCompositeResources(device))
				return false;

			SequentialCompositeConstants constants{};
			constants.fullWidth = fullWidth;
			constants.fullHeight = fullHeight;
			constants.pass2OffsetX = (fullWidth - pass2Width) / 2;
			constants.pass2OffsetY = (fullHeight - pass2Height) / 2;
			constants.pass2Width = pass2Width;
			constants.pass2Height = pass2Height;
			constants.blendMode = std::min(tuning.secondPass.blendMode, 2u);
			constants.maskMode = std::min(tuning.secondPass.maskMode, 1u);
			constants.frameIndex = globals::state ? static_cast<std::uint32_t>(globals::state->frameCount) : 0u;
			constants.featherWidth = std::clamp(tuning.secondPass.featherWidth, 2.0f, 128.0f);
			constants.ditherStrength = std::clamp(tuning.secondPass.ditherStrength, 0.0f, 2.0f);
			constants.falloffCurve = std::clamp(tuning.secondPass.falloffCurve, 0.5f, 2.0f);

			CS_GPU_PASS("NeuralRendering::SequentialComposite");
			context->UpdateSubresource(sequentialCompositeCB.Get(), 0, nullptr, &constants, 0, 0);
			ID3D11ShaderResourceView* sources[2]{
				tier.cascadeIntermediates[0].srv11.Get(), tier.secondPassOutput.srv11.Get() };
			ID3D11UnorderedAccessView* target = tier.output.uav11.Get();
			ID3D11Buffer* cb = sequentialCompositeCB.Get();
			context->CSSetShader(sequentialCompositeCS.get(), nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &cb);
			context->CSSetShaderResources(0, 2, sources);
			context->CSSetUnorderedAccessViews(0, 1, &target, nullptr);
			context->Dispatch((fullWidth + 7) / 8, (fullHeight + 7) / 8, 1);
			ClearSequentialCompositeBindings(context);
			return true;
		}

		enum class StereoAtlasResult
		{
			FallBack,
			Applied,
			Failed,
		};

		struct StereoAtlasPackConstants
		{
			std::uint32_t eyeWidth = 0;
			std::uint32_t eyeHeight = 0;
			std::uint32_t guardWidth = 0;
			std::uint32_t sourceOffsetX = 0;
			std::uint32_t sourceOffsetY = 0;
			std::uint32_t atlasWidth = 0;
			std::uint32_t atlasHeight = 0;
			std::uint32_t padding = 0;
		};
		static_assert(sizeof(StereoAtlasPackConstants) == 32);

		void ResetStereoAtlasFeatures()
		{
			ladderAtlasGeometry.valid = false;
			for (std::uint32_t tier = 0; tier < kResolutionTierCount; ++tier)
				for (std::uint32_t pass = 0; pass < kCascadePassCount; ++pass)
					Runtime::Instance().ResetFeature(AtlasFeatureSlot(tier, pass));
			stereoAtlasResetPending = true;
		}

		bool EnsureStereoAtlasPackResources(ID3D11Device* device)
		{
			if (!device)
				return false;
			if (!stereoAtlasColorPackCS.Get(L"Data\\Shaders\\Upscaling\\NeuralRendering\\StereoAtlasPackColorCS.hlsl", {},
				"cs_5_0", "main", "NeuralRendering::StereoAtlasPackColorCS") ||
				!stereoAtlasDepthPackCS.Get(L"Data\\Shaders\\Upscaling\\NeuralRendering\\StereoAtlasPackDepthCS.hlsl", {},
				"cs_5_0", "main", "NeuralRendering::StereoAtlasPackDepthCS") ||
				!stereoAtlasMotionPackCS.Get(L"Data\\Shaders\\Upscaling\\NeuralRendering\\StereoAtlasPackMotionCS.hlsl", {},
				"cs_5_0", "main", "NeuralRendering::StereoAtlasPackMotionCS"))
				return false;
			if (!stereoAtlasPackCB) {
				D3D11_BUFFER_DESC desc{};
				desc.ByteWidth = sizeof(StereoAtlasPackConstants);
				desc.Usage = D3D11_USAGE_DEFAULT;
				desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&desc, nullptr, stereoAtlasPackCB.GetAddressOf())))
					return false;
				Util::SetResourceName(stereoAtlasPackCB.Get(), "NeuralRendering::StereoAtlasPackCB");
			}
			return true;
		}

		bool DispatchStereoAtlasPack(ID3D11DeviceContext* context, ID3D11ComputeShader* shader,
			ID3D11ShaderResourceView* left, ID3D11ShaderResourceView* right, ID3D11UnorderedAccessView* target,
			std::uint32_t eyeWidth, std::uint32_t eyeHeight, std::uint32_t guardWidth,
			std::uint32_t sourceOffsetX, std::uint32_t sourceOffsetY)
		{
			if (!context || !shader || !left || !right || !target || !eyeWidth || !eyeHeight || !guardWidth)
				return false;
			StereoAtlasPackConstants constants{};
			constants.eyeWidth = eyeWidth;
			constants.eyeHeight = eyeHeight;
			constants.guardWidth = guardWidth;
			constants.sourceOffsetX = sourceOffsetX;
			constants.sourceOffsetY = sourceOffsetY;
			constants.atlasWidth = eyeWidth * 2 + guardWidth;
			constants.atlasHeight = eyeHeight;
			context->UpdateSubresource(stereoAtlasPackCB.Get(), 0, nullptr, &constants, 0, 0);
			ID3D11ShaderResourceView* sources[2]{ left, right };
			ID3D11Buffer* cb = stereoAtlasPackCB.Get();
			context->CSSetShader(shader, nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &cb);
			context->CSSetShaderResources(0, 2, sources);
			context->CSSetUnorderedAccessViews(0, 1, &target, nullptr);
			context->Dispatch((constants.atlasWidth + 7) / 8, (constants.atlasHeight + 7) / 8, 1);
			ID3D11ShaderResourceView* nullSRVs[2]{};
			ID3D11UnorderedAccessView* nullUAV = nullptr;
			ID3D11Buffer* nullCB = nullptr;
			context->CSSetShaderResources(0, 2, nullSRVs);
			context->CSSetUnorderedAccessViews(0, 1, &nullUAV, nullptr);
			context->CSSetConstantBuffers(0, 1, &nullCB);
			context->CSSetShader(nullptr, nullptr, 0);
			return true;
		}

		bool EnsureStereoAtlasResources(ID3D11Device* device, std::uint32_t modelWidth, std::uint32_t modelHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorGuard, std::uint32_t guideGuard)
		{
			if (!device || !modelWidth || !modelHeight || !guideWidth || !guideHeight || !colorGuard || !guideGuard)
				return false;
			const auto colorAtlasWidth = modelWidth * 2 + colorGuard;
			const auto guideAtlasWidth = guideWidth * 2 + guideGuard;
			const UINT sharedFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
			const auto colorDesc = MakeSharedDesc(eyes[0].color.desc, colorAtlasWidth, modelHeight, sharedFlags);
			const auto outputDesc = colorDesc;
			const auto depthDesc = MakeSharedDesc(eyes[0].depth.desc, guideAtlasWidth, guideHeight, sharedFlags);
			const auto motionDesc = MakeSharedDesc(eyes[0].motionVectors.desc, guideAtlasWidth, guideHeight, sharedFlags);
			const bool matches = stereoAtlas.valid &&
				stereoAtlas.colorEyeWidth == modelWidth && stereoAtlas.colorEyeHeight == modelHeight &&
				stereoAtlas.guideEyeWidth == guideWidth && stereoAtlas.guideEyeHeight == guideHeight &&
				stereoAtlas.colorGuard == colorGuard && stereoAtlas.guideGuard == guideGuard &&
				Matches(stereoAtlas.color, colorDesc) && Matches(stereoAtlas.depth, depthDesc) &&
				Matches(stereoAtlas.motionVectors, motionDesc) && Matches(stereoAtlas.output, outputDesc);
			if (matches)
				return true;
			if (stereoAtlas.valid && !interop.WaitForIdle())
				return false;
			ResetStereoAtlasFeatures();
			stereoAtlas = {};
			if (!interop.CreateSharedTexture(colorDesc, stereoAtlas.color, "NeuralRendering::StereoAtlasColor") ||
				!interop.CreateSharedTexture(depthDesc, stereoAtlas.depth, "NeuralRendering::StereoAtlasDepth") ||
				!interop.CreateSharedTexture(motionDesc, stereoAtlas.motionVectors, "NeuralRendering::StereoAtlasMotion") ||
				!interop.CreateSharedTexture(outputDesc, stereoAtlas.output, "NeuralRendering::StereoAtlasOutput"))
			{
				stereoAtlas = {};
				return false;
			}
			stereoAtlas.colorEyeWidth = modelWidth;
			stereoAtlas.colorEyeHeight = modelHeight;
			stereoAtlas.guideEyeWidth = guideWidth;
			stereoAtlas.guideEyeHeight = guideHeight;
			stereoAtlas.colorGuard = colorGuard;
			stereoAtlas.guideGuard = guideGuard;
			stereoAtlas.valid = true;
			return true;
		}

		bool PackStereoAtlas(ID3D11Device* device, ID3D11DeviceContext* context,
			ID3D11ShaderResourceView* leftColor, ID3D11ShaderResourceView* rightColor,
			ID3D11ShaderResourceView* leftDepth, ID3D11ShaderResourceView* rightDepth,
			ID3D11ShaderResourceView* leftMotion, ID3D11ShaderResourceView* rightMotion,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorGuard, std::uint32_t guideGuard,
			std::uint32_t colorOffsetX = 0, std::uint32_t colorOffsetY = 0,
			std::uint32_t guideOffsetX = 0, std::uint32_t guideOffsetY = 0)
		{
			return EnsureStereoAtlasPackResources(device) &&
				DispatchStereoAtlasPack(context, stereoAtlasColorPackCS.get(), leftColor, rightColor, stereoAtlas.color.uav11.Get(),
					colorWidth, colorHeight, colorGuard, colorOffsetX, colorOffsetY) &&
				DispatchStereoAtlasPack(context, stereoAtlasDepthPackCS.get(), leftDepth, rightDepth, stereoAtlas.depth.uav11.Get(),
					guideWidth, guideHeight, guideGuard, guideOffsetX, guideOffsetY) &&
				DispatchStereoAtlasPack(context, stereoAtlasMotionPackCS.get(), leftMotion, rightMotion, stereoAtlas.motionVectors.uav11.Get(),
					guideWidth, guideHeight, guideGuard, guideOffsetX, guideOffsetY);
		}

		bool EvaluateStereoAtlasPass(std::uint32_t tierIndex, std::uint32_t passIndex,
			std::uint32_t eyeColorWidth, std::uint32_t eyeColorHeight,
			std::uint32_t eyeGuideWidth, std::uint32_t eyeGuideHeight,
			std::uint32_t colorGuard, std::uint32_t guideGuard,
			float motionScaleX, float motionScaleY, const Tuning& tuning, bool reset)
		{
			const auto atlasColorWidth = eyeColorWidth * 2 + colorGuard;
			const auto atlasGuideWidth = eyeGuideWidth * 2 + guideGuard;
			Feature18GuideContract guide{};
			guide.colorWidth = atlasColorWidth;
			guide.colorHeight = eyeColorHeight;
			guide.depthWidth = atlasGuideWidth;
			guide.depthHeight = eyeGuideHeight;
			guide.motionWidth = atlasGuideWidth;
			guide.motionHeight = eyeGuideHeight;
			guide.outputWidth = atlasColorWidth;
			guide.outputHeight = eyeColorHeight;
			const auto atlasCreationColorWidth = stereoAtlas.colorEyeWidth * 2 + stereoAtlas.colorGuard;
			const auto atlasCreationColorHeight = stereoAtlas.colorEyeHeight;
			guide.creationInputWidth = atlasCreationColorWidth;
			guide.creationInputHeight = atlasCreationColorHeight;
			guide.creationOutputWidth = atlasCreationColorWidth;
			guide.creationOutputHeight = atlasCreationColorHeight;
			guide.motionVectorScaleX = motionScaleX;
			guide.motionVectorScaleY = motionScaleY;
			guide.motionVectorsLowResolution = atlasGuideWidth <= atlasColorWidth && eyeGuideHeight <= eyeColorHeight;
			const auto slot = AtlasFeatureSlot(tuning.singlePassLadder ? 0u : tierIndex, passIndex);
			if (Runtime::Instance().NeedsRecreation(slot, atlasCreationColorWidth, atlasCreationColorHeight,
				atlasCreationColorWidth, atlasCreationColorHeight, guide.motionVectorsLowResolution)) {
				if (!interop.WaitForIdle()) return false;
				Runtime::Instance().ResetFeature(slot);
				ladderAtlasGeometry.valid = false;
				reset = true;
				logger::info("[DLSSNR][Atlas] native history reset: creation contract changed slot={}", slot);
			}
			ID3D12GraphicsCommandList* commandList = nullptr;
			if (!interop.BeginD3D12(&commandList)) return false;
			TransitionEvaluationResources(commandList, stereoAtlas.color.resource12.Get(), stereoAtlas.depth.resource12.Get(),
				stereoAtlas.motionVectors.resource12.Get(), stereoAtlas.output.resource12.Get(), true);
			const auto passTuning = TuningForCascadePass(tuning, passIndex);
			const bool succeeded = Runtime::Instance().Execute(commandList, slot,
				stereoAtlas.color.resource12.Get(), stereoAtlas.depth.resource12.Get(), stereoAtlas.motionVectors.resource12.Get(),
				stereoAtlas.output.resource12.Get(), guide, passTuning, reset);
			TransitionEvaluationResources(commandList, stereoAtlas.color.resource12.Get(), stereoAtlas.depth.resource12.Get(),
				stereoAtlas.motionVectors.resource12.Get(), stereoAtlas.output.resource12.Get(), false);
			if (!interop.EndD3D12())
				return false;
			return succeeded;
		}

		void SplitStereoAtlasOutput(ID3D11DeviceContext* context, ID3D11Resource* leftTarget, ID3D11Resource* rightTarget,
			std::uint32_t eyeWidth, std::uint32_t eyeHeight, std::uint32_t guardWidth,
			std::uint32_t destinationOffsetX = 0, std::uint32_t destinationOffsetY = 0)
		{
			const D3D11_BOX leftBox{ 0, 0, 0, eyeWidth, eyeHeight, 1 };
			const D3D11_BOX rightBox{ eyeWidth + guardWidth, 0, 0, eyeWidth * 2 + guardWidth, eyeHeight, 1 };
			context->CopySubresourceRegion(leftTarget, 0, destinationOffsetX, destinationOffsetY, 0, stereoAtlas.output.resource11.Get(), 0, &leftBox);
			context->CopySubresourceRegion(rightTarget, 0, destinationOffsetX, destinationOffsetY, 0, stereoAtlas.output.resource11.Get(), 0, &rightBox);
		}


		struct LadderAtlasGeometry
		{
			std::uint32_t modelWidth = 0, modelHeight = 0, colorWidth = 0, colorHeight = 0, guard = 0, frame = UINT32_MAX;
			std::array<std::array<std::uint32_t, 2>, 2> origins{};
			std::array<std::array<float, 4>, 2> sampling{};
			bool valid = false;
		};
		struct LadderAtlasConstants
		{
			std::array<std::uint32_t, 4> current{}, previous{}, layout{};
			std::array<float, 4> leftOrigin{}, rightOrigin{}, motionScale{};
			std::array<std::uint32_t, 4> flags{};
			std::array<float, 4> modelPitch{}, leftPhase{}, rightPhase{};
		};
		static_assert(sizeof(LadderAtlasConstants) == 160);

		bool PackLadderGuides(ID3D11Device* device, ID3D11DeviceContext* context,
			const std::array<StereoEyeInput, 2>& inputs,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t modelWidth, std::uint32_t modelHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight, std::uint32_t colorGuard, std::uint32_t guideGuard)
		{
			if (!ladderAtlasGuidesCS.Get(L"Data\\Shaders\\Upscaling\\NeuralRendering\\LadderAtlasGuidesCS.hlsl", {}, "cs_5_0", "main", "NeuralRendering::LadderAtlasGuides"))
				return false;
			if (!ladderAtlasCB) {
				D3D11_BUFFER_DESC desc{};
				desc.ByteWidth = sizeof(LadderAtlasConstants);
				desc.Usage = D3D11_USAGE_DEFAULT;
				desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&desc, nullptr, ladderAtlasCB.GetAddressOf()))) return false;
				Util::SetResourceName(ladderAtlasCB.Get(), "NeuralRendering::LadderAtlasCB");
			}
			const auto frame = globals::state->frameCount;
			const bool previousValid = ladderAtlasGeometry.valid &&
				std::uint32_t(frame - ladderAtlasGeometry.frame) == 1u && !stereoAtlasResetPending;
			LadderAtlasConstants data{};
			data.current = { modelWidth, modelHeight, guideWidth, guideHeight };
			data.previous = { ladderAtlasGeometry.modelWidth, ladderAtlasGeometry.modelHeight,
				ladderAtlasGeometry.colorWidth, ladderAtlasGeometry.colorHeight };
			data.layout = { colorWidth, colorHeight, colorGuard, ladderAtlasGeometry.guard };
			for (unsigned eye = 0; eye < 2; ++eye) {
				auto& origin = eye ? data.rightOrigin : data.leftOrigin;
				origin = { float(inputs[eye].sourceX), float(inputs[eye].sourceY),
					float(ladderAtlasGeometry.origins[eye][0]), float(ladderAtlasGeometry.origins[eye][1]) };
				auto& phase = eye ? data.rightPhase : data.leftPhase;
				phase = { eyes[eye].modelSampling[2], eyes[eye].modelSampling[3],
					ladderAtlasGeometry.sampling[eye][2], ladderAtlasGeometry.sampling[eye][3] };
			}
			data.modelPitch = { eyes[0].modelSampling[0], eyes[0].modelSampling[1],
				ladderAtlasGeometry.sampling[0][0], ladderAtlasGeometry.sampling[0][1] };
			data.motionScale = {
				inputs[0].sceneColorMotionScale[0] > 0 ? inputs[0].sceneColorMotionScale[0] : GuideToColorMotionScale(inputs[0].motionVectorScaleX, colorWidth, guideWidth),
				inputs[0].sceneColorMotionScale[1] > 0 ? inputs[0].sceneColorMotionScale[1] : GuideToColorMotionScale(inputs[0].motionVectorScaleY, colorHeight, guideHeight),
				inputs[0].motionVectorScaleX * float(modelWidth) / guideWidth,
				inputs[0].motionVectorScaleY * float(modelHeight) / guideHeight };
			if (!std::isfinite(data.motionScale[2]) || !std::isfinite(data.motionScale[3]) ||
				data.motionScale[2] == 0.0f || data.motionScale[3] == 0.0f ||
				std::abs(2.0f * stereoAtlas.colorEyeHeight / data.motionScale[3]) > 65504.0f)
				return false;
			data.flags = { previousValid ? 1u : 0u, guideGuard, stereoAtlas.colorEyeHeight, 0u };
			CS_GPU_PASS("NeuralRendering::LadderAtlasGuides");
			context->UpdateSubresource(ladderAtlasCB.Get(), 0, nullptr, &data, 0, 0);
			ID3D11ShaderResourceView* sources[]{ eyes[0].motionVectors.srv11.Get(), eyes[1].motionVectors.srv11.Get(),
				eyes[0].depth.srv11.Get(), eyes[1].depth.srv11.Get() };
			ID3D11UnorderedAccessView* targets[]{ stereoAtlas.motionVectors.uav11.Get(), stereoAtlas.depth.uav11.Get() };
			ID3D11Buffer* cb = ladderAtlasCB.Get();
			context->CSSetShader(ladderAtlasGuidesCS.get(), nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &cb);
			context->CSSetShaderResources(0, 4, sources);
			context->CSSetUnorderedAccessViews(0, 2, targets, nullptr);
			context->Dispatch((guideWidth * 2 + guideGuard + 7) / 8, (guideHeight + 7) / 8, 1);
			ID3D11ShaderResourceView* nullSources[4]{};
			ID3D11UnorderedAccessView* nullTargets[2]{};
			ID3D11Buffer* nullCB = nullptr;
			context->CSSetShaderResources(0, 4, nullSources);
			context->CSSetUnorderedAccessViews(0, 2, nullTargets, nullptr);
			context->CSSetConstantBuffers(0, 1, &nullCB);
			context->CSSetShader(nullptr, nullptr, 0);
			return true;
		}

		StereoAtlasResult ApplyStereoAtlasNative(ID3D11Device* device, ID3D11DeviceContext* context,
			const std::array<StereoEyeInput, 2>& inputs, std::uint32_t tierIndex,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t modelWidth, std::uint32_t modelHeight,
			std::uint32_t modelResolution, std::uint32_t passCount, const Tuning& tuning)
		{
			if (!tuning.stereoAtlas) {
				if (stereoAtlasActiveLastFrame) {
					if (interop.WaitForIdle()) ResetStereoAtlasFeatures();
					stereoAtlasActiveLastFrame = false;
				}
				return StereoAtlasResult::FallBack;
			}
			if (stereoAtlasModeObserved && stereoAtlasSinglePassMode != tuning.singlePassLadder) {
				if (!interop.WaitForIdle()) return StereoAtlasResult::Failed;
				ResetStereoAtlasFeatures();
				stereoAtlasActiveLastFrame = false;
			}
			stereoAtlasModeObserved = true;
			stereoAtlasSinglePassMode = tuning.singlePassLadder;
			const bool scalesMatch = std::abs(inputs[0].motionVectorScaleX - inputs[1].motionVectorScaleX) < 1e-4f &&
				std::abs(inputs[0].motionVectorScaleY - inputs[1].motionVectorScaleY) < 1e-4f;
			const bool compatible = (!tuning.singlePassLadder || passCount == 1) && passCount >= 1 && passCount <= 2 && !tuning.adaptiveResolution &&
				tuning.temporalReuseCadence == 0 && !tuning.temporalReuseStaggerEyes && scalesMatch &&
				modelWidth && modelHeight && guideWidth && guideHeight;
			if (!compatible) {
				if (!stereoAtlasFallbackLogged) {
					logger::warn("[DLSSNR][Atlas] incompatible route; strict={} passes={} scalesMatch={}",
					tuning.singlePassLadder, passCount, scalesMatch);
					stereoAtlasFallbackLogged = true;
				}
				if (stereoAtlasActiveLastFrame && interop.WaitForIdle()) ResetStereoAtlasFeatures();
				stereoAtlasActiveLastFrame = false;
				return StereoAtlasResult::FallBack;
			}

			const auto requestedGuard = std::clamp(tuning.stereoAtlasGuardPixels, 8u, 256u);
			const auto colorGuard = std::clamp(ScaleDimension(requestedGuard, modelResolution), 1u, modelWidth);
			const auto guideGuard = std::clamp(static_cast<std::uint32_t>(std::lround(
				static_cast<double>(colorGuard) * guideWidth / std::max(modelWidth, 1u))), 1u, guideWidth);
			const auto residentModelWidth = tuning.singlePassLadder ? eyes[0].color.desc.Width : eyes[0].tiers[tierIndex].reducedResolution ?
				eyes[0].tiers[tierIndex].modelInput.desc.Width : eyes[0].color.desc.Width;
			const auto residentModelHeight = tuning.singlePassLadder ? eyes[0].color.desc.Height : eyes[0].tiers[tierIndex].reducedResolution ?
				eyes[0].tiers[tierIndex].modelInput.desc.Height : eyes[0].color.desc.Height;
			if (!EnsureStereoAtlasResources(device, residentModelWidth, residentModelHeight,
				eyes[0].depth.desc.Width, eyes[0].depth.desc.Height,
				tuning.singlePassLadder ? requestedGuard : colorGuard,
				tuning.singlePassLadder ? std::max(guideGuard, static_cast<std::uint32_t>(std::ceil(
					double(requestedGuard) * eyes[0].depth.desc.Width / std::max(1.0, double(eyes[0].color.desc.Width) * 0.70)))) : guideGuard))
				return StereoAtlasResult::FallBack;

			auto& leftTier = eyes[0].tiers[tierIndex];
			auto& rightTier = eyes[1].tiers[tierIndex];
			ID3D11ShaderResourceView* leftInput = leftTier.reducedResolution ? leftTier.modelInput.srv11.Get() : eyes[0].color.srv11.Get();
			ID3D11ShaderResourceView* rightInput = rightTier.reducedResolution ? rightTier.modelInput.srv11.Get() : eyes[1].color.srv11.Get();
			if (!leftInput || !rightInput || colorWidth > eyes[0].color.desc.Width || colorWidth > eyes[1].color.desc.Width ||
				colorHeight > eyes[0].color.desc.Height || colorHeight > eyes[1].color.desc.Height ||
				modelWidth > residentModelWidth || modelHeight > residentModelHeight ||
				guideWidth > eyes[0].depth.desc.Width || guideWidth > eyes[1].depth.desc.Width ||
				guideHeight > eyes[0].depth.desc.Height || guideHeight > eyes[1].depth.desc.Height)
				return StereoAtlasResult::Failed;
			bool packed = false;
			if (tuning.singlePassLadder) {
				if (!EnsureStereoAtlasPackResources(device)) return StereoAtlasResult::FallBack;
				packed = DispatchStereoAtlasPack(context, stereoAtlasColorPackCS.get(), leftInput, rightInput,
					stereoAtlas.color.uav11.Get(), modelWidth, modelHeight, colorGuard, 0, 0) &&
					PackLadderGuides(device, context, inputs, colorWidth, colorHeight,
						modelWidth, modelHeight, guideWidth, guideHeight, colorGuard, guideGuard);
			} else {
				packed = PackStereoAtlas(device, context, leftInput, rightInput,
					eyes[0].depth.srv11.Get(), eyes[1].depth.srv11.Get(),
					eyes[0].motionVectors.srv11.Get(), eyes[1].motionVectors.srv11.Get(),
					modelWidth, modelHeight, guideWidth, guideHeight, colorGuard, guideGuard);
			}
			if (!leftInput || !rightInput || !packed) return StereoAtlasResult::FallBack;
			const float motionScaleX = FoveatedRenderImpl::CropGeometry::NativeGuideMotionScale(inputs[0].motionVectorScaleX, modelWidth, colorWidth);
			const float motionScaleY = FoveatedRenderImpl::CropGeometry::NativeGuideMotionScale(inputs[0].motionVectorScaleY, modelHeight, colorHeight);

			const bool enteringAtlas = !stereoAtlasActiveLastFrame;
			const bool reset = stereoAtlasResetPending ||
				(tuning.singlePassLadder && (!ladderAtlasGeometry.valid ||
					std::uint32_t(globals::state->frameCount - ladderAtlasGeometry.frame) != 1u)) ||
				(enteringAtlas && (resetPending[0][tierIndex] || resetPending[1][tierIndex])) ||
				(temporalSkippedSinceFull && tuning.temporalReuseResetAfterSkip);
			if (!EvaluateStereoAtlasPass(tierIndex, 0, modelWidth, modelHeight, guideWidth, guideHeight,
				colorGuard, guideGuard, motionScaleX, motionScaleY, tuning, reset)) {
				if (interop.WaitForIdle())
					Runtime::Instance().ResetFeature(AtlasFeatureSlot(tuning.singlePassLadder ? 0u : tierIndex, 0));
				stereoAtlasResetPending = true;
				return StereoAtlasResult::FallBack;
			}

			ID3D11Resource* leftPass1Target = passCount == 1 ? leftTier.output.resource11.Get() : leftTier.cascadeIntermediates[0].resource11.Get();
			ID3D11Resource* rightPass1Target = passCount == 1 ? rightTier.output.resource11.Get() : rightTier.cascadeIntermediates[0].resource11.Get();
			if (!leftPass1Target || !rightPass1Target)
				return StereoAtlasResult::FallBack;
			SplitStereoAtlasOutput(context, leftPass1Target, rightPass1Target, modelWidth, modelHeight, colorGuard);

			if (passCount == 2) {
				const auto coverage = std::clamp(tuning.secondPass.coveragePercent, 50u, 100u);
				const auto pass2Width = ScaleDimension(modelWidth, coverage);
				const auto pass2Height = ScaleDimension(modelHeight, coverage);
				const auto pass2GuideWidth = ScaleDimension(guideWidth, coverage);
				const auto pass2GuideHeight = ScaleDimension(guideHeight, coverage);
				const auto pass2ColorGuard = std::min(colorGuard, pass2Width);
				const auto pass2GuideGuard = std::min(guideGuard, pass2GuideWidth);
				const auto colorOffsetX = (modelWidth - pass2Width) / 2;
				const auto colorOffsetY = (modelHeight - pass2Height) / 2;
				const auto guideOffsetX = (guideWidth - pass2GuideWidth) / 2;
				const auto guideOffsetY = (guideHeight - pass2GuideHeight) / 2;
				if (!PackStereoAtlas(device, context,
					leftTier.cascadeIntermediates[0].srv11.Get(), rightTier.cascadeIntermediates[0].srv11.Get(),
					eyes[0].depth.srv11.Get(), eyes[1].depth.srv11.Get(),
					eyes[0].motionVectors.srv11.Get(), eyes[1].motionVectors.srv11.Get(),
					pass2Width, pass2Height, pass2GuideWidth, pass2GuideHeight,
					pass2ColorGuard, pass2GuideGuard, colorOffsetX, colorOffsetY, guideOffsetX, guideOffsetY))
					return StereoAtlasResult::FallBack;
				if (!EvaluateStereoAtlasPass(tierIndex, 1, pass2Width, pass2Height, pass2GuideWidth, pass2GuideHeight,
					pass2ColorGuard, pass2GuideGuard, motionScaleX, motionScaleY, tuning, reset)) {
					if (interop.WaitForIdle())
						Runtime::Instance().ResetFeature(AtlasFeatureSlot(tierIndex, 1));
					stereoAtlasResetPending = true;
					return StereoAtlasResult::FallBack;
				}
				if (coverage < 100) {
					if (!leftTier.secondPassOutput.resource11 || !rightTier.secondPassOutput.resource11)
						return StereoAtlasResult::FallBack;
					SplitStereoAtlasOutput(context, leftTier.secondPassOutput.resource11.Get(), rightTier.secondPassOutput.resource11.Get(),
						pass2Width, pass2Height, pass2ColorGuard,
						(modelWidth - pass2Width) / 2, (modelHeight - pass2Height) / 2);
					if (!CompositeSequentialPass(device, context, leftTier, modelWidth, modelHeight, pass2Width, pass2Height, tuning) ||
						!CompositeSequentialPass(device, context, rightTier, modelWidth, modelHeight, pass2Width, pass2Height, tuning))
						return StereoAtlasResult::FallBack;
				} else {
					SplitStereoAtlasOutput(context, leftTier.output.resource11.Get(), rightTier.output.resource11.Get(),
						modelWidth, modelHeight, colorGuard);
				}
			}

			if (tuning.singlePassLadder) {
				ladderAtlasGeometry = { modelWidth, modelHeight, colorWidth, colorHeight, colorGuard,
					globals::state->frameCount,
					{{ { inputs[0].sourceX, inputs[0].sourceY }, { inputs[1].sourceX, inputs[1].sourceY } }},
					{ eyes[0].modelSampling, eyes[1].modelSampling }, true };
			} else ladderAtlasGeometry.valid = false;
			stereoAtlasResetPending = false;
			stereoAtlasActiveLastFrame = true;
			stereoAtlasFallbackLogged = false;
			if (!stereoAtlasActiveLogged) {
				logger::info("[DLSSNR][Atlas] active passes={} guard={}px modelGuard={}px; one Feature18 atlas evaluation per pass",
					passCount, tuning.stereoAtlasGuardPixels, colorGuard);
				stereoAtlasActiveLogged = true;
			}
			return StereoAtlasResult::Applied;
		}

		bool LatchFailure(const char* operation, HRESULT error)
		{
			failureLatched = true;
			failureOperation = operation;
			failureTime = std::chrono::steady_clock::now();
			recoverableFailure = error == E_OUTOFMEMORY || static_cast<std::uint32_t>(error) == 0xBAD00002u;
			logger::error("[DLSSNR] {} failed hr/ngx=0x{:08X} status={} detail={}",
				operation, static_cast<std::uint32_t>(error), ToString(Runtime::Instance().Status()), Runtime::Instance().Detail());
			return false;
		}

		D3D12Interop interop;
		Util::LazyShader<ID3D11ComputeShader> copyDepthGuideCS;
		Util::LazyShader<ID3D11ComputeShader> alignGuidesCS;
		Microsoft::WRL::ComPtr<ID3D11Buffer> alignGuidesCB;
		Util::LazyShader<ID3D11ComputeShader> modelResolutionCS;
		Util::LazyShader<ID3D11ComputeShader> temporalSnapshotCS;
		Util::LazyShader<ID3D11ComputeShader> temporalAccumulateCS;
		Util::LazyShader<ID3D11ComputeShader> temporalReprojectCS;
		Util::LazyShader<ID3D11ComputeShader> adaptiveHandoffCS;
		Util::LazyShader<ID3D11ComputeShader> resultShapingCS;
		Util::LazyShader<ID3D11ComputeShader> sequentialCompositeCS;
		Util::LazyShader<ID3D11ComputeShader> stereoAtlasColorPackCS;
		Util::LazyShader<ID3D11ComputeShader> stereoAtlasDepthPackCS;
		Util::LazyShader<ID3D11ComputeShader> stereoAtlasMotionPackCS;
		Microsoft::WRL::ComPtr<ID3D11Buffer> sequentialCompositeCB;
		Microsoft::WRL::ComPtr<ID3D11Buffer> stereoAtlasPackCB;
		Microsoft::WRL::ComPtr<ID3D11Buffer> modelResolutionCB;
		Microsoft::WRL::ComPtr<ID3D11SamplerState> modelResolutionSampler;
		Microsoft::WRL::ComPtr<ID3D11Buffer> temporalReuseCB;
		Microsoft::WRL::ComPtr<ID3D11SamplerState> temporalReuseSampler;
		Microsoft::WRL::ComPtr<ID3D11Buffer> adaptiveHandoffCB;
		Microsoft::WRL::ComPtr<ID3D11SamplerState> adaptiveHandoffSampler;
		Microsoft::WRL::ComPtr<ID3D11Buffer> resultShapingCB;
		Microsoft::WRL::ComPtr<ID3D11SamplerState> resultShapingSampler;
		std::array<EyeResources, 2> eyes;
		LadderAtlasGeometry ladderAtlasGeometry;
		bool stereoAtlasModeObserved = false;
		bool stereoAtlasSinglePassMode = false;
		Util::LazyShader<ID3D11ComputeShader> ladderAtlasGuidesCS;
		Microsoft::WRL::ComPtr<ID3D11Buffer> ladderAtlasCB;
		StereoAtlasResources stereoAtlas;
		std::array<std::array<bool, kResolutionTierCount>, 2> resetPending{};
		bool stereoAtlasResetPending = true;
		bool stereoAtlasActiveLastFrame = false;
		bool stereoAtlasActiveLogged = false;
		bool stereoAtlasFallbackLogged = false;
		bool temporalConfigInitialized = false;
		TemporalHistoryConfig temporalConfig;
		bool resultShapingConfigInitialized = false;
		ResultShapingConfigKey resultShapingConfig;
		std::uint64_t temporalFrameIndex = 0;
		bool temporalSkippedSinceFull = false;
		std::array<bool, 2> staggerSkippedLastFrame{};
		bool temporalReuseStaggerLogged = false;
		bool temporalReuseActiveLogged = false;
		bool temporalReuseCropActiveLogged = false;
		bool temporalReuseWarningLogged = false;
		bool resultShapingFailureLogged = false;
		bool resultStabilizationFailureLogged = false;
		std::uint32_t adaptivePrewarmTier = UINT32_MAX;
		std::uint32_t adaptivePrewarmResolution = 0;
		std::int32_t adaptivePrewarmDirection = 0;
		std::uint32_t adaptivePrewarmPassCount = 0;
		std::uint32_t adaptivePrewarmStableFrames = 0;
		std::uint32_t adaptivePrewarmCandidate = 0;
		std::uint32_t adaptivePrewarmEye = 0;
		std::uint32_t adaptivePrewarmColorWidth = 0;
		std::uint32_t adaptivePrewarmColorHeight = 0;
		std::uint32_t adaptivePrewarmGuideWidth = 0;
		std::uint32_t adaptivePrewarmGuideHeight = 0;
		std::array<bool, 2> adaptivePrewarmResourcesReady{};
		std::array<bool, 2> adaptivePrewarmRejected{};
		std::string failureOperation;
		bool failureLatched = false;
		bool recoveryAttempted = false;
		bool recoverableFailure = false;
		std::chrono::steady_clock::time_point failureTime{};
	};

	Renderer::Renderer() : state_(new State()) {}
	Renderer::~Renderer() { delete state_; }
	Renderer& Renderer::Instance() { static Renderer instance; return instance; }

	bool Renderer::Apply(ID3D11Device* device, ID3D11DeviceContext* context, std::uint32_t eyeIndex,
		ID3D11Resource* color, ID3D11Resource* depth, ID3D11ShaderResourceView* depthSRV,
		ID3D11Resource* motionVectors,
		std::uint32_t guideWidth, std::uint32_t guideHeight, std::uint32_t colorWidth, std::uint32_t colorHeight,
		float motionVectorScaleX, float motionVectorScaleY, const Tuning& tuning)
	{
		return state_->Apply(device, context, eyeIndex, color, depth, depthSRV, motionVectors,
			guideWidth, guideHeight, colorWidth, colorHeight, motionVectorScaleX, motionVectorScaleY, tuning);
	}

	bool Renderer::ApplyStereo(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Resource* color,
		const std::array<StereoEyeInput, 2>& eyes,
		std::uint32_t guideWidth, std::uint32_t guideHeight,
		std::uint32_t colorWidth, std::uint32_t colorHeight, const Tuning& tuning,
		ID3D11Resource* destination, ID3D11UnorderedAccessView* destinationUAV,
		bool blendSubrect, const StereoResourceEnvelope& resourceEnvelope)
	{
		const bool succeeded = state_->ApplyStereo(device, context, color, eyes,
			guideWidth, guideHeight, colorWidth, colorHeight, tuning,
				destination, destinationUAV, blendSubrect, resourceEnvelope);
		for (std::uint32_t eye = 0; eye < 2; ++eye)
			FoveatedRenderImpl::CropMotion::Commit(2 + eye, succeeded && eyes[eye].compensateCropMotion);
		return succeeded;
	}

	bool Renderer::Reset() { FoveatedRenderImpl::CropMotion::Invalidate(2, 2); return state_->Reset(); }

	void Renderer::ClearShaderCache() { state_->ClearShaderCache(); }
	void Renderer::ResetHistory() { FoveatedRenderImpl::CropMotion::Invalidate(2, 2); state_->ResetHistory(); }
	bool Renderer::IsStereoAtlasActive() const { return state_->IsStereoAtlasActive(); }
	bool Renderer::IsOutputTransitioning() const { return state_->IsOutputTransitioning(); }
	bool Renderer::IsFailureLatched() const { return state_->IsFailureLatched(); }
	bool Renderer::IsFailureRecoverable() const { return state_->IsFailureRecoverable(); }
	bool Renderer::IsRecoveryLimited() const { return state_->IsRecoveryLimited(); }
	bool Renderer::IsAdaptiveTierReady(std::uint32_t modelResolution) const { return state_->IsAdaptiveTierReady(modelResolution); }
	std::uint32_t Renderer::NgxResult() const { return Runtime::Instance().NgxResult(); }
	std::uint64_t Renderer::SuccessfulFrames() const { return Runtime::Instance().SuccessfulFrames(); }
	const char* Renderer::StatusText() const { return state_->StatusText(); }
}
