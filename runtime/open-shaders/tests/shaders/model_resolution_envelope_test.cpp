// Standalone D3D11 WARP regression: identical valid images must resolve identically
// whether tightly allocated or stored in a larger, poisoned crop envelope.
#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;

static void Check(HRESULT result)
{
	if (FAILED(result))
		throw std::runtime_error("D3D failure: " + std::to_string(result));
}

struct Pixel { float r, g, b, a; };
struct Params
{
	UINT mode, width, height, sourceWidth, sourceHeight;
	float transfer = 1, colour = 0.8f, maxRatio = 1.6f, residual = 0.9f;
	float padding[3]{};
};
static_assert(sizeof(Params) == 48);

struct Texture
{
	ComPtr<ID3D11Texture2D> texture;
	ComPtr<ID3D11ShaderResourceView> srv;
	ComPtr<ID3D11UnorderedAccessView> uav;
};

static Texture MakeTexture(ID3D11Device* device, UINT width, UINT height,
	UINT validWidth, UINT validHeight, unsigned seed)
{
	std::vector<Pixel> data(width * height, Pixel{ 99, 17, 63, 1 });
	for (UINT y = 0; y < validHeight; ++y)
		for (UINT x = 0; x < validWidth; ++x) {
			const float value = 0.1f + float((x * 7 + y * 11 + seed * 3) % 31) / 40;
			data[y * width + x] = { value, value * 0.6f, value * 0.3f, 1 };
		}
	D3D11_TEXTURE2D_DESC desc{};
	desc.Width = width;
	desc.Height = height;
	desc.MipLevels = desc.ArraySize = desc.SampleDesc.Count = 1;
	desc.Format = DXGI_FORMAT_R32G32B32A32_FLOAT;
	desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
	D3D11_SUBRESOURCE_DATA initial{ data.data(), width * sizeof(Pixel), 0 };
	Texture result;
	Check(device->CreateTexture2D(&desc, &initial, &result.texture));
	Check(device->CreateShaderResourceView(result.texture.Get(), nullptr, &result.srv));
	Check(device->CreateUnorderedAccessView(result.texture.Get(), nullptr, &result.uav));
	return result;
}

static std::vector<Pixel> Run(ID3D11Device* device, ID3D11DeviceContext* context,
	const Params& params, bool envelope)
{
	const UINT extraWidth = envelope ? 13 : 0;
	const UINT extraHeight = envelope ? 9 : 0;
	auto proxy = MakeTexture(device, params.sourceWidth + extraWidth, params.sourceHeight + extraHeight,
		params.sourceWidth, params.sourceHeight, 0);
	auto model = MakeTexture(device, params.sourceWidth + extraWidth, params.sourceHeight + extraHeight,
		params.sourceWidth, params.sourceHeight, 1);
	auto original = MakeTexture(device, params.width + extraWidth, params.height + extraHeight,
		params.width, params.height, 2);
	auto output = MakeTexture(device, params.width + extraWidth, params.height + extraHeight, 0, 0, 0);
	D3D11_BUFFER_DESC cbDesc{};
	cbDesc.ByteWidth = sizeof(Params);
	cbDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
	D3D11_SUBRESOURCE_DATA cbData{ &params, 0, 0 };
	ComPtr<ID3D11Buffer> cb;
	Check(device->CreateBuffer(&cbDesc, &cbData, &cb));
	ID3D11ShaderResourceView* sources[]{ proxy.srv.Get(), model.srv.Get(), original.srv.Get() };
	context->CSSetShaderResources(0, 3, sources);
	context->CSSetConstantBuffers(0, 1, cb.GetAddressOf());
	context->CSSetUnorderedAccessViews(0, 1, output.uav.GetAddressOf(), nullptr);
	context->Dispatch((params.width + 7) / 8, (params.height + 7) / 8, 1);
	ID3D11ShaderResourceView* nullSources[3]{};
	ID3D11UnorderedAccessView* nullTarget = nullptr;
	context->CSSetShaderResources(0, 3, nullSources);
	context->CSSetUnorderedAccessViews(0, 1, &nullTarget, nullptr);
	D3D11_TEXTURE2D_DESC stagingDesc{};
	output.texture->GetDesc(&stagingDesc);
	stagingDesc.BindFlags = 0;
	stagingDesc.Usage = D3D11_USAGE_STAGING;
	stagingDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
	ComPtr<ID3D11Texture2D> staging;
	Check(device->CreateTexture2D(&stagingDesc, nullptr, &staging));
	context->CopyResource(staging.Get(), output.texture.Get());
	D3D11_MAPPED_SUBRESOURCE mapped{};
	Check(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped));
	std::vector<Pixel> result;
	for (UINT y = 0; y < params.height; ++y) {
		const auto row = reinterpret_cast<const Pixel*>(static_cast<const char*>(mapped.pData) + y * mapped.RowPitch);
		result.insert(result.end(), row, row + params.width);
	}
	context->Unmap(staging.Get(), 0);
	return result;
}

int wmain(int argc, wchar_t** argv)
{
	try {
		if (argc != 2)
			throw std::runtime_error("Expected ModelResolutionCS.hlsl path");
		ComPtr<ID3DBlob> code, errors;
		const auto compiled = D3DCompileFromFile(argv[1], nullptr, nullptr, "main", "cs_5_0",
			D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_WARNINGS_ARE_ERRORS, 0, &code, &errors);
		if (errors)
			std::cerr << static_cast<const char*>(errors->GetBufferPointer());
		Check(compiled);
		ComPtr<ID3D11Device> device;
		ComPtr<ID3D11DeviceContext> context;
		Check(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0, nullptr, 0,
			D3D11_SDK_VERSION, &device, nullptr, &context));
		ComPtr<ID3D11ComputeShader> shader;
		Check(device->CreateComputeShader(code->GetBufferPointer(), code->GetBufferSize(), nullptr, &shader));
		context->CSSetShader(shader.Get(), nullptr, 0);
		D3D11_SAMPLER_DESC samplerDesc{};
		samplerDesc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
		samplerDesc.AddressU = samplerDesc.AddressV = samplerDesc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
		samplerDesc.MaxLOD = D3D11_FLOAT32_MAX;
		ComPtr<ID3D11SamplerState> sampler;
		Check(device->CreateSamplerState(&samplerDesc, &sampler));
		context->CSSetSamplers(0, 1, sampler.GetAddressOf());
		unsigned failures = 0;
		for (UINT mode = 0; mode < 4; ++mode) {
			for (UINT percent : { 95u, 85u, 60u, 33u }) {
				const UINT modelWidth = std::max(1u, (37 * percent + 50) / 100);
				const UINT modelHeight = std::max(1u, (29 * percent + 50) / 100);
				const bool downsample = mode == 0 || mode == 2;
				const Params params{ mode, downsample ? modelWidth : 37, downsample ? modelHeight : 29,
					downsample ? 37 : modelWidth, downsample ? 29 : modelHeight };
				const auto tight = Run(device.Get(), context.Get(), params, false);
				const auto envelope = Run(device.Get(), context.Get(), params, true);
				float maxError = 0;
				for (size_t i = 0; i < tight.size(); ++i) {
					const float error = std::max({ std::abs(tight[i].r - envelope[i].r),
						std::abs(tight[i].g - envelope[i].g), std::abs(tight[i].b - envelope[i].b) });
					if (!std::isfinite(error))
						throw std::runtime_error("Nonfinite shader output");
					maxError = std::max(maxError, error);
				}
				const bool passed = maxError < 0.0001f;
				failures += !passed;
				std::cout << "mode=" << mode << " NR=" << percent << " maxError=" << maxError
					<< (passed ? " PASS\n" : " FAIL\n");
			}
		}
		return failures ? 1 : 0;
	} catch (const std::exception& error) {
		std::cerr << error.what() << '\n';
		return 2;
	}
}
