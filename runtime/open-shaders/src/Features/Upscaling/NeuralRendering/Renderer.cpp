#include "Renderer.h"

#include "D3D12Interop.h"
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
		constexpr std::array<std::uint32_t, 7> kResolutionTiers{
			100, 95, 90, 85, 80, 75, 70 };
		constexpr std::uint32_t kResolutionTierCount = static_cast<std::uint32_t>(kResolutionTiers.size());
		// All supported adaptive tiers are prewarmed. Keeping this ladder short
		// limits the number of per-eye Feature 18 dimension/resource states.
		constexpr std::uint32_t kAdaptiveTierCount = kResolutionTierCount;
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

		std::uint32_t GetPassCount(const Tuning& tuning)
		{
			return tuning.multiPass == 0 ? 1 : std::min(tuning.multiPass + 1, kCascadePassCount);
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
				!GetTextureDesc(globals::game::renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kMAIN].texture, nativeDesc) ||
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
				if (!IsValidCaptureRect(texture, sourceX, sourceY, sourceWidth, sourceHeight))
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
				const bool hasDesc = GetTextureDesc(texture, desc);
				const bool validRect = hasDesc && sourceWidth && sourceHeight &&
					static_cast<std::uint64_t>(sourceX) + sourceWidth <= desc.Width &&
					static_cast<std::uint64_t>(sourceY) + sourceHeight <= desc.Height;
				const bool queued = validRect && capture.CaptureTexture(texture, sourceX, sourceY,
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
			// Keep the renderer-side safety net aligned with FoveatedRender::ClampSettings:
			// old experimental values below 70% must not silently re-enable full-cost NR.
			return percent < kResolutionTiers.back() ? kResolutionTiers.back() : kResolutionTiers.front();
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
			// controls build stops at the conservative 70% floor.
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
				return { 0.90f, 0.52f, 1.50f, 0.76f };
			case 70:
				return { 0.86f, 0.45f, 1.45f, 0.72f };
			case 67:
				return { 0.83f, 0.40f, 1.42f, 0.70f };
			case 60:
				return { 0.76f, 0.30f, 1.38f, 0.66f };
			case 50:
				return { 0.70f, 0.22f, 1.35f, 0.65f };
			case 33:
				return { 0.60f, 0.18f, 1.20f, 0.55f };
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
			std::uint32_t accumulatedMotionIndex = 0;
			bool valid = false;
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
			SharedTexture output;
			Microsoft::WRL::ComPtr<ID3D11Texture2D> resolved;
			Microsoft::WRL::ComPtr<ID3D11ShaderResourceView> resolvedSRV;
			Microsoft::WRL::ComPtr<ID3D11UnorderedAccessView> resolvedUAV;
			std::uint32_t modelResolution = 100;
			std::uint32_t passCount = 1;
			bool reducedResolution = false;
		};

		struct EyeResources
			{
			SharedTexture color;
			SharedTexture depth;
			SharedTexture motionVectors;
			std::array<TierResources, kResolutionTierCount> tiers;
			TemporalEyeState temporal;
				std::uint32_t colorWidth = 0;
				std::uint32_t colorHeight = 0;
				std::uint32_t guideWidth = 0;
				std::uint32_t guideHeight = 0;
				std::uint32_t sharedColorWidth = 0;
				std::uint32_t sharedColorHeight = 0;
				std::uint32_t sharedGuideWidth = 0;
				std::uint32_t sharedGuideHeight = 0;
				bool sharedResourcesValid = false;
				bool adaptiveTiersPrewarmed = false;
				HandoffEyeState handoff;
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
			if (failureLatched || !device || !context || eyeIndex >= eyes.size() || !color || !depth || !depthSRV || !motionVectors)
				return false;
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
				colorWidth, colorHeight, modelWidth, modelHeight, passCount, modelResolution,
				tuning.adaptiveResolution, {}))
				return LatchFailure("shared resource creation", interop.LastError());

			auto& eye = eyes[eyeIndex];
			auto& tier = eye.tiers[tierIndex];
			if (!tuning.adaptiveResolution)
				eye.handoff.valid = false;
			context->CopyResource(eye.color.resource11.Get(), color);
			if (tier.reducedResolution && !DispatchModelInput(device, context, eye, tier, colorWidth, colorHeight, modelWidth, modelHeight,
				 tuning.modelResolveMode == 1))
				return LatchFailure("model input downsample", E_FAIL);
			if (!CopyDepthGuide(context, depthSRV, eye.depth.uav11.Get(), guideWidth, guideHeight))
				return LatchFailure("depth guide conversion", E_FAIL);
			context->CopyResource(eye.motionVectors.resource11.Get(), motionVectors);

			const bool temporalCandidate = IsTemporalReuseConfigured(tuning) &&
				modelResolution == 100 && passCount == 1 &&
				CanAttemptTemporalReuse(eye, colorWidth, colorHeight, guideWidth, guideHeight) &&
				!tuning.adaptiveResolution && !resetPending[eyeIndex][tierIndex] &&
				(temporalFrameIndex % tuning.temporalReuseCadence) != 0;
			if (temporalCandidate && TryTemporalReuse(device, context, eye,
				colorWidth, colorHeight, guideWidth, guideHeight,
				motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth,
				motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight, tuning)) {
				context->CopyResource(color, eye.tiers[0].output.resource11.Get());
				resetPending[eyeIndex][tierIndex] = false;
				temporalSkippedSinceFull = true;
				AdvanceTemporalFrame(tuning);
				LogTemporalReuseActive(tuning.temporalReuseCadence);
				return true;
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
				captureInfo.motionVectorScaleX[eyeIndex] = motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth;
				captureInfo.motionVectorScaleY[eyeIndex] = motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight;
				captureInfo.historyReset[eyeIndex] = resetPending[eyeIndex][tierIndex];
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
				tier.output.resource12.Get(),
				tier.reducedResolution ? modelWidth : colorWidth,
				tier.reducedResolution ? modelHeight : colorHeight,
				guideWidth, guideHeight, modelWidth, modelHeight,
				motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth,
				motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight,
				tuning, passCount, resetPending[eyeIndex][tierIndex] || temporalSkippedSinceFull);
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

			if (tier.reducedResolution && !DispatchModelResolve(device, context, eye, tier, colorWidth, colorHeight, resolveSettings,
					tuning.modelResolveMode == 1)) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("model output resolve", E_FAIL);
			}
			if (!tuning.adaptiveResolution && IsTemporalReuseConfigured(tuning) && modelResolution == 100 && passCount == 1) {
				if (!RecordTemporalHistory(device, context, eye, colorWidth, colorHeight, guideWidth, guideHeight))
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
			ID3D11Resource* writeback = neuralOutput;
			if (tuning.adaptiveResolution)
				writeback = ApplyAdaptiveHandoff(device, context, eyeIndex, eye, neuralOutput, neuralOutputSRV,
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
			if (failureLatched || !device || !context || !color)
				return false;
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
			const std::uint32_t passCount = GetPassCount(tuning);
			const std::uint32_t tierIndex = ResolutionTierIndex(modelResolution);
			const auto resolveSettings = FrameResolveSettings(modelResolution, tuning.adaptiveResolution);
			SyncTemporalReuseConfig(tuning, modelResolution, passCount);
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				const auto& input = inputs[eyeIndex];
				if (!input.depth || !input.depthSRV || !input.motionVectors)
					return false;
				if (!EnsureResources(device, eyeIndex, color, input.depth, input.motionVectors,
						guideWidth, guideHeight, colorWidth, colorHeight, modelWidth, modelHeight, passCount, modelResolution,
						tuning.adaptiveResolution, resourceEnvelope))
					return LatchFailure("shared resource creation", interop.LastError());

				D3D11_BOX sourceBox{
					input.sourceX, input.sourceY, 0,
					input.sourceX + colorWidth, input.sourceY + colorHeight, 1
				};
				auto& eye = eyes[eyeIndex];
				auto& tier = eye.tiers[tierIndex];
				context->CopySubresourceRegion(eye.color.resource11.Get(), 0, 0, 0, 0, color, 0, &sourceBox);
				if (tier.reducedResolution && !DispatchModelInput(device, context, eye, tier, colorWidth, colorHeight, modelWidth, modelHeight,
					 tuning.modelResolveMode == 1))
					return LatchFailure("model input downsample stereo", E_FAIL);
				if (!CopyDepthGuide(context, input.depthSRV, eye.depth.uav11.Get(), guideWidth, guideHeight))
					return LatchFailure("depth guide conversion", E_FAIL);
				context->CopyResource(eye.motionVectors.resource11.Get(), input.motionVectors);
			}

			const bool temporalCandidate = IsTemporalReuseConfigured(tuning) &&
				modelResolution == 100 && passCount == 1 && !blendSubrect &&
				IsFullEyeTemporalLayout(colorDesc, inputs, colorWidth, colorHeight) &&
				CanAttemptTemporalReuse(eyes[0], colorWidth, colorHeight, guideWidth, guideHeight) &&
				CanAttemptTemporalReuse(eyes[1], colorWidth, colorHeight, guideWidth, guideHeight) &&
				!tuning.adaptiveResolution && !resetPending[0][tierIndex] && !resetPending[1][tierIndex] &&
				(temporalFrameIndex % tuning.temporalReuseCadence) != 0;
			if (temporalCandidate) {
				bool reused = true;
				for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
					const auto& input = inputs[eyeIndex];
					if (!TryTemporalReuse(device, context, eyes[eyeIndex],
						colorWidth, colorHeight, guideWidth, guideHeight,
						input.motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth,
						input.motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight, tuning)) {
						reused = false;
						break;
					}
				}
				if (reused) {
					const D3D11_BOX outputBox{ 0, 0, 0, colorWidth, colorHeight, 1 };
					for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
						const auto& input = inputs[eyeIndex];
						auto& eye = eyes[eyeIndex];
						if (blendSubrect && destinationUAV) {
							FoveatedRenderImpl::Ops::BlendSubrectToOutput(eye.tiers[0].output.resource11.Get(),
								writeback, destinationUAV, input.sourceX, input.sourceY, colorWidth, colorHeight);
						} else {
							context->CopySubresourceRegion(writeback, 0, input.sourceX, input.sourceY, 0,
								eye.tiers[0].output.resource11.Get(), 0, &outputBox);
						}
						resetPending[eyeIndex][tierIndex] = false;
					}
					temporalSkippedSinceFull = true;
					AdvanceTemporalFrame(tuning);
					LogTemporalReuseActive(tuning.temporalReuseCadence);
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
					captureInfo.historyReset[eyeIndex] = resetPending[eyeIndex][tierIndex];
				}
				captureInfo.intensity = tuning.intensity;
				captureInfo.localToneStrength = tuning.localToneStrength;
				captureInfo.localStructureStrength = tuning.localStructureStrength;
				captureInfo.skinStructureStrength = tuning.skinStructureStrength;
				captureInfo.style = tuning.style;
				captureInfo.useAutoMask = tuning.useAutoMask;
				captureInfo.uiCorrection = tuning.uiCorrection;
				captureInfo.route = "feature18_stereo";
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

			ID3D12GraphicsCommandList* commandList = nullptr;
			if (!interop.BeginD3D12(&commandList)) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("BeginD3D12 stereo", interop.LastError());
			}

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
					tier.output.resource12.Get(),
					tier.reducedResolution ? modelWidth : colorWidth,
					tier.reducedResolution ? modelHeight : colorHeight,
					guideWidth, guideHeight, modelWidth, modelHeight,
					input.motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth,
					input.motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight,
					tuning, passCount, resetPending[eyeIndex][tierIndex] || temporalSkippedSinceFull);
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

			D3D11_BOX outputBox{ 0, 0, 0, colorWidth, colorHeight, 1 };
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				const auto& input = inputs[eyeIndex];
				auto& eye = eyes[eyeIndex];
				auto& tier = eye.tiers[tierIndex];
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
				ID3D11Resource* writebackOutput = neuralOutput;
				if (tuning.adaptiveResolution)
					writebackOutput = ApplyAdaptiveHandoff(device, context, eyeIndex, eye, neuralOutput, neuralOutputSRV,
						colorWidth, colorHeight, guideWidth, guideHeight,
						input.motionVectorScaleX, input.motionVectorScaleY,
						input.sourceX, input.sourceY, tuning);
				if (blendSubrect && destinationUAV) {
					// Keep the original background in `writeback` and composite the NR
					// crop over it with the same edge treatment as standard foveated DLSS.
					FoveatedRenderImpl::Ops::BlendSubrectToOutput(writebackOutput, writeback, destinationUAV,
						input.sourceX, input.sourceY, colorWidth, colorHeight);
				} else {
					context->CopySubresourceRegion(writeback, 0, input.sourceX, input.sourceY, 0,
						writebackOutput, 0, &outputBox);
				}
				resetPending[eyeIndex][tierIndex] = false;
			}
			if (IsTemporalReuseConfigured(tuning) && modelResolution == 100 && passCount == 1) {
				bool recorded = true;
				for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex)
					recorded = RecordTemporalHistory(device, context, eyes[eyeIndex],
						colorWidth, colorHeight, guideWidth, guideHeight) && recorded;
				if (!recorded)
					InvalidateTemporalHistory();
			}
			temporalSkippedSinceFull = false;
			AdvanceTemporalFrame(tuning);
#if defined(OPENNR_CAPTURE_ENABLED)
			if (captureFrame)
				globals::features::openNRCapture.EndFrame();
#endif
			return true;
		}

		void Reset()
		{
			resolveInitialized = false;
			resolveFrame = UINT32_MAX;
			interop.WaitForIdle();
			Runtime::Instance().Shutdown();
			interop.Shutdown();
			eyes = {};
			for (auto& eyeReset : resetPending)
				eyeReset.fill(true);
			failureLatched = false;
			copyDepthGuideCS.Reset();
			modelResolutionCS.Reset();
			temporalSnapshotCS.Reset();
			temporalAccumulateCS.Reset();
			temporalReprojectCS.Reset();
			adaptiveHandoffCS.Reset();
			modelResolutionCB.Reset();
			modelResolutionSampler.Reset();
			temporalReuseCB.Reset();
			temporalReuseSampler.Reset();
			temporalConfigInitialized = false;
			temporalFrameIndex = 0;
			temporalSkippedSinceFull = false;
			temporalReuseActiveLogged = false;
			temporalReuseWarningLogged = false;
		}

		void ResetHistory()
		{
			interop.WaitForIdle();
			Runtime::Instance().ResetFeatures();
			for (auto& eyeReset : resetPending)
				eyeReset.fill(true);
			InvalidateTemporalHistory();
		}

		void ClearShaderCache()
		{
			copyDepthGuideCS.Reset();
			modelResolutionCS.Reset();
			temporalSnapshotCS.Reset();
			temporalAccumulateCS.Reset();
			temporalReprojectCS.Reset();
			adaptiveHandoffCS.Reset();
		}

		[[nodiscard]] bool IsFailureLatched() const { return failureLatched; }

	private:
		bool IsTemporalReuseConfigured(const Tuning& tuning) const
		{
			return tuning.temporalReuseCadence >= kTemporalReuseMinCadence &&
				tuning.temporalReuseCadence <= kTemporalReuseMaxCadence;
		}

		void SyncTemporalReuseConfig(const Tuning& tuning, std::uint32_t modelResolution, std::uint32_t passCount)
		{
			const bool changed = !temporalConfigInitialized ||
				temporalConfigCadence != tuning.temporalReuseCadence ||
				temporalConfigDepthThreshold != tuning.temporalReuseDepthThreshold ||
				temporalConfigColorTolerance != tuning.temporalReuseColorTolerance ||
				temporalConfigModelResolution != modelResolution ||
				temporalConfigPassCount != passCount;
			if (!changed)
				return;

			temporalConfigInitialized = true;
			temporalConfigCadence = tuning.temporalReuseCadence;
			temporalConfigDepthThreshold = tuning.temporalReuseDepthThreshold;
			temporalConfigColorTolerance = tuning.temporalReuseColorTolerance;
			temporalConfigModelResolution = modelResolution;
			temporalConfigPassCount = passCount;
			InvalidateTemporalHistory();
		}

		bool CanAttemptTemporalReuse(const EyeResources& eye,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight) const
		{
			const auto& fullTier = eye.tiers[0];
			return !fullTier.reducedResolution && fullTier.passCount == 1 && eye.temporal.valid &&
				eye.temporal.width == colorWidth && eye.temporal.height == colorHeight &&
				eye.temporal.guideWidth == guideWidth && eye.temporal.guideHeight == guideHeight &&
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
			const EyeResources& eye, std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight)
		{
			if (!EnsureTemporalReuseShaders(device) || !context || !eye.color.srv11 || !eye.tiers[0].output.srv11 ||
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
			sources[1] = eye.tiers[0].output.srv11.Get();
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
				.motionScaleX = motionScaleX,
				.motionScaleY = motionScaleY,
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
			const EyeResources& eye, const TemporalEyeState& temporal,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			float depthThreshold, float colorTolerance)
		{
			if (!EnsureTemporalReuseShaders(device) || !context || !eye.color.srv11 || !eye.depth.srv11 ||
				!eye.tiers[0].output.uav11 || !temporal.base.srv || !temporal.depth.srv || !temporal.residual.srv ||
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
			targets[3] = eye.tiers[0].output.uav11.Get();
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
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight)
		{
			if (!EnsureTemporalEyeResources(device, eye, colorWidth, colorHeight, guideWidth, guideHeight) ||
				!DispatchTemporalSnapshot(device, context, eye, colorWidth, colorHeight, guideWidth, guideHeight) ||
				!eye.depth.resource11 || !eye.temporal.depth.resource)
				return false;
			context->CopyResource(eye.temporal.depth.resource.Get(), eye.depth.resource11.Get());
			const float clearValue[4]{};
			context->ClearUnorderedAccessViewFloat(eye.temporal.accumulatedMotion[0].uav.Get(), clearValue);
			context->ClearUnorderedAccessViewFloat(eye.temporal.accumulatedMotion[1].uav.Get(), clearValue);
			eye.temporal.accumulatedMotionIndex = 0;
			eye.temporal.valid = true;
			return true;
		}

		bool TryTemporalReuse(ID3D11Device* device, ID3D11DeviceContext* context, EyeResources& eye,
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
			if (!DispatchTemporalReprojection(device, context, eye, eye.temporal,
				colorWidth, colorHeight, guideWidth, guideHeight,
				tuning.temporalReuseDepthThreshold, tuning.temporalReuseColorTolerance)) {
				LogTemporalReuseFailure("residual reprojection");
				InvalidateTemporalHistory();
				return false;
			}
			return true;
		}

		void InvalidateTemporalHistory()
		{
			for (auto& eye : eyes) {
				eye.temporal.valid = false;
				eye.temporal.accumulatedMotionIndex = 0;
				// A resolution handoff uses a separate display-space history. Keep it
				// only while the adaptive route remains at the same crop/extent; a
				// normal temporal reset must invalidate it as well.
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

		void LogTemporalReuseActive(std::uint32_t cadence)
		{
			if (temporalReuseActiveLogged)
				return;
			temporalReuseActiveLogged = true;
			logger::info("[DLSSNR] experimental temporal residual reuse active cadence=N{}; full-eye exact-MV normal route only", cadence);
		}

		bool ExecuteCascade(ID3D12GraphicsCommandList* commandList, std::uint32_t eyeIndex, std::uint32_t tierIndex,
			ID3D12Resource* initialInput, ID3D12Resource* depth, ID3D12Resource* motionVectors,
			const std::array<ID3D12Resource*, kCascadePassCount - 1>& intermediates,
			ID3D12Resource* finalOutput,
			std::uint32_t firstInputWidth, std::uint32_t firstInputHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t outputWidth, std::uint32_t outputHeight,
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

			for (std::uint32_t passIndex = 0; passIndex < passCount; ++passIndex) {
				ID3D12Resource* input = passIndex == 0 ? initialInput : intermediates[passIndex - 1];
				ID3D12Resource* output = (passIndex + 1 == passCount) ? finalOutput : intermediates[passIndex];
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
				guide.motionVectorScaleX = motionVectorScaleX;
				guide.motionVectorScaleY = motionVectorScaleY;
				// Per-eye resources are isolated before this D3D12 bridge. Their
				// subrect bases therefore remain zero; only the valid extents and
				// motion-vector scale vary by route.
				guide.motionVectorsLowResolution =
					guide.motionWidth <= guide.colorWidth && guide.motionHeight <= guide.colorHeight;
				const bool succeeded = Runtime::Instance().Execute(commandList, FeatureSlot(eyeIndex, tierIndex, passIndex),
					input, depth, motionVectors, output, guide, tuning, reset);
				TransitionEvaluationResources(commandList, input, depth, motionVectors, output, false);
				if (!succeeded) {
					logger::warn("[DLSSNR] cascade pass failed eye={} pass={} of {}", eyeIndex, passIndex + 1, passCount);
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
				.sourceWidth = width,
				.sourceHeight = height,
				.transferStrength = resolveSettings.transferStrength,
				.colourStrength = resolveSettings.colourStrength,
				.maxRatio = resolveSettings.maxRatio,
				.residualStrength = resolveSettings.residualStrength,
			};
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

		bool EnsureTierResources(ID3D11Device* device, std::uint32_t eyeIndex, EyeResources& eye,
			std::uint32_t tierIndex, std::uint32_t modelWidth, std::uint32_t modelHeight,
			std::uint32_t passCount, std::uint32_t modelResolution,
			std::uint32_t resourceColorWidth, std::uint32_t resourceColorHeight)
		{
			if (!device || eyeIndex >= eyes.size() || tierIndex >= kResolutionTierCount ||
				modelWidth == 0 || modelHeight == 0 || passCount == 0 || passCount > kCascadePassCount ||
				resourceColorWidth == 0 || resourceColorHeight == 0 || !eye.sharedResourcesValid)
				return false;

			const bool reducedResolution = modelWidth != eye.colorWidth || modelHeight != eye.colorHeight;
			const bool multiPass = passCount > 1;
			const UINT sharedFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
			const auto resourceModelWidth = ScaleDimension(resourceColorWidth, modelResolution);
			const auto resourceModelHeight = ScaleDimension(resourceColorHeight, modelResolution);
			const auto modelInputDesc = MakeSharedDesc(eye.color.desc, resourceModelWidth, resourceModelHeight, sharedFlags);
			const auto outputDesc = MakeSharedDesc(eye.color.desc, resourceModelWidth, resourceModelHeight, sharedFlags);
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
			if (resourcesMatch)
				return true;

			if (tier.output.resource11 || tier.modelInput.resource11 || tier.resolved) {
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
			std::uint32_t modelResolution, bool prewarmAdaptive,
			const StereoResourceEnvelope& resourceEnvelope)
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
				eye.adaptiveTiersPrewarmed = false;
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
			if (!EnsureTierResources(device, eyeIndex, eye, tierIndex, modelWidth, modelHeight, passCount, modelResolution,
				sharedColorWidth, sharedColorHeight))
				return false;
			if (prewarmAdaptive && passCount == 1) {
				if (useEnvelope) {
					if (!eye.adaptiveTiersPrewarmed) {
						for (std::uint32_t prewarmIndex = 0; prewarmIndex < kAdaptiveTierCount; ++prewarmIndex) {
							const auto resolution = kResolutionTiers[prewarmIndex];
							if (!EnsureTierResources(device, eyeIndex, eye, prewarmIndex,
								ScaleDimension(colorWidth, resolution), ScaleDimension(colorHeight, resolution),
								1, resolution, sharedColorWidth, sharedColorHeight))
								return false;
						}
						eye.adaptiveTiersPrewarmed = true;
					}
				} else {
					// Exact-size fallback bounds residency to the active tier and
					// its likely one-step neighbors.
					const auto first = tierIndex == 0 ? 0u : tierIndex - 1;
					const auto last = std::min<std::uint32_t>(kAdaptiveTierCount - 1, tierIndex + 1);
					for (std::uint32_t residentIndex = first; residentIndex <= last; ++residentIndex) {
						const auto resolution = kResolutionTiers[residentIndex];
						if (!EnsureTierResources(device, eyeIndex, eye, residentIndex,
							ScaleDimension(colorWidth, resolution), ScaleDimension(colorHeight, resolution),
							1, resolution, sharedColorWidth, sharedColorHeight))
							return false;
					}
				}
			}
			return true;
		}

		bool LatchFailure(const char* operation, HRESULT error)
		{
			failureLatched = true;
			logger::error("[DLSSNR] {} failed hr/ngx=0x{:08X} status={} detail={}",
				operation, static_cast<std::uint32_t>(error), ToString(Runtime::Instance().Status()), Runtime::Instance().Detail());
			return false;
		}

		D3D12Interop interop;
		Util::LazyShader<ID3D11ComputeShader> copyDepthGuideCS;
		Util::LazyShader<ID3D11ComputeShader> modelResolutionCS;
		Util::LazyShader<ID3D11ComputeShader> temporalSnapshotCS;
		Util::LazyShader<ID3D11ComputeShader> temporalAccumulateCS;
		Util::LazyShader<ID3D11ComputeShader> temporalReprojectCS;
		Util::LazyShader<ID3D11ComputeShader> adaptiveHandoffCS;
		Microsoft::WRL::ComPtr<ID3D11Buffer> modelResolutionCB;
		Microsoft::WRL::ComPtr<ID3D11SamplerState> modelResolutionSampler;
		Microsoft::WRL::ComPtr<ID3D11Buffer> temporalReuseCB;
		Microsoft::WRL::ComPtr<ID3D11SamplerState> temporalReuseSampler;
		Microsoft::WRL::ComPtr<ID3D11Buffer> adaptiveHandoffCB;
		Microsoft::WRL::ComPtr<ID3D11SamplerState> adaptiveHandoffSampler;
		std::array<EyeResources, 2> eyes;
		std::array<std::array<bool, kResolutionTierCount>, 2> resetPending{};
		bool temporalConfigInitialized = false;
		std::uint32_t temporalConfigCadence = 0;
		float temporalConfigDepthThreshold = 0.05f;
		float temporalConfigColorTolerance = 0.08f;
		std::uint32_t temporalConfigModelResolution = 100;
		std::uint32_t temporalConfigPassCount = 1;
		std::uint64_t temporalFrameIndex = 0;
		bool temporalSkippedSinceFull = false;
		bool temporalReuseActiveLogged = false;
		bool temporalReuseWarningLogged = false;
		bool failureLatched = false;
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
		return state_->ApplyStereo(device, context, color, eyes,
			guideWidth, guideHeight, colorWidth, colorHeight, tuning,
				destination, destinationUAV, blendSubrect, resourceEnvelope);
	}

	void Renderer::Reset() { state_->Reset(); }
	void Renderer::ClearShaderCache() { state_->ClearShaderCache(); }
	void Renderer::ResetHistory() { state_->ResetHistory(); }
	bool Renderer::IsFailureLatched() const { return state_->IsFailureLatched(); }
	std::uint32_t Renderer::NgxResult() const { return Runtime::Instance().NgxResult(); }
	std::uint64_t Renderer::SuccessfulFrames() const { return Runtime::Instance().SuccessfulFrames(); }
	const char* Renderer::StatusText() const { return ToString(Runtime::Instance().Status()); }
}
