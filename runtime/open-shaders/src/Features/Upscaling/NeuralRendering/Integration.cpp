#include "Integration.h"

#include "Renderer.h"
#include "Features/HDRDisplay.h"
#include "Features/Upscaling.h"
#include "Features/Upscaling/FoveatedRender/Bridge.h"
#include "Features/Upscaling/FoveatedRender/Core.h"
#include "Features/Upscaling/FoveatedRender/Ops.h"
#include "Features/Upscaling/NativeOpenVRGaze.h"
#include "RuntimePolicy.h"
#include "SecondPassCrop.h"
#include "StageSplitPolicy.h"
#include "Features/Upscaling/PerfMode.h"
#include "AdaptiveQualityOrder.h"
#include "PixelCrop.h"
#include "Globals.h"
#include "GpuPass.h"
#include "State.h"

#include "RE/C/Console.h"

#include <array>
#include <atomic>
#include <algorithm>
#include <cmath>

namespace NeuralRendering
{
	namespace
	{
		eastl::unique_ptr<Texture2D> color[2];
		std::array<eastl::unique_ptr<Texture2D>, 2> eyeBlendTargets;
		struct PreUpscaleGuideResources
		{
			eastl::unique_ptr<Texture2D> depth;
			eastl::unique_ptr<Texture2D> motion;
			std::uint32_t width = 0;
			std::uint32_t height = 0;
			DXGI_FORMAT motionFormat = DXGI_FORMAT_UNKNOWN;
		};
		std::array<PreUpscaleGuideResources, 2> preUpscaleGuides;
		std::uint32_t colorWidth = 0;
		std::uint32_t colorHeight = 0;
		DXGI_FORMAT colorFormat = DXGI_FORMAT_UNKNOWN;
		std::array<std::uint32_t, 2> eyeBlendWidths{};
		std::array<std::uint32_t, 2> eyeBlendHeights{};
		std::array<DXGI_FORMAT, 2> eyeBlendFormats{ DXGI_FORMAT_UNKNOWN, DXGI_FORMAT_UNKNOWN };
		std::uint32_t lastAppliedFrame = UINT32_MAX;
		bool writebackLogged = false;
		bool flatRouteWasActive = false;
		bool flatFrameGenerationBlockLogged = false;
		bool flatHdrBlockLogged = false;
		bool blendFallbackLogged = false;
		std::atomic_bool historyResetRequested{ false };
		std::atomic_bool fullResetRequested{ false };
		bool temporalSuppressed = false;
		bool menuStateObserved = false;
		bool menuWasOpen = false;
		std::uint32_t preUpscaleAppliedFrame = UINT32_MAX;
		bool preUpscaleModeObserved = false;
		bool preUpscaleMode = false;
		bool preUpscaleBlockLogged = false;
		bool preUpscaleSuccessLogged = false;
		bool preUpscaleExecutionFailed = false;
		bool adaptiveCropHandoffDisabledLogged = false;

		bool IsGameMenuOpen()
		{
			auto* state = globals::state;
			return state && state->IsPausedOrMenuOpen(globals::game::ui);
		}

		bool IsTemporalOverlayOpen()
		{
			auto* state = globals::state;
			auto* ui = globals::game::ui;
			const bool consoleOpen = ui && ui->IsMenuOpen(RE::Console::MENU_NAME);
			// Ordinary pause/map/stats menus have a guarded camera-MV path below and
			// are safe to keep on NR. Loading and console overlays still have no
			// stable scene contract, so they remain fail-closed and reset history.
			return consoleOpen || (state && state->isLoadingMenuOpen);
		}

		ID3D11Texture2D* ResolveRenderTargetTexture(
			const RE::BSGraphics::RenderTargetData& target,
			winrt::com_ptr<ID3D11Texture2D>& holder)
		{
			if (target.texture)
				return target.texture;
			auto resolveView = [&](ID3D11View* view) -> ID3D11Texture2D* {
				if (!view)
					return nullptr;
				winrt::com_ptr<ID3D11Resource> resource;
				view->GetResource(resource.put());
				if (!resource || FAILED(resource->QueryInterface(holder.put())))
					return nullptr;
				return holder.get();
			};
			if (auto* texture = resolveView(target.SRV))
				return texture;
			return resolveView(target.RTV);
		}

		bool EnsureColorResources(ID3D11Resource* source, std::uint32_t width, std::uint32_t height)
		{
			winrt::com_ptr<ID3D11Texture2D> sourceTexture;
			if (!source || FAILED(source->QueryInterface(sourceTexture.put())))
				return false;
			D3D11_TEXTURE2D_DESC sourceDesc{};
			sourceTexture->GetDesc(&sourceDesc);
			if (color[0] && colorWidth == width && colorHeight == height && colorFormat == sourceDesc.Format)
				return true;
			const std::uint32_t resourceCount = globals::game::isVR ? 2u : 1u;
			for (std::uint32_t eye = 0; eye < resourceCount; ++eye) {
				color[eye] = Upscaling::CreateTextureFromSource(source, width, height, false, true, true,
					eye == 0 ? "NeuralRendering::LdrColorLeft" : "NeuralRendering::LdrColorRight");
				if (!color[eye])
					return false;
			}
			if (!globals::game::isVR)
				color[1].reset();
			colorWidth = width;
			colorHeight = height;
			colorFormat = sourceDesc.Format;
			return true;
		}

		bool EnsureEyeBlendTarget(ID3D11Resource* source, std::uint32_t eye,
			std::uint32_t width, std::uint32_t height)
		{
			if (!source || eye >= eyeBlendTargets.size() || width == 0 || height == 0)
				return false;

			winrt::com_ptr<ID3D11Texture2D> sourceTexture;
			if (FAILED(source->QueryInterface(sourceTexture.put())))
				return false;
			D3D11_TEXTURE2D_DESC sourceDesc{};
			sourceTexture->GetDesc(&sourceDesc);
			auto& target = eyeBlendTargets[eye];
			if (target && eyeBlendWidths[eye] == width && eyeBlendHeights[eye] == height &&
				eyeBlendFormats[eye] == sourceDesc.Format && target->uav)
				return true;

			const char* name = eye == 0 ? "NeuralRendering::FoveatedBlendCropLeft" :
				"NeuralRendering::FoveatedBlendCropRight";
			target = Upscaling::CreateTextureFromSource(source, width, height, false, true, true, name);
			if (!target || !target->uav)
				return false;
			eyeBlendWidths[eye] = width;
			eyeBlendHeights[eye] = height;
			eyeBlendFormats[eye] = sourceDesc.Format;
			return true;
		}

		PixelCrop GetPixelCrop(const Util::Subrect::UVRegion& uv, std::uint32_t width, std::uint32_t height)
		{
			return ComputePixelCrop(uv.x, uv.y, uv.w, uv.h, width, height);
		}

		Util::Subrect::UVRegion ScaleCropAroundCenter(Util::Subrect::UVRegion uv, std::uint32_t coveragePercent)
		{
			const float scale = std::clamp(static_cast<float>(coveragePercent) / 100.0f, 0.01f, 1.0f);
			const float centerX = uv.x + uv.w * 0.5f;
			const float centerY = uv.y + uv.h * 0.5f;
			uv.w *= scale;
			uv.h *= scale;
			uv.x = std::clamp(centerX - uv.w * 0.5f, 0.0f, 1.0f - uv.w);
			uv.y = std::clamp(centerY - uv.h * 0.5f, 0.0f, 1.0f - uv.h);
			return uv;
		}

		bool EnsurePreUpscaleGuideResources(std::uint32_t eye, std::uint32_t width,
			std::uint32_t height, DXGI_FORMAT motionFormat)
		{
			if (eye >= preUpscaleGuides.size() || !width || !height ||
				motionFormat == DXGI_FORMAT_UNKNOWN || !globals::d3d::device)
				return false;
			auto& resources = preUpscaleGuides[eye];
			if (resources.depth && resources.motion && resources.width == width && resources.height == height &&
				resources.motionFormat == motionFormat)
				return true;

			resources.depth.reset();
			resources.motion.reset();
			resources.width = resources.height = 0;
			resources.motionFormat = DXGI_FORMAT_UNKNOWN;
			D3D11_TEXTURE2D_DESC depthDesc{};
			depthDesc.Width = width;
			depthDesc.Height = height;
			depthDesc.MipLevels = 1;
			depthDesc.ArraySize = 1;
			depthDesc.Format = DXGI_FORMAT_R32_TYPELESS;
			depthDesc.SampleDesc.Count = 1;
			depthDesc.Usage = D3D11_USAGE_DEFAULT;
			depthDesc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
			winrt::com_ptr<ID3D11Texture2D> depthTexture;
			if (FAILED(globals::d3d::device->CreateTexture2D(&depthDesc, nullptr, depthTexture.put())))
				return false;
			const char* depthName = eye == 0 ? "NeuralRendering::PreUpscaleDepthLeft" : "NeuralRendering::PreUpscaleDepthRight";
			resources.depth = eastl::make_unique<Texture2D>(depthTexture.detach(), depthName);
			D3D11_SHADER_RESOURCE_VIEW_DESC depthSRV{};
			depthSRV.Format = DXGI_FORMAT_R32_FLOAT;
			depthSRV.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
			depthSRV.Texture2D.MipLevels = 1;
			if (FAILED(globals::d3d::device->CreateShaderResourceView(resources.depth->resource.get(),
				&depthSRV, resources.depth->srv.put()))) {
				resources.depth.reset();
				return false;
			}
			D3D11_UNORDERED_ACCESS_VIEW_DESC depthUAV{};
			depthUAV.Format = DXGI_FORMAT_R32_FLOAT;
			depthUAV.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
			if (FAILED(globals::d3d::device->CreateUnorderedAccessView(resources.depth->resource.get(),
				&depthUAV, resources.depth->uav.put()))) {
				resources.depth.reset();
				return false;
			}
			Util::SetResourceName(resources.depth->srv.get(), eye == 0 ? "NeuralRendering::PreUpscaleDepthLeft SRV" : "NeuralRendering::PreUpscaleDepthRight SRV");
			Util::SetResourceName(resources.depth->uav.get(), eye == 0 ? "NeuralRendering::PreUpscaleDepthLeft UAV" : "NeuralRendering::PreUpscaleDepthRight UAV");

			D3D11_TEXTURE2D_DESC motionDesc{};
			motionDesc.Width = width;
			motionDesc.Height = height;
			motionDesc.MipLevels = 1;
			motionDesc.ArraySize = 1;
			motionDesc.Format = motionFormat;
			motionDesc.SampleDesc.Count = 1;
			motionDesc.Usage = D3D11_USAGE_DEFAULT;
			motionDesc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
			winrt::com_ptr<ID3D11Texture2D> motionTexture;
			if (FAILED(globals::d3d::device->CreateTexture2D(&motionDesc, nullptr, motionTexture.put()))) {
				resources.depth.reset();
				return false;
			}
			const char* motionName = eye == 0 ? "NeuralRendering::PreUpscaleMotionLeft" : "NeuralRendering::PreUpscaleMotionRight";
			resources.motion = eastl::make_unique<Texture2D>(motionTexture.detach(), motionName);
			D3D11_SHADER_RESOURCE_VIEW_DESC motionSRV{};
			motionSRV.Format = motionFormat;
			motionSRV.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
			motionSRV.Texture2D.MipLevels = 1;
			if (FAILED(globals::d3d::device->CreateShaderResourceView(resources.motion->resource.get(),
				&motionSRV, resources.motion->srv.put()))) {
				resources.depth.reset();
				resources.motion.reset();
				return false;
			}
			Util::SetResourceName(resources.motion->srv.get(), eye == 0 ? "NeuralRendering::PreUpscaleMotionLeft SRV" : "NeuralRendering::PreUpscaleMotionRight SRV");
			resources.width = width;
			resources.height = height;
			resources.motionFormat = motionFormat;
			return true;
		}

		Tuning GetTuning(const FoveatedRender& foveated, bool adaptiveEligible)
		{
			const auto& settings = foveated.settings;
			const bool adaptive = adaptiveEligible && settings.neuralRenderingAdaptiveEnabled &&
				foveated.adaptiveController.IsEnabled();
			const bool adaptiveCrop = adaptive && foveated.IsAdaptiveCropRuntimeActive();
			const auto& controller = foveated.adaptiveController;
			const auto requestedPassMode = std::min(settings.neuralRenderingMultiPass, 2u);
			const auto activePassMode = settings.neuralRenderingPreUpscale == 0 ?
				foveated.GetEffectiveMultiPassMode() : 0u;
			const auto leftUV = foveated.subrectController.GetUV();
			const auto rightUV = foveated.subrectController.GetRightEyeUV();
			const bool geometryCompatible = std::abs(leftUV.w - rightUV.w) <= 0.0005f &&
				std::abs(leftUV.h - rightUV.h) <= 0.0005f;
			const auto configuredCrop = static_cast<std::uint32_t>(std::lround(std::clamp(
				std::min({ leftUV.w, leftUV.h, rightUV.w, rightUV.h }) * 100.0f, 0.0f, 100.0f)));
			const auto cropMaximum = std::min(settings.neuralRenderingAdaptiveCropMaximumCoverage, configuredCrop);
			const auto cropMinimum = std::min(settings.neuralRenderingAdaptiveCropMinimumCoverage, cropMaximum);
			const bool passesCanDown = adaptive && foveated.adaptivePassController.CanDecrease(requestedPassMode);
			const bool cropCanDown = adaptive && settings.neuralRenderingAdaptiveCropEnabled && geometryCompatible &&
				!FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected &&
				!FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected && configuredCrop >= 30 &&
				(foveated.IsAdaptiveCropRuntimeActive() ?
					foveated.adaptiveCropController.ActiveCoverage() > foveated.adaptiveCropController.MinimumCoverage() :
					cropMaximum > cropMinimum);
			const bool resolutionCanDown = adaptive && !controller.IsAtMinimum();
			const auto downshiftAxis = SelectAdaptiveDownshift(settings.neuralRenderingAdaptiveQualityOrder,
				passesCanDown, cropCanDown, resolutionCanDown);
			const bool passesCanUp = adaptive && foveated.adaptivePassController.CanIncrease(requestedPassMode);
			const bool cropCanUp = adaptive && settings.neuralRenderingAdaptiveCropEnabled &&
				foveated.IsAdaptiveCropRuntimeActive() &&
				foveated.adaptiveCropController.ActiveCoverage() < foveated.adaptiveCropController.MaximumCoverage();
			const bool resolutionCanUp = adaptive && !controller.IsAtMaximum();
			const auto upshiftAxis = SelectAdaptiveUpshift(settings.neuralRenderingAdaptiveQualityOrder,
				passesCanUp, cropCanUp, resolutionCanUp);
			const int prewarmDirection = !adaptive || foveated.IsAdaptiveCropTransitioning() ? 0 :
				controller.LastSampleOverBudget() && downshiftAxis == AdaptiveQualityAxis::Resolution ? -1 :
				controller.LastSampleHadHeadroom() && upshiftAxis == AdaptiveQualityAxis::Resolution ? 1 : 0;
			return {
				.intensity = settings.neuralRenderingIntensity,
				.localToneStrength = settings.neuralRenderingLocalTone,
				.localStructureStrength = settings.neuralRenderingLocalStructure,
				.skinStructureStrength = settings.neuralRenderingSkinStructure,
				.style = settings.neuralRenderingStyle,
				.useAutoMask = settings.neuralRenderingAutoMask,
				.uiCorrection = settings.neuralRenderingUICorrection,
				.modelResolutionPercent = adaptive ? controller.ActiveResolution() : settings.neuralRenderingModelResolution,
				.modelResolveMode = settings.neuralRenderingResolveMode,
				.multiPass = activePassMode,
				.secondPassContribution = settings.neuralRenderingSecondPassContribution,
				.secondPassCropReductionX = settings.neuralRenderingSecondPassCropReductionX,
				.secondPassCropReductionY = settings.neuralRenderingSecondPassCropReductionY,
				.secondPassBlendMode = settings.neuralRenderingSecondPassBlendMode,
				.secondPassMaskMode = settings.neuralRenderingSecondPassMaskMode,
				.secondPassFeatherWidth = settings.neuralRenderingSecondPassFeatherWidth,
				.secondPassFalloffCurve = settings.neuralRenderingSecondPassFalloffCurve,
				.secondPassDitherStrength = settings.neuralRenderingSecondPassDitherStrength,
				.adaptiveMaxPassCount = requestedPassMode + 1,
				.temporalReuseCadence = (adaptive || !globals::game::isVR || settings.neuralRenderingPreUpscale != 0 ||
					settings.neuralRenderingMultiPass != 0) ? 0u : settings.neuralRenderingTemporalReuseCadence,
				.temporalReuseDepthThreshold = settings.neuralRenderingTemporalDepthThreshold,
				.temporalReuseColorTolerance = settings.neuralRenderingTemporalColorTolerance,
				.temporalReuseResetAfterSkip = settings.neuralRenderingTemporalReuseResetAfterSkip,
				.adaptiveResolution = adaptive,
				.adaptiveHandoff = !adaptiveCrop,
				.adaptiveHandoffAlpha = adaptive ? controller.HandoffAlpha() : 1.0f,
				.adaptiveDepthThreshold = adaptive ? settings.neuralRenderingTemporalDepthThreshold : 0.05f,
				.adaptivePrewarmDirection = prewarmDirection,
				.adaptiveMemoryCeiling = adaptive ? controller.MemoryCeiling() : 100u,
				.nrContribution = settings.neuralRenderingNRContribution,
				.detailBoost = settings.neuralRenderingDetailBoost,
			};
		}

		void LogPreUpscaleBlocked(const char* reason)
		{
			if (!preUpscaleBlockLogged) {
				logger::warn("[DLSSNR] experimental pre-upscale route unavailable ({}); falling back to post-upscale NR", reason);
				preUpscaleBlockLogged = true;
			}
		}

		void RestoreRenderTargets(ID3D11DeviceContext* context,
			ID3D11RenderTargetView* (&savedRTVs)[D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT],
			ID3D11DepthStencilView* savedDSV)
		{
			context->OMSetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, savedRTVs, savedDSV);
			for (auto*& rtv : savedRTVs)
				if (rtv)
					rtv->Release();
			if (savedDSV)
				savedDSV->Release();
		}

		bool ApplyFlatLdr(Upscaling& upscaling, FoveatedRender& foveated)
		{
			const bool frameGenerationConfigured = upscaling.IsFrameGenerationConfiguredForSession();
			const bool hdrConfigured = globals::features::hdrDisplay.loaded &&
				globals::features::hdrDisplay.settings.enableHDR;
			auto* renderer = globals::game::renderer;
			winrt::com_ptr<ID3D11Texture2D> framebufferHolder;
			ID3D11Texture2D* framebuffer = nullptr;
			if (renderer) {
				auto& target = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kFRAMEBUFFER];
				framebuffer = ResolveRenderTargetTexture(target, framebufferHolder);
			}
			const bool routeActive = upscaling.GetUpscaleMethod() == Upscaling::UpscaleMethod::kDLSS &&
				foveated.settings.neuralRenderingEnabled && !frameGenerationConfigured && !hdrConfigured;
			if (!routeActive) {
				if (foveated.settings.neuralRenderingEnabled && frameGenerationConfigured && !flatFrameGenerationBlockLogged) {
					logger::warn("[DLSSNR] Flat route blocked: disable Frame Generation and restart the game");
					flatFrameGenerationBlockLogged = true;
				}
				if (foveated.settings.neuralRenderingEnabled && hdrConfigured && !flatHdrBlockLogged) {
					logger::warn("[DLSSNR] Flat route blocked: HDR Display is not supported by the LDR integration");
					flatHdrBlockLogged = true;
				}
				if (flatRouteWasActive)
					Reset();
				return false;
			}
			flatRouteWasActive = true;

			const std::uint32_t frame = globals::state ? globals::state->frameCount : 0;
			const bool preStageAppliedThisFrame = preUpscaleAppliedFrame == frame;
			const auto requestedPassMode = std::min(foveated.settings.neuralRenderingMultiPass, 2u);
			const auto stagePlan = ResolveStageSplitPlan(foveated.settings.neuralRenderingPreUpscale != 0,
				preStageAppliedThisFrame, requestedPassMode, requestedPassMode);
			if (!stagePlan.runPostStage)
				return false;
			if (lastAppliedFrame == frame)
				return true;
			auto* context = globals::d3d::context;
			if (!renderer || !context || !globals::d3d::device || !upscaling.motionVectorCopyTexture)
				return false;

			auto& depth = renderer->GetDepthStencilData().depthStencils[RE::RENDER_TARGETS_DEPTHSTENCIL::kMAIN];
			if (!framebuffer || !depth.texture || !depth.depthSRV || !upscaling.motionVectorCopyTexture->resource)
				return false;

			D3D11_TEXTURE2D_DESC totalDesc{};
			D3D11_TEXTURE2D_DESC motionDesc{};
			framebuffer->GetDesc(&totalDesc);
			upscaling.motionVectorCopyTexture->resource->GetDesc(&motionDesc);
			if (!EnsureColorResources(framebuffer, totalDesc.Width, totalDesc.Height))
				return false;

			CS_GPU_PASS("NeuralRendering::FlatLdrBeforeUI");
			ID3D11RenderTargetView* savedRTVs[D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT]{};
			ID3D11DepthStencilView* savedDSV = nullptr;
			context->OMGetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, savedRTVs, &savedDSV);
			context->OMSetRenderTargets(0, nullptr, nullptr);
			context->CopyResource(color[0]->resource.get(), framebuffer);

			Tuning tuning = GetTuning(foveated, false);
			if (foveated.settings.neuralRenderingPreUpscale != 0) {
				tuning.multiPass = stagePlan.postMultiPassMode;
				tuning.adaptiveMaxPassCount = stagePlan.postResourcePassCount;
			}
			const bool succeeded = Renderer::Instance().Apply(globals::d3d::device, context, 0,
				color[0]->resource.get(), depth.texture, depth.depthSRV,
				upscaling.motionVectorCopyTexture->resource.get(), motionDesc.Width, motionDesc.Height,
				totalDesc.Width, totalDesc.Height, static_cast<float>(motionDesc.Width),
				static_cast<float>(motionDesc.Height), tuning);
			if (succeeded) {
				context->CopyResource(framebuffer, color[0]->resource.get());
				lastAppliedFrame = frame;
				if (!writebackLogged) {
					logger::info("[DLSSNR] Flat LDR kFRAMEBUFFER output written before UI guides={}x{} color={}x{}",
						motionDesc.Width, motionDesc.Height, totalDesc.Width, totalDesc.Height);
					writebackLogged = true;
				}
			}

			context->OMSetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, savedRTVs, savedDSV);
			for (auto*& rtv : savedRTVs)
				if (rtv) rtv->Release();
			if (savedDSV) savedDSV->Release();
			return succeeded;
		}
	}

	void ResetHistory()
	{
		Renderer::Instance().ResetHistory();
		Renderer::PreUpscaleInstance().ResetHistory();
		lastAppliedFrame = UINT32_MAX;
		preUpscaleAppliedFrame = UINT32_MAX;
	}

	void RequestHistoryReset()
	{
		historyResetRequested.store(true, std::memory_order_release);
	}

	bool IsPreUpscaleExecutionFailed()
	{
		return preUpscaleExecutionFailed;
	}

	void UpdateFrameState()
	{
		static std::uint32_t resetCheckedFrame = UINT32_MAX;
		const auto currentFrame = globals::state ? globals::state->frameCount : 0;
		const bool firstUpdate = resetCheckedFrame != currentFrame;
		resetCheckedFrame = currentFrame;
		if (firstUpdate && fullResetRequested.exchange(false, std::memory_order_acq_rel)) {
			Reset();
			if (Renderer::Instance().IsFailureLatched() || Renderer::PreUpscaleInstance().IsFailureLatched())
				return;
			auto& streamline = globals::features::upscaling.streamline;
			streamline.DestroyDLSSResources();
			streamline.lastDLSSFailureFrame = UINT32_MAX;
			streamline.lastVRAMPressureFrame = UINT32_MAX;
			FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected = false;
			FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected = false;
			FoveatedRenderImpl::Core::activeSubrectUVHash = 0;
			FoveatedRenderImpl::Core::InvalidateTemporalState();
			logger::info("[DLSSNR] Manual reset completed on render thread; DLSS and adaptive crop rearmed");
		}
		const bool menuOpen = IsGameMenuOpen();
		const bool overlayOpen = IsTemporalOverlayOpen();
		const bool requested = historyResetRequested.exchange(false, std::memory_order_acq_rel);
		const bool requestedPreUpscale = globals::features::upscaling.foveatedRender.settings.neuralRenderingPreUpscale != 0;
		bool stageChanged = false;
		bool menuChanged = false;
		if (!menuStateObserved) {
			menuStateObserved = true;
			menuWasOpen = menuOpen;
		} else if (menuWasOpen != menuOpen) {
			menuWasOpen = menuOpen;
			menuChanged = true;
		}
		if (!preUpscaleModeObserved) {
			preUpscaleModeObserved = true;
			preUpscaleMode = requestedPreUpscale;
		} else if (preUpscaleMode != requestedPreUpscale) {
			preUpscaleMode = requestedPreUpscale;
			stageChanged = true;
		}
		if (stageChanged) {
			preUpscaleBlockLogged = false;
			preUpscaleExecutionFailed = false;
		}
		if (!requested && overlayOpen == temporalSuppressed && !stageChanged && !menuChanged)
			return;

		temporalSuppressed = overlayOpen;
		if (menuChanged) {
			// Menu entry/exit changes the motion-vector contract. Invalidate both
			// the neural history and the foveated periphery history, but do not
			// suppress the ordinary menu route itself.
			FoveatedRenderImpl::Core::InvalidateTemporalState();
		} else {
			ResetHistory();
		}
		const char* resetReason = stageChanged ? "NR stage changed" :
			menuChanged ? (menuOpen ? "menu open" : "menu closed") :
			requested ? "event" : (overlayOpen ? "overlay open" : "overlay closed");
		logger::info("[DLSSNR] Temporal history reset ({})",
			resetReason);
	}

	bool ApplyPreUpscale()
	{
		UpdateFrameState();
		// The pre-upscale hook runs before Upscale() has installed the guarded
		// menu motion-vector fallback. Keep this experimental stage out of menus;
		// post-upscale NR is allowed once those inputs have been prepared.
		if (temporalSuppressed || IsGameMenuOpen())
			return false;

		auto& upscaling = globals::features::upscaling;
		auto& foveated = upscaling.foveatedRender;
		if (!foveated.settings.neuralRenderingEnabled || foveated.settings.neuralRenderingPreUpscale == 0)
			return false;
		if (preUpscaleExecutionFailed) {
			LogPreUpscaleBlocked("the previous pre-NR execution failed; toggle the option to retry");
			return false;
		}

		const std::uint32_t frame = globals::state ? globals::state->frameCount : 0;
		if (preUpscaleAppliedFrame == frame)
			return true;

		const bool frameGenerationConfigured = upscaling.IsFrameGenerationConfiguredForSession();
		const bool hdrConfigured = globals::features::hdrDisplay.loaded &&
			globals::features::hdrDisplay.settings.enableHDR;
		if (upscaling.GetUpscaleMethod() != Upscaling::UpscaleMethod::kDLSS) {
			LogPreUpscaleBlocked("DLSS is not the selected upscaler");
			return false;
		}
		if (frameGenerationConfigured || upscaling.IsFrameGenerationActive()) {
			LogPreUpscaleBlocked("Frame Generation is enabled");
			return false;
		}
		if (hdrConfigured) {
			LogPreUpscaleBlocked("HDR Display uses the unsupported HDR integration");
			return false;
		}

		auto* renderer = globals::game::renderer;
		auto* context = globals::d3d::context;
		if (!renderer || !context || !globals::d3d::device) {
			LogPreUpscaleBlocked("D3D or renderer resources are not ready");
			return false;
		}

		auto& main = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kMAIN];
		auto& motionVector = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kMOTION_VECTOR];
		auto& depth = renderer->GetDepthStencilData().depthStencils[RE::RENDER_TARGETS_DEPTHSTENCIL::kMAIN];
		if (!main.texture || !motionVector.texture || !depth.texture || !depth.depthSRV) {
			LogPreUpscaleBlocked("native color/depth/motion guide resources are missing");
			return false;
		}

		D3D11_TEXTURE2D_DESC colorDesc{};
		D3D11_TEXTURE2D_DESC motionDesc{};
		main.texture->GetDesc(&colorDesc);
		motionVector.texture->GetDesc(&motionDesc);
		if (colorDesc.Width == 0 || colorDesc.Height == 0 ||
			(globals::game::isVR && (colorDesc.Width < 2 || (colorDesc.Width & 1u) != 0)) ||
			motionDesc.Width == 0 || motionDesc.Height == 0) {
			LogPreUpscaleBlocked("native stereo dimensions are invalid");
			return false;
		}
		if (Renderer::PreUpscaleInstance().IsFailureLatched()) {
			LogPreUpscaleBlocked("the shared NR renderer has an existing failure latch");
			return false;
		}

		ID3D11RenderTargetView* savedRTVs[D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT]{};
		ID3D11DepthStencilView* savedDSV = nullptr;
		context->OMGetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, savedRTVs, &savedDSV);
		context->OMSetRenderTargets(0, nullptr, nullptr);

		// Keep pre-SR history and resources isolated from the post-SR stage. When
		// sequential NR is selected, this one evaluation is pass one; the later
		// foveated hook runs the remaining pass or passes after the upscaler.
		foveated.UpdateAdaptiveState(frame, true);
		Tuning tuning = GetTuning(foveated, true);
		tuning.temporalReuseCadence = 0;
		bool succeeded = false;
		if (!globals::game::isVR) {
			CS_GPU_PASS("NeuralRendering::FlatPreUpscale");
			succeeded = Renderer::PreUpscaleInstance().Apply(globals::d3d::device, context, 0,
				main.texture, depth.texture, depth.depthSRV, motionVector.texture,
				motionDesc.Width, motionDesc.Height, colorDesc.Width, colorDesc.Height,
				static_cast<float>(motionDesc.Width), static_cast<float>(motionDesc.Height), tuning);
		} else {
			if (!FoveatedRenderImpl::Bridge::IsRouteActive()) {
				LogPreUpscaleBlocked("VR foveated route is not active");
			} else if (foveated.GetDlssMode() != FoveatedRender::DlssMode::kDefault) {
				LogPreUpscaleBlocked("VR Faster mode does not provide the isolated pre-NR guide contract");
			} else {
				const std::uint32_t eyeWidth = colorDesc.Width / 2;
				const std::uint32_t eyeHeight = colorDesc.Height;
				D3D11_TEXTURE2D_DESC depthDesc{};
				depth.texture->GetDesc(&depthDesc);
				const auto gazeConfig = FoveatedRenderImpl::NativeOpenVRGaze::Config{
					.enabled = foveated.settings.neuralRenderingEyeTrackedFoveation,
					.smoothingMs = foveated.settings.neuralRenderingEyeTrackedSmoothingMs,
					.policy = foveated.settings.neuralRenderingEyeTrackedPolicy,
					.catchupMs = foveated.settings.neuralRenderingEyeTrackedCatchupMs,
					.deadbandPixels = foveated.settings.neuralRenderingEyeTrackedDeadbandPixels,
					.holdMs = foveated.settings.neuralRenderingEyeTrackedHoldMs,
					.predictionMs = foveated.settings.neuralRenderingEyeTrackedPredictionMs,
					.quantizationPixels = foveated.settings.neuralRenderingEyeTrackedQuantizationPixels,
					.cropPaddingPixels = foveated.settings.neuralRenderingEyeTrackedCropPaddingPixels,
				};
				const auto baseLeftUV = foveated.GetEffectiveLeftUV();
				const auto baseRightUV = foveated.GetEffectiveRightUV();
				const bool gazeRequested = gazeConfig.enabled && foveated.settings.neuralRenderingEnabled &&
					foveated.GetDlssMode() == FoveatedRender::DlssMode::kDefault &&
					upscaling.GetUpscaleMethod() == Upscaling::UpscaleMethod::kDLSS;
				const auto gaze = FoveatedRenderImpl::NativeOpenVRGaze::ResolveForFrame(
					gazeConfig, baseLeftUV, baseRightUV, eyeWidth, eyeHeight, frame,
					gazeRequested && FoveatedRenderImpl::NativeOpenVRGaze::IsDynamicGazeAllowed());
				const auto cropCoverage = foveated.settings.neuralRenderingPreUpscaleCropCoverage;
				const auto leftUV = cropCoverage == 0 ? Util::Subrect::UVRegion{ 0.0f, 0.0f, 1.0f, 1.0f } :
					ScaleCropAroundCenter(gaze.leftUV, cropCoverage);
				const auto rightUV = cropCoverage == 0 ? Util::Subrect::UVRegion{ 0.0f, 0.0f, 1.0f, 1.0f } :
					ScaleCropAroundCenter(gaze.rightUV, cropCoverage);
				const bool useFullEyeGuides = leftUV.IsFullEye() && rightUV.IsFullEye();
				if (leftUV.w != rightUV.w || leftUV.h != rightUV.h ||
					depthDesc.Width < 2 || (depthDesc.Width & 1u) != 0 ||
					motionDesc.Width < 2 || (motionDesc.Width & 1u) != 0) {
					LogPreUpscaleBlocked("per-eye pre-NR crop extents are incompatible");
				} else if (useFullEyeGuides && !FoveatedRenderImpl::Core::PrepareVRPerEyeInputs(
						main.texture, depth.texture, motionVector.texture, nullptr, nullptr,
						eyeWidth, eyeHeight, eyeWidth, eyeHeight)) {
					LogPreUpscaleBlocked("per-eye pre-NR guide preparation failed");
				} else {
					std::array<Renderer::StereoEyeInput, 2> inputs{};
					std::uint32_t colorCropWidth = 0;
					std::uint32_t colorCropHeight = 0;
					std::uint32_t guideCropWidth = 0;
					std::uint32_t guideCropHeight = 0;
					const Util::Subrect::UVRegion* cropUVs[2]{ &leftUV, &rightUV };
					const std::uint32_t depthEyeWidth = depthDesc.Width / 2;
					const std::uint32_t motionEyeWidth = motionDesc.Width / 2;
					bool guidesReady = true;
					for (std::uint32_t eye = 0; eye < 2; ++eye) {
						auto& depthGuide = FoveatedRenderImpl::Core::vrIntermediateDepth[eye];
						auto& motionGuide = FoveatedRenderImpl::Core::vrIntermediateMotionVectors[eye];
						if (useFullEyeGuides) {
							if (!depthGuide || !motionGuide) {
								guidesReady = false;
								break;
							}
							inputs[eye] = {
								.depth = depthGuide->resource.get(),
								.depthSRV = depthGuide->srv.get(),
								.motionVectors = motionGuide->resource.get(),
								.sourceX = eye * eyeWidth,
								.sourceY = 0,
								.motionVectorScaleX = 1.0f,
								.motionVectorScaleY = 1.0f,
							};
							colorCropWidth = eyeWidth;
							colorCropHeight = eyeHeight;
							guideCropWidth = eyeWidth;
							guideCropHeight = eyeHeight;
							continue;
						}

						const auto colorCrop = GetPixelCrop(*cropUVs[eye], eyeWidth, eyeHeight);
						const auto depthCrop = GetPixelCrop(*cropUVs[eye], depthEyeWidth, depthDesc.Height);
						const auto motionCrop = GetPixelCrop(*cropUVs[eye], motionEyeWidth, motionDesc.Height);
						if (eye == 0) {
							colorCropWidth = colorCrop.width;
							colorCropHeight = colorCrop.height;
							guideCropWidth = depthCrop.width;
							guideCropHeight = depthCrop.height;
						} else if (colorCrop.width != colorCropWidth || colorCrop.height != colorCropHeight ||
							depthCrop.width != guideCropWidth || depthCrop.height != guideCropHeight ||
							motionCrop.width != guideCropWidth || motionCrop.height != guideCropHeight) {
							guidesReady = false;
							break;
						}
						if (depthCrop.width != motionCrop.width || depthCrop.height != motionCrop.height ||
							!EnsurePreUpscaleGuideResources(eye, depthCrop.width, depthCrop.height, motionDesc.Format)) {
							guidesReady = false;
							break;
						}
						auto& guideResources = preUpscaleGuides[eye];
						const std::uint32_t depthSourceX = eye * depthEyeWidth + depthCrop.x;
						if (!FoveatedRenderImpl::Ops::CopyDepthRegionToTexture(depth.texture, depth.depthSRV,
							guideResources.depth->uav.get(), depthSourceX, depthCrop.y,
							depthCrop.width, depthCrop.height)) {
							guidesReady = false;
							break;
						}
						const std::uint32_t motionSourceX = eye * motionEyeWidth + motionCrop.x;
						const D3D11_BOX motionBox{ motionSourceX, motionCrop.y, 0,
							motionSourceX + motionCrop.width, motionCrop.y + motionCrop.height, 1 };
						context->CopySubresourceRegion(guideResources.motion->resource.get(), 0, 0, 0, 0,
							motionVector.texture, 0, &motionBox);
						inputs[eye] = {
							.depth = guideResources.depth->resource.get(),
							.depthSRV = guideResources.depth->srv.get(),
							.motionVectors = guideResources.motion->resource.get(),
							.sourceX = eye * eyeWidth + colorCrop.x,
							.sourceY = colorCrop.y,
							.motionVectorScaleX = static_cast<float>(eyeWidth),
							.motionVectorScaleY = static_cast<float>(eyeHeight),
							.compensateCropMotion = gaze.dynamic,
						};
					}
					if (!guidesReady || !inputs[0].depth || !inputs[1].depth ||
						!inputs[0].motionVectors || !inputs[1].motionVectors) {
						LogPreUpscaleBlocked("per-eye pre-NR crop guides could not be prepared");
					} else {
						if (gaze.historyReset)
							Renderer::PreUpscaleInstance().ResetHistory();
						CS_GPU_PASS("NeuralRendering::StereoPreUpscale");
						succeeded = Renderer::PreUpscaleInstance().ApplyStereo(globals::d3d::device, context,
							main.texture, inputs, guideCropWidth, guideCropHeight,
							colorCropWidth, colorCropHeight, tuning,
							main.texture, main.UAV, !useFullEyeGuides);
					}
				}
			}
		}

		RestoreRenderTargets(context, savedRTVs, savedDSV);
		if (!succeeded) {
			// The experimental stage must not poison the established post-upscale
			// route. Reset the shared renderer after a pre-stage execution failure;
			// the later UI-composite hook can initialize it again for fallback.
			Renderer::PreUpscaleInstance().Reset();
			preUpscaleExecutionFailed = true;
			LogPreUpscaleBlocked("pre-NR execution failed; renderer reset for fallback");
			return false;
		}

		preUpscaleAppliedFrame = frame;
		preUpscaleBlockLogged = false;
		preUpscaleExecutionFailed = false;
		if (!preUpscaleSuccessLogged) {
			logger::info("[DLSSNR] experimental pre-upscale route active; stage=before-dlss vr={} model={} resolve={}",
				globals::game::isVR, foveated.settings.neuralRenderingModelResolution,
				foveated.settings.neuralRenderingResolveMode == 1 ? "matched-residual" : "classic");
			preUpscaleSuccessLogged = true;
		}
		return true;
	}

	bool ApplyFoveatedLdr()
	{
		UpdateFrameState();
		if (temporalSuppressed)
			return false;

		auto& upscaling = globals::features::upscaling;
		auto& foveated = upscaling.foveatedRender;
		if (!globals::game::isVR)
			return ApplyFlatLdr(upscaling, foveated);
		if (!globals::game::isVR || !FoveatedRenderImpl::Bridge::IsRouteActive() ||
			upscaling.GetUpscaleMethod() != Upscaling::UpscaleMethod::kDLSS ||
			foveated.GetDlssMode() != FoveatedRender::DlssMode::kDefault ||
			!foveated.settings.neuralRenderingEnabled || upscaling.IsFrameGenerationActive())
			return false;

		const std::uint32_t frame = globals::state ? globals::state->frameCount : 0;
		const bool preStageAppliedThisFrame = preUpscaleAppliedFrame == frame;
		if (preStageAppliedThisFrame && foveated.settings.neuralRenderingMultiPass == 0)
			return false;
		const std::uint32_t guideFrame = FoveatedRenderImpl::Core::neuralGuidesFrame;
		if (lastAppliedFrame == frame || (guideFrame != frame && !(frame > 0 && guideFrame == frame - 1)))
			return false;
		// The controller samples the host-frame interval here, immediately before
		// choosing the native tier used by this frame. Calling it again from the
		// foveated hook is harmless because it is frame-idempotent.
		foveated.UpdateAdaptiveState(frame, true);
		const auto activePassMode = foveated.GetEffectiveMultiPassMode();
		const auto requestedPassMode = std::min(foveated.settings.neuralRenderingMultiPass, 2u);
		const auto stagePlan = ResolveStageSplitPlan(foveated.settings.neuralRenderingPreUpscale != 0,
			preStageAppliedThisFrame, activePassMode, requestedPassMode);
		if (!stagePlan.runPostStage)
			return false;
		const bool splitPostStage = stagePlan.runPreStage;

		auto* renderer = globals::game::renderer;
		auto* context = globals::d3d::context;
		if (!renderer || !context || !globals::d3d::device)
			return false;
		auto& total = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kTOTAL];
		if (!total.texture)
			return false;
		D3D11_TEXTURE2D_DESC totalDesc{};
		total.texture->GetDesc(&totalDesc);

		const FoveatedRenderImpl::NativeOpenVRGaze::Config gazeConfig{
			.enabled = foveated.settings.neuralRenderingEyeTrackedFoveation,
			.smoothingMs = foveated.settings.neuralRenderingEyeTrackedSmoothingMs,
			.policy = foveated.settings.neuralRenderingEyeTrackedPolicy,
			.catchupMs = foveated.settings.neuralRenderingEyeTrackedCatchupMs,
			.deadbandPixels = foveated.settings.neuralRenderingEyeTrackedDeadbandPixels,
			.holdMs = foveated.settings.neuralRenderingEyeTrackedHoldMs,
			.predictionMs = foveated.settings.neuralRenderingEyeTrackedPredictionMs,
			.quantizationPixels = foveated.settings.neuralRenderingEyeTrackedQuantizationPixels,
			.cropPaddingPixels = foveated.settings.neuralRenderingEyeTrackedCropPaddingPixels,
		};
		const bool gazeRequested = gazeConfig.enabled && foveated.settings.neuralRenderingEnabled &&
			foveated.GetDlssMode() == FoveatedRender::DlssMode::kDefault &&
			upscaling.GetUpscaleMethod() == Upscaling::UpscaleMethod::kDLSS;
		const auto staticLeftUV = foveated.GetEffectiveLeftUV();
		const auto staticRightUV = foveated.GetEffectiveRightUV();
		const auto gaze = FoveatedRenderImpl::NativeOpenVRGaze::ResolveForFrame(
			gazeConfig, staticLeftUV, staticRightUV, totalDesc.Width / 2, totalDesc.Height, frame,
			gazeRequested && FoveatedRenderImpl::NativeOpenVRGaze::IsDynamicGazeAllowed());
		// If the DLSS route did not publish this frame's guides yet, a moving crop
		// would make the previous frame's guides address the wrong source region.
		// Keep the established one-frame static tolerance, but fail closed for the
		// dynamic experiment until the current guides are available.
		if ((gaze.dynamic || foveated.IsAdaptiveCropRuntimeActive()) && guideFrame != frame)
			return false;
		auto leftUV = gaze.leftUV;
		auto rightUV = gaze.rightUV;
		const bool baseFullEye = leftUV.IsFullEye() && rightUV.IsFullEye();
		const auto* depthLeft = baseFullEye ? FoveatedRenderImpl::Core::vrIntermediateDepth[0].get() : FoveatedRenderImpl::Core::vrSubrectDepth[0].get();
		const auto* depthRight = baseFullEye ? FoveatedRenderImpl::Core::vrIntermediateDepth[1].get() : FoveatedRenderImpl::Core::vrSubrectDepth[1].get();
		const auto* motionLeft = baseFullEye ? FoveatedRenderImpl::Core::vrIntermediateMotionVectors[0].get() : FoveatedRenderImpl::Core::vrSubrectMotionVectors[0].get();
		const auto* motionRight = baseFullEye ? FoveatedRenderImpl::Core::vrIntermediateMotionVectors[1].get() : FoveatedRenderImpl::Core::vrSubrectMotionVectors[1].get();
		if (!depthLeft || !depthRight || !motionLeft || !motionRight)
			return false;
		if (leftUV.w != rightUV.w || leftUV.h != rightUV.h)
			return false;
		const std::uint32_t eyeWidth = totalDesc.Width / 2;
		const std::uint32_t baseOutWidth = std::max<std::uint32_t>(1, static_cast<std::uint32_t>(eyeWidth * leftUV.w));
		const std::uint32_t baseOutHeight = std::max<std::uint32_t>(1, static_cast<std::uint32_t>(totalDesc.Height * leftUV.h));
			// The fixed crop envelope is a backing-resource contract only. Feature
			// 18 still receives the current valid native guide extent so a smaller
			// crop never exposes stale tail data from the envelope.
			const std::uint32_t baseGuideWidth = baseFullEye ? FoveatedRenderImpl::Core::vrIntermediateDepth[0]->desc.Width : FoveatedRenderImpl::Core::vrSubrectValidInW;
			const std::uint32_t baseGuideHeight = baseFullEye ? FoveatedRenderImpl::Core::vrIntermediateDepth[0]->desc.Height : FoveatedRenderImpl::Core::vrSubrectValidInH;
			if (baseGuideWidth == 0 || baseGuideHeight == 0)
				return false;
		const bool splitSecondPassCrop = splitPostStage && activePassMode == 1 &&
			(foveated.settings.neuralRenderingSecondPassCropReductionX != 0 ||
				foveated.settings.neuralRenderingSecondPassCropReductionY != 0);
		const auto splitCrop = splitSecondPassCrop ? MakeSecondPassCropPlan(baseOutWidth, baseOutHeight,
			baseGuideWidth, baseGuideHeight, foveated.settings.neuralRenderingSecondPassCropReductionX,
			foveated.settings.neuralRenderingSecondPassCropReductionY) :
			NeuralRendering::SecondPassCropPlan{};
		if (splitSecondPassCrop && !splitCrop.enabled)
			return false;
		const std::uint32_t outWidth = splitSecondPassCrop ? splitCrop.output.width : baseOutWidth;
		const std::uint32_t outHeight = splitSecondPassCrop ? splitCrop.output.height : baseOutHeight;
		const std::uint32_t guideWidth = splitSecondPassCrop ? splitCrop.guides.width : baseGuideWidth;
		const std::uint32_t guideHeight = splitSecondPassCrop ? splitCrop.guides.height : baseGuideHeight;
		const bool fullEye = baseFullEye && !splitSecondPassCrop;
			Renderer::StereoResourceEnvelope resourceEnvelope{};
			if (!fullEye &&
				foveated.IsAdaptiveCropRuntimeActive() &&
				FoveatedRenderImpl::Core::vrSubrectResourceMode == FoveatedRenderImpl::Core::SubrectResourceMode::FixedEnvelope &&
				!FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected &&
				!FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected &&
				FoveatedRenderImpl::Core::vrSubrectInW >= guideWidth &&
				FoveatedRenderImpl::Core::vrSubrectInH >= guideHeight &&
				FoveatedRenderImpl::Core::vrSubrectOutW >= outWidth &&
				FoveatedRenderImpl::Core::vrSubrectOutH >= outHeight) {
				resourceEnvelope = {
					.enabled = true,
					.guideWidth = FoveatedRenderImpl::Core::vrSubrectInW,
					.guideHeight = FoveatedRenderImpl::Core::vrSubrectInH,
					.colorWidth = FoveatedRenderImpl::Core::vrSubrectOutW,
					.colorHeight = FoveatedRenderImpl::Core::vrSubrectOutH,
				};
			}

		// The normal foveated route blends the cropped upscaler result over the
		// stretched/background image. NR used to bypass that step and hard-copy
		// the crop, which made its rectangle visible even when Edge Blend was set
		// to Feather or Dither.
		const auto blendMode = foveated.GetSubrectBlendMode();
		const bool wantsEdgeBlend = !fullEye &&
			(splitSecondPassCrop || foveated.IsAdaptiveCropRuntimeActive() ||
				blendMode != FoveatedRender::SubrectBlendMode::kHardCopy);
		ID3D11Resource* destination = total.texture;
		ID3D11UnorderedAccessView* destinationUAV = total.UAV;
		bool stagedCropWriteback = false;
		CS_GPU_PASS("NeuralRendering::FoveatedLdrBeforeUI");
		ID3D11RenderTargetView* savedRTVs[D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT]{};
		ID3D11DepthStencilView* savedDSV = nullptr;
		context->OMGetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, savedRTVs, &savedDSV);
		context->OMSetRenderTargets(0, nullptr, nullptr);

		const Util::Subrect::UVRegion* eyeUVs[2]{ &leftUV, &rightUV };
		std::array<Renderer::StereoEyeInput, 2> inputs{};
		for (std::uint32_t eye = 0; eye < 2; ++eye) {
			const auto& uv = *eyeUVs[eye];
			const std::uint32_t cropBaseX = (eye ? eyeWidth : 0) + static_cast<std::uint32_t>(eyeWidth * uv.x);
			const std::uint32_t cropBaseY = static_cast<std::uint32_t>(totalDesc.Height * uv.y);
			const std::uint32_t x = cropBaseX + (splitSecondPassCrop ? splitCrop.output.x : 0u);
			const std::uint32_t y = cropBaseY + (splitSecondPassCrop ? splitCrop.output.y : 0u);
			float motionScaleX = 1.0f;
			float motionScaleY = 1.0f;
			FoveatedRenderImpl::Bridge::ComputeMvecScale(eye, motionScaleX, motionScaleY);
			inputs[eye] = {
				.depth = (baseFullEye ? FoveatedRenderImpl::Core::vrIntermediateDepth[eye] : FoveatedRenderImpl::Core::vrSubrectDepth[eye])->resource.get(),
				.depthSRV = (baseFullEye ? FoveatedRenderImpl::Core::vrIntermediateDepth[eye] : FoveatedRenderImpl::Core::vrSubrectDepth[eye])->srv.get(),
				.motionVectors = (baseFullEye ? FoveatedRenderImpl::Core::vrIntermediateMotionVectors[eye] : FoveatedRenderImpl::Core::vrSubrectMotionVectors[eye])->resource.get(),
				.sourceX = x,
				.sourceY = y,
				.guideSourceX = splitSecondPassCrop ? splitCrop.guides.x : 0u,
				.guideSourceY = splitSecondPassCrop ? splitCrop.guides.y : 0u,
				.guideSourceWidth = splitSecondPassCrop ? baseGuideWidth : 0u,
				.guideSourceHeight = splitSecondPassCrop ? baseGuideHeight : 0u,
				.forceFeatherComposite = splitSecondPassCrop,
				.motionVectorScaleX = motionScaleX * baseGuideWidth,
				.motionVectorScaleY = motionScaleY * baseGuideHeight,
				.compensateCropMotion = gaze.dynamic && !baseFullEye,
			};
		}
		const bool splitSecondPass = splitPostStage && activePassMode == 1;
		const bool finishNR = foveated.settings.neuralRenderingNRContribution < 1.0f ||
			foveated.settings.neuralRenderingDetailBoost > 1.0f ||
			(splitSecondPass && foveated.settings.neuralRenderingSecondPassContribution < 1.0f);
		if ((wantsEdgeBlend || finishNR) && !destinationUAV) {
			// Stage only each eye's active crop. The old fallback copied the full
			// SBS target in both directions, even when NR covered a small gaze crop.
			stagedCropWriteback = true;
			for (std::uint32_t eye = 0; eye < inputs.size(); ++eye) {
				auto& target = eyeBlendTargets[eye];
				if (!EnsureEyeBlendTarget(total.texture, eye, outWidth, outHeight)) {
					stagedCropWriteback = false;
					break;
				}
				const D3D11_BOX cropBox{ inputs[eye].sourceX, inputs[eye].sourceY, 0,
					inputs[eye].sourceX + outWidth, inputs[eye].sourceY + outHeight, 1 };
				context->CopySubresourceRegion(target->resource.get(), 0, 0, 0, 0, total.texture, 0, &cropBox);
				inputs[eye].writebackTarget = target->resource.get();
				inputs[eye].writebackUAV = target->uav.get();
			}
			if (!stagedCropWriteback) {
				for (auto& input : inputs) {
					input.writebackTarget = nullptr;
					input.writebackUAV = nullptr;
				}
				if (!blendFallbackLogged) {
					logger::warn("[DLSSNR] crop writeback allocation failed; using direct hard-copy fallback");
					blendFallbackLogged = true;
				}
			}
		}
		const bool enableBlend = wantsEdgeBlend && (destinationUAV || stagedCropWriteback);
		Tuning tuning = GetTuning(foveated, true);
		if (foveated.settings.neuralRenderingPreUpscale != 0) {
			// The pre-SR stage already consumed pass one when it succeeded. If it
			// did not, the post-SR route runs the full configured cascade as fallback.
			tuning.multiPass = stagePlan.postMultiPassMode;
			tuning.adaptiveMaxPassCount = stagePlan.postResourcePassCount;
		}
		if (splitPostStage && activePassMode == 1) {
			// In the 1-before/1-after split, the post-SR evaluation is pass two;
			// run it on its configured smaller crop and composite it against the SR
			// result derived from pass one's output.
			tuning.secondPassCropReductionX = 0;
			tuning.secondPassCropReductionY = 0;
			tuning.nrContribution *= tuning.secondPassContribution;
		} else if (activePassMode != 1) {
			// The centered crop contract is specifically for a two-evaluation chain.
			// A three-pass chain must not accidentally crop its third (final) pass.
			tuning.secondPassCropReductionX = 0;
			tuning.secondPassCropReductionY = 0;
		}
		if (!fullEye && tuning.adaptiveResolution && !tuning.adaptiveHandoff && !adaptiveCropHandoffDisabledLogged) {
			logger::info("[DLSSNR] adaptive NR history handoff disabled while adaptive crop is active; using current-frame crop feathering");
			adaptiveCropHandoffDisabledLogged = true;
		}
		tuning.multiPass = ResolveMultiPassMode(tuning.multiPass, !fullEye, tuning.adaptiveResolution);
			bool succeeded = Renderer::Instance().ApplyStereo(globals::d3d::device, context,
				total.texture, inputs, guideWidth, guideHeight,
				outWidth, outHeight, tuning, destination, destinationUAV, enableBlend,
				resourceEnvelope);
			if (!succeeded && resourceEnvelope.IsValid() &&
				Renderer::Instance().IsFailureRecoverable()) {
				// A native Feature 18 failure is not allowed to leave the runtime
				// latched on the experimental envelope. Drop only the NR renderer's
				// state, remember the rejection for this route, and retry with exact
				// current extents. The native depth/motion guide inputs stay unchanged.
				logger::warn("[DLSSNR] fixed resource envelope rejected; retrying exact extents frame={} result=0x{:08X} fallbackEntries={}",
					frame, Renderer::Instance().NgxResult(), FoveatedRenderImpl::Core::vrSubrectNeuralFallbackEntries + 1);
				if (Renderer::Instance().Reset()) {
					FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected = true;
					++FoveatedRenderImpl::Core::vrSubrectNeuralFallbackEntries;
					FoveatedRenderImpl::Core::InvalidateTemporalState();
					resourceEnvelope.enabled = false;
					if (stagedCropWriteback) {
						for (std::uint32_t eye = 0; eye < inputs.size(); ++eye) {
							const D3D11_BOX cropBox{ inputs[eye].sourceX, inputs[eye].sourceY, 0,
								inputs[eye].sourceX + outWidth, inputs[eye].sourceY + outHeight, 1 };
							context->CopySubresourceRegion(eyeBlendTargets[eye]->resource.get(), 0, 0, 0, 0,
								total.texture, 0, &cropBox);
						}
					}
					succeeded = Renderer::Instance().ApplyStereo(globals::d3d::device, context,
						total.texture, inputs, guideWidth, guideHeight,
						outWidth, outHeight, tuning, destination, destinationUAV, enableBlend,
						resourceEnvelope);
				} else {
					logger::error("[DLSSNR] fixed resource envelope fallback aborted because the GPU fence could not be drained");
				}
			}
		if (succeeded) {
			if (stagedCropWriteback) {
				const D3D11_BOX cropBox{ 0, 0, 0, outWidth, outHeight, 1 };
				for (std::uint32_t eye = 0; eye < inputs.size(); ++eye)
					context->CopySubresourceRegion(total.texture, 0, inputs[eye].sourceX, inputs[eye].sourceY, 0,
						eyeBlendTargets[eye]->resource.get(), 0, &cropBox);
			}
			// Crop handoffs move the current-frame compositing mask; no prior SBS image is reused.
			lastAppliedFrame = frame;
			if (!writebackLogged) {
				const char* path = stagedCropWriteback ? "crop-staged-uav" :
					(destinationUAV ? "direct-uav" : "direct-copy");
				logger::info("[DLSSNR] LDR output written before UI composite size={}x{} edgeBlend={} mode={} path={} gazeCrop={} batchedAsync=true",
					outWidth, outHeight, wantsEdgeBlend && destinationUAV != nullptr,
					FoveatedRender::SubrectBlendModeName(blendMode), path, gaze.dynamic);
				writebackLogged = true;
			}
		}

		context->OMSetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, savedRTVs, savedDSV);
		for (auto*& rtv : savedRTVs)
			if (rtv) rtv->Release();
		if (savedDSV) savedDSV->Release();
		return succeeded;
	}

	void RequestReset()
	{
		fullResetRequested.store(true, std::memory_order_release);
	}

	void Reset()
	{
		const bool preReset = Renderer::PreUpscaleInstance().Reset();
		const bool postReset = Renderer::Instance().Reset();
		if (preReset && postReset)
			Runtime::Instance().Shutdown();
		else
			logger::error("[DLSSNR] Full reset retained the NGX runtime because a stage GPU fence did not drain");
		globals::features::upscaling.foveatedRender.ResetAdaptiveState();
		FoveatedRenderImpl::NativeOpenVRGaze::Reset();
		historyResetRequested.store(false, std::memory_order_release);
		temporalSuppressed = false;
		// Keep Integration-owned staging textures alive if either stage still has
		// GPU work in flight. Its D3D11/D3D12 command stream may still reference
		// these objects after the bounded fence wait timed out.
		if (preReset && postReset) {
			color[0].reset();
			color[1].reset();
			preUpscaleGuides = {};
			for (auto& target : eyeBlendTargets)
				target.reset();
			colorWidth = colorHeight = 0;
			colorFormat = DXGI_FORMAT_UNKNOWN;
			eyeBlendWidths.fill(0);
			eyeBlendHeights.fill(0);
			eyeBlendFormats.fill(DXGI_FORMAT_UNKNOWN);
		}
		lastAppliedFrame = UINT32_MAX;
		preUpscaleAppliedFrame = UINT32_MAX;
		menuStateObserved = false;
		menuWasOpen = false;
		preUpscaleModeObserved = false;
		preUpscaleMode = false;
		preUpscaleBlockLogged = false;
		preUpscaleSuccessLogged = false;
		preUpscaleExecutionFailed = false;
		adaptiveCropHandoffDisabledLogged = false;
		writebackLogged = false;
		flatRouteWasActive = false;
		flatFrameGenerationBlockLogged = false;
		flatHdrBlockLogged = false;
		blendFallbackLogged = false;
	}
}
