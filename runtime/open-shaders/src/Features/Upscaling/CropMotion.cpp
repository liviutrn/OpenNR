#include "CropMotion.h"
#include "../../Globals.h"
#include "../../GpuPass.h"
#include "../../Util.h"
#include "../../Utils/D3D.h"

#include <wrl/client.h>

namespace FoveatedRenderImpl::CropMotion
{
	namespace
	{
		using Microsoft::WRL::ComPtr;
		struct Slot
		{
			History previous{}, pending{};
			ComPtr<ID3D11Resource> source;
			ComPtr<ID3D11ShaderResourceView> sourceView;
			ComPtr<ID3D11Texture2D> output;
			ComPtr<ID3D11UnorderedAccessView> outputView;
			D3D11_TEXTURE2D_DESC desc{};
		};
		std::array<Slot, 6> slots;
		ComPtr<ID3D11ComputeShader> shader;
		ComPtr<ID3D11Buffer> constants;
		struct Constants
		{
			std::uint32_t width, height;
			float dx, dy;
		};
		static_assert(sizeof(Constants) == 16);

		bool EnsureResources(Slot& slot, ID3D11Resource* source)
		{
			auto* device = globals::d3d::device;
			if (!device)
				return false;
			if (!shader) {
				shader.Attach(static_cast<ID3D11ComputeShader*>(Util::CompileShader(
					L"Data\\Shaders\\Upscaling\\FoveatedRender\\CropMotionCS.hlsl", {}, "cs_5_0")));
				if (!shader)
					return false;
				Util::SetResourceName(shader.Get(), "FoveatedRender::CropMotion");
			}
			if (!constants) {
				D3D11_BUFFER_DESC desc{};
				desc.ByteWidth = sizeof(Constants);
				desc.Usage = D3D11_USAGE_DEFAULT;
				desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&desc, nullptr, &constants)))
					return false;
				Util::SetResourceName(constants.Get(), "FoveatedRender::CropMotionConstants");
			}
			if (slot.source.Get() == source && slot.sourceView && slot.output && slot.outputView)
				return true;
			ComPtr<ID3D11Texture2D> texture;
			if (FAILED(source->QueryInterface(IID_PPV_ARGS(&texture))))
				return false;
			D3D11_TEXTURE2D_DESC desc{};
			texture->GetDesc(&desc);
			if (desc.ArraySize != 1 || desc.MipLevels != 1 || desc.SampleDesc.Count != 1 ||
				(desc.Format != DXGI_FORMAT_R16G16_FLOAT && desc.Format != DXGI_FORMAT_R32G32_FLOAT))
				return false;
			slot.sourceView.Reset();
			if (FAILED(device->CreateShaderResourceView(source, nullptr, &slot.sourceView)))
				return false;
			Util::SetResourceName(slot.sourceView.Get(), "FoveatedRender::CropMotionSource SRV");
			if (!slot.output || slot.desc.Width != desc.Width || slot.desc.Height != desc.Height || slot.desc.Format != desc.Format) {
				slot.output.Reset();
				slot.outputView.Reset();
				desc.Usage = D3D11_USAGE_DEFAULT;
				desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
				desc.CPUAccessFlags = 0;
				desc.MiscFlags = 0;
				if (FAILED(device->CreateTexture2D(&desc, nullptr, &slot.output)) ||
					FAILED(device->CreateUnorderedAccessView(slot.output.Get(), nullptr, &slot.outputView)))
					return false;
				Util::SetResourceName(slot.output.Get(), "FoveatedRender::CropMotionOutput");
				Util::SetResourceName(slot.outputView.Get(), "FoveatedRender::CropMotionOutput UAV");
			}
			slot.source = source;
			slot.desc = desc;
			return true;
		}
	}

	ID3D11Resource* Prepare(std::uint32_t index, ID3D11Resource* source,
		const Region& region, std::uint32_t guideWidth, std::uint32_t guideHeight,
		std::array<float, 2> scale, std::uint32_t frame, bool& reset)
	{
		if (index >= slots.size() || !source || !globals::d3d::context || !guideWidth || !guideHeight)
			return nullptr;
		auto& slot = slots[index];
		slot.pending = {};
		const auto offset = Offset(slot.previous, region, scale, frame, reset);
		slot.pending = { region, scale, frame, true };
		if (offset[0] == 0.0f && offset[1] == 0.0f)
			return source;
		if (!EnsureResources(slot, source) || guideWidth > slot.desc.Width || guideHeight > slot.desc.Height) {
			slot.pending.valid = false;
			return nullptr;
		}
		CS_GPU_PASS("FoveatedRender::CropMotion");
		auto* context = globals::d3d::context;
		ComPtr<ID3D11ComputeShader> oldShader;
		ComPtr<ID3D11ShaderResourceView> oldSource;
		ComPtr<ID3D11UnorderedAccessView> oldOutput;
		ComPtr<ID3D11Buffer> oldConstants;
		std::array<ID3D11ClassInstance*, 256> classes{};
		UINT classCount = static_cast<UINT>(classes.size());
		context->CSGetShader(&oldShader, classes.data(), &classCount);
		context->CSGetShaderResources(0, 1, &oldSource);
		context->CSGetUnorderedAccessViews(0, 1, &oldOutput);
		context->CSGetConstantBuffers(0, 1, &oldConstants);
		ID3D11UnorderedAccessView* nullOutput = nullptr;
		context->CSSetUnorderedAccessViews(0, 1, &nullOutput, nullptr);
		const Constants data{ guideWidth, guideHeight, offset[0], offset[1] };
		context->UpdateSubresource(constants.Get(), 0, nullptr, &data, 0, 0);
		context->CSSetShader(shader.Get(), nullptr, 0);
		context->CSSetShaderResources(0, 1, slot.sourceView.GetAddressOf());
		context->CSSetUnorderedAccessViews(0, 1, slot.outputView.GetAddressOf(), nullptr);
		context->CSSetConstantBuffers(0, 1, constants.GetAddressOf());
		context->Dispatch((guideWidth + 7) / 8, (guideHeight + 7) / 8, 1);
		context->CSSetUnorderedAccessViews(0, 1, &nullOutput, nullptr);
		context->CSSetShaderResources(0, 1, oldSource.GetAddressOf());
		context->CSSetUnorderedAccessViews(0, 1, oldOutput.GetAddressOf(), nullptr);
		context->CSSetConstantBuffers(0, 1, oldConstants.GetAddressOf());
		context->CSSetShader(oldShader.Get(), classes.data(), classCount);
		for (UINT i = 0; i < classCount; ++i)
			classes[i]->Release();
		return slot.output.Get();
	}

	void Commit(std::uint32_t slot, bool succeeded)
	{
		if (slot < slots.size())
			slots[slot].previous = succeeded ? slots[slot].pending : History{};
	}

	void Invalidate(std::uint32_t firstSlot, std::uint32_t count)
	{
		for (auto i = firstSlot; i < slots.size() && i - firstSlot < count; ++i) {
			slots[i].previous = {};
			slots[i].pending = {};
		}
	}

	void Clear()
	{
		slots = {};
		shader.Reset();
		constants.Reset();
	}
}
