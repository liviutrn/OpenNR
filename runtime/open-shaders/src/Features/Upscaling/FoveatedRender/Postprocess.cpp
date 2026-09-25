#include "Postprocess.h"

#include "../../../Globals.h"
#include "../../../GpuPass.h"
#include "../../../State.h"
#include "../../Upscaling.h"

namespace FoveatedRenderImpl
{
	namespace
	{
		eastl::unique_ptr<Texture2D> sharpenTarget;
		D3D11_TEXTURE2D_DESC sharpenDesc{};
		uint32_t sharpenFrame = UINT32_MAX;
	}

	void Postprocess::Reset()
	{
		sharpenTarget.reset();
		sharpenDesc = {};
		sharpenFrame = UINT32_MAX;
	}

	bool Postprocess::ApplyDlssSharpening(Upscaling& upscaling)
	{
		const float strength = Sharpening::Sanitize(upscaling.settings.sharpnessDLSS);
		if (!upscaling.settings.sharpnessEnabledDLSS || strength == 0.0f)
			return true;
		auto* context = globals::d3d::context;
		auto* renderer = globals::game::renderer;
		if (!context || !renderer || !globals::state)
			return false;
		const auto frame = globals::state->frameCount;
		if (sharpenFrame == frame)
			return true;
		auto& total = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kTOTAL];
		if (!total.texture || !total.SRV)
			return false;
		D3D11_TEXTURE2D_DESC desc{};
		total.texture->GetDesc(&desc);
		if (desc.SampleDesc.Count != 1 || desc.ArraySize != 1 || desc.MipLevels != 1 ||
			!desc.Width || (desc.Width % 2) != 0 || !desc.Height)
			return false;
		if (!sharpenTarget || desc.Width != sharpenDesc.Width || desc.Height != sharpenDesc.Height || desc.Format != sharpenDesc.Format) {
			sharpenTarget = Upscaling::CreateTextureFromSource(total.texture, desc.Width, desc.Height,
				false, false, true, "FoveatedRender::FinalSharpen");
			sharpenDesc = desc;
		}
		if (!sharpenTarget || !sharpenTarget->resource || !sharpenTarget->uav)
			return false;

		CS_GPU_PASS("FoveatedRender::SharpenFinalScene");
		ID3D11RenderTargetView* oldRTVs[D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT]{};
		ID3D11DepthStencilView* oldDSV = nullptr;
		winrt::com_ptr<ID3D11ComputeShader> oldShader;
		winrt::com_ptr<ID3D11ShaderResourceView> oldSource;
		winrt::com_ptr<ID3D11UnorderedAccessView> oldOutput;
		winrt::com_ptr<ID3D11Buffer> oldConstants;
		ID3D11ClassInstance* classes[256]{};
		UINT classCount = 256;
		context->OMGetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, oldRTVs, &oldDSV);
		context->CSGetShader(oldShader.put(), classes, &classCount);
		context->CSGetShaderResources(0, 1, oldSource.put());
		context->CSGetUnorderedAccessViews(0, 1, oldOutput.put());
		context->CSGetConstantBuffers(0, 1, oldConstants.put());
		context->OMSetRenderTargets(0, nullptr, nullptr);
		ID3D11UnorderedAccessView* nullOutput = nullptr;
		context->CSSetUnorderedAccessViews(0, 1, &nullOutput, nullptr);
		const bool applied = upscaling.rcas.ApplySharpen(total.SRV, sharpenTarget->uav.get(), strength);
		if (applied) {
			context->CopyResource(total.texture, sharpenTarget->resource.get());
			sharpenFrame = frame;
		}
		auto* oldSourceView = oldSource.get();
		auto* oldOutputView = oldOutput.get();
		auto* oldBuffer = oldConstants.get();
		context->CSSetShaderResources(0, 1, &oldSourceView);
		context->CSSetUnorderedAccessViews(0, 1, &oldOutputView, nullptr);
		context->CSSetConstantBuffers(0, 1, &oldBuffer);
		context->CSSetShader(oldShader.get(), classes, classCount);
		for (UINT i = 0; i < classCount; ++i)
			if (classes[i]) classes[i]->Release();
		context->OMSetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, oldRTVs, oldDSV);
		for (auto* rtv : oldRTVs)
			if (rtv) rtv->Release();
		if (oldDSV) oldDSV->Release();
		return applied;
	}
}
