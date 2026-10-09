#include "Postprocess.h"

#include "../../../Globals.h"
#include "../../../State.h"
#include "../../Upscaling.h"
#include "../FoveatedRender.h"

#include <cmath>

namespace FoveatedRenderImpl
{
	bool Postprocess::ApplyDlssSharpening(Upscaling& upscaling)
	{
		if (!upscaling.IsDlssSharpeningEnabled())
			return true;

		auto context = globals::d3d::context;
		auto renderer = globals::game::renderer;
		if (!context || !renderer) {
			logger::error("[FOVEATED] Missing D3D context or renderer for DLSS sharpening");
			return false;
		}

		const float currentSharpness = RCAS::MapSliderStrength(upscaling.settings.sharpnessDLSS);
		context->OMSetRenderTargets(0, nullptr, nullptr);

		// PerfMode + foveated DLSS writes the reconstructed display-resolution
		// image to testTexture. The previous foveated sharpening path always read
		// kMAIN, which is only the render-resolution bridge in this mode, so the
		// visible HMD output was not being sharpened. Reuse PerfMode's existing
		// display-resolution scratch: testTexture -> refraTempTex -> RCAS -> testTexture.
		auto& perfMode = upscaling.perfMode;
		if (perfMode.IsHookActive() && perfMode.GetTestTexture()) {
			if (!perfMode.GetTestTextureSRV() || !perfMode.GetTestTextureUAV() ||
				!perfMode.GetRefraTempTex() || !perfMode.GetRefraTempSRV()) {
				logger::error("[FOVEATED] Missing PerfMode display-resolution sharpening resources");
				return false;
			}

			context->CopyResource(perfMode.GetRefraTempTex(), perfMode.GetTestTexture());
			if (!upscaling.rcas.ApplySharpen(perfMode.GetRefraTempSRV(), perfMode.GetTestTextureUAV(), currentSharpness))
				return false;
			if (globals::game::stateUpdateFlags)
				globals::game::stateUpdateFlags->set(RE::BSGraphics::ShaderFlags::DIRTY_RENDERTARGET);
			return true;
		}

		// Non-PerfMode foveated route: kMAIN is the actual DLSS output. Preserve
		// the original sharpener scratch path and write its RCAS result back in place.
		if (!upscaling.sharpenerTexture || !upscaling.sharpenerTexture->uav ||
			!upscaling.sharpenerTexture->resource) {
			logger::error("[FOVEATED] Missing standard DLSS sharpener resources");
			return false;
		}

		auto& main = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kMAIN];
		if (!main.SRV) {
			logger::error("[FOVEATED] Missing main SRV for DLSS sharpening");
			return false;
		}

		ID3D11Resource* mainResource = nullptr;
		main.SRV->GetResource(Util::AsW32(&mainResource));
		if (!mainResource) {
			logger::error("[FOVEATED] Failed to acquire main resource for DLSS sharpening");
			return false;
		}

		if (!upscaling.rcas.ApplySharpen(Util::AsReal(main.SRV), upscaling.sharpenerTexture->uav.get(), currentSharpness)) {
			mainResource->Release();
			return false;
		}
		context->CopyResource(mainResource, upscaling.sharpenerTexture->resource.get());
		mainResource->Release();

		if (globals::game::stateUpdateFlags)
			globals::game::stateUpdateFlags->set(RE::BSGraphics::ShaderFlags::DIRTY_RENDERTARGET);
		return true;
	}
}
