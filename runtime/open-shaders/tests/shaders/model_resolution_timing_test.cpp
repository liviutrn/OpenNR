// Standalone D3D11 hardware timing probe for the reduced-resolution resolve.
//
// This intentionally stays outside the OpenNR runtime. It compiles the same
// ModelResolutionCS.hlsl and measures the GPU timestamp for the resolve
// dispatch at the captured full-eye dimensions. The full-setup measurement
// mirrors DispatchModelResolve's UpdateSubresource, binding, dispatch, and
// unbinding sequence; it does not include Feature 18, copies, interop, or the
// game/compositor.
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <dxgi.h>
#include <wrl/client.h>
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;

static void Check(HRESULT result, const char* operation)
{
	if (FAILED(result))
		throw std::runtime_error(std::string(operation) + " failed: HRESULT=" + std::to_string(result));
}

struct Params
{
	UINT mode = 3;
	UINT width = 0;
	UINT height = 0;
	UINT sourceWidth = 0;
	UINT sourceHeight = 0;
	float transferStrength = 1.0f;
	float colourStrength = 1.0f;
	float maxRatio = 1.5f;
	float residualStrength = 1.0f;
	float padding0 = 0.0f;
	float padding1 = 0.0f;
	float padding2 = 0.0f;
};
static_assert(sizeof(Params) == 48);

struct Texture
{
	ComPtr<ID3D11Texture2D> resource;
	ComPtr<ID3D11ShaderResourceView> srv;
	ComPtr<ID3D11UnorderedAccessView> uav;
};

struct Eye
{
	Texture proxy;
	Texture model;
	Texture original;
	Texture target;
};

static Texture MakeTexture(ID3D11Device* device, UINT width, UINT height)
{
	D3D11_TEXTURE2D_DESC desc{};
	desc.Width = width;
	desc.Height = height;
	desc.MipLevels = 1;
	desc.ArraySize = 1;
	desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
	desc.SampleDesc.Count = 1;
	desc.Usage = D3D11_USAGE_DEFAULT;
	desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;

	const size_t rowBytes = static_cast<size_t>(width) * 8;
	std::vector<std::uint8_t> zeroes(rowBytes * height, 0);
	D3D11_SUBRESOURCE_DATA initial{ zeroes.data(), static_cast<UINT>(rowBytes), 0 };
	Texture texture;
	Check(device->CreateTexture2D(&desc, &initial, texture.resource.GetAddressOf()), "CreateTexture2D");
	Check(device->CreateShaderResourceView(texture.resource.Get(), nullptr, texture.srv.GetAddressOf()),
		"CreateShaderResourceView");
	Check(device->CreateUnorderedAccessView(texture.resource.Get(), nullptr, texture.uav.GetAddressOf()),
		"CreateUnorderedAccessView");
	return texture;
}

static Eye MakeEye(ID3D11Device* device, UINT width, UINT height, UINT sourceWidth, UINT sourceHeight)
{
	return Eye{
		.proxy = MakeTexture(device, sourceWidth, sourceHeight),
		.model = MakeTexture(device, sourceWidth, sourceHeight),
		.original = MakeTexture(device, width, height),
		.target = MakeTexture(device, width, height),
	};
}

static void BindResolve(ID3D11DeviceContext* context, ID3D11ComputeShader* shader,
	ID3D11SamplerState* sampler, ID3D11Buffer* constants, const Eye& eye, const Params& params)
{
	context->UpdateSubresource(constants, 0, nullptr, &params, 0, 0);
	context->CSSetShader(shader, nullptr, 0);
	context->CSSetConstantBuffers(0, 1, &constants);
	ID3D11ShaderResourceView* sources[]{ eye.proxy.srv.Get(), eye.model.srv.Get(), eye.original.srv.Get() };
	context->CSSetShaderResources(0, 3, sources);
	ID3D11UnorderedAccessView* target = eye.target.uav.Get();
	context->CSSetUnorderedAccessViews(0, 1, &target, nullptr);
	context->CSSetSamplers(0, 1, &sampler);
}

static void ClearBindings(ID3D11DeviceContext* context)
{
	ID3D11ShaderResourceView* nullSources[3]{};
	ID3D11UnorderedAccessView* nullTarget = nullptr;
	ID3D11Buffer* nullConstants = nullptr;
	ID3D11SamplerState* nullSampler = nullptr;
	context->CSSetShaderResources(0, 3, nullSources);
	context->CSSetUnorderedAccessViews(0, 1, &nullTarget, nullptr);
	context->CSSetConstantBuffers(0, 1, &nullConstants);
	context->CSSetSamplers(0, 1, &nullSampler);
}

static void BindDownsample(ID3D11DeviceContext* context, ID3D11ComputeShader* shader,
	ID3D11SamplerState* sampler, ID3D11Buffer* constants, const Texture& source,
	const Texture& target, const Params& params)
{
	context->UpdateSubresource(constants, 0, nullptr, &params, 0, 0);
	context->CSSetShader(shader, nullptr, 0);
	context->CSSetConstantBuffers(0, 1, &constants);
	ID3D11ShaderResourceView* sourceView = source.srv.Get();
	context->CSSetShaderResources(0, 1, &sourceView);
	ID3D11UnorderedAccessView* targetView = target.uav.Get();
	context->CSSetUnorderedAccessViews(0, 1, &targetView, nullptr);
	context->CSSetSamplers(0, 1, &sampler);
}

static void FullSetupBatch(ID3D11DeviceContext* context, ID3D11ComputeShader* shader,
	ID3D11SamplerState* sampler, ID3D11Buffer* constants, const Eye& left, const Eye& right,
	const Params& params, UINT dispatchWidth, UINT dispatchHeight, UINT repetitions)
{
	for (UINT repetition = 0; repetition < repetitions; ++repetition) {
		for (const Eye* eye : { &left, &right }) {
			BindResolve(context, shader, sampler, constants, *eye, params);
			context->Dispatch((dispatchWidth + 7) / 8, (dispatchHeight + 7) / 8, 1);
			ClearBindings(context);
		}
	}
}

static void DispatchOnlyBatch(ID3D11DeviceContext* context, ID3D11ComputeShader* shader,
	ID3D11SamplerState* sampler, ID3D11Buffer* constants, const Eye& eye, const Params& params,
	UINT dispatchWidth, UINT dispatchHeight, UINT stereoRepetitions)
{
	// Two dispatches on one resident eye are equivalent GPU work to the stereo
	// pair, while avoiding resource rebinding in this lower-bound measurement.
	BindResolve(context, shader, sampler, constants, eye, params);
	for (UINT repetition = 0; repetition < stereoRepetitions; ++repetition) {
		context->Dispatch((dispatchWidth + 7) / 8, (dispatchHeight + 7) / 8, 1);
		context->Dispatch((dispatchWidth + 7) / 8, (dispatchHeight + 7) / 8, 1);
	}
	ClearBindings(context);
}

static void DownsampleBatch(ID3D11DeviceContext* context, ID3D11ComputeShader* shader,
	ID3D11SamplerState* sampler, ID3D11Buffer* constants, const Eye& left, const Eye& right,
	const Params& params, UINT dispatchWidth, UINT dispatchHeight, UINT repetitions)
{
	for (UINT repetition = 0; repetition < repetitions; ++repetition) {
		for (const Eye* eye : { &left, &right }) {
			BindDownsample(context, shader, sampler, constants, eye->original, eye->proxy, params);
			context->Dispatch((dispatchWidth + 7) / 8, (dispatchHeight + 7) / 8, 1);
			ClearBindings(context);
		}
	}
}

template <class T>
static T WaitForQuery(ID3D11DeviceContext* context, ID3D11Query* query)
{
	T result{};
	for (;;) {
		const HRESULT status = context->GetData(query, &result, sizeof(result), 0);
		if (status == S_OK)
			return result;
		if (status != S_FALSE)
			Check(status, "GetData");
		::Sleep(1);
	}
}

static void WaitForEvent(ID3D11DeviceContext* context, ID3D11Query* query)
{
	for (;;) {
		const HRESULT status = context->GetData(query, nullptr, 0, 0);
		if (status == S_OK)
			return;
		if (status != S_FALSE)
			Check(status, "GetData event");
		::Sleep(1);
	}
}

template <class Batch>
static double TimedBatch(ID3D11DeviceContext* context, Batch&& batch, UINT repetitions)
{
	D3D11_QUERY_DESC disjointDesc{ D3D11_QUERY_TIMESTAMP_DISJOINT, 0 };
	D3D11_QUERY_DESC timestampDesc{ D3D11_QUERY_TIMESTAMP, 0 };
	ComPtr<ID3D11Query> disjoint;
	ComPtr<ID3D11Query> start;
	ComPtr<ID3D11Query> stop;
	ComPtr<ID3D11Device> device;
	context->GetDevice(device.GetAddressOf());
	Check(device->CreateQuery(&disjointDesc, disjoint.GetAddressOf()), "CreateQuery disjoint");
	Check(device->CreateQuery(&timestampDesc, start.GetAddressOf()), "CreateQuery start");
	Check(device->CreateQuery(&timestampDesc, stop.GetAddressOf()), "CreateQuery stop");

	context->Begin(disjoint.Get());
	context->End(start.Get());
	batch();
	context->End(stop.Get());
	context->End(disjoint.Get());
	context->Flush();

	const auto disjointData = WaitForQuery<D3D11_QUERY_DATA_TIMESTAMP_DISJOINT>(context, disjoint.Get());
	const auto startTimestamp = WaitForQuery<UINT64>(context, start.Get());
	const auto stopTimestamp = WaitForQuery<UINT64>(context, stop.Get());
	if (disjointData.Disjoint || stopTimestamp < startTimestamp || disjointData.Frequency == 0)
		throw std::runtime_error("invalid timestamp disjoint result");
	return (static_cast<double>(stopTimestamp - startTimestamp) * 1000.0 /
		static_cast<double>(disjointData.Frequency)) / static_cast<double>(repetitions);
}

static void WaitForIdle(ID3D11DeviceContext* context, ID3D11Device* device)
{
	D3D11_QUERY_DESC eventDesc{ D3D11_QUERY_EVENT, 0 };
	ComPtr<ID3D11Query> event;
	Check(device->CreateQuery(&eventDesc, event.GetAddressOf()), "CreateQuery event");
	context->End(event.Get());
	context->Flush();
	WaitForEvent(context, event.Get());
}

static double Median(std::vector<double> values)
{
	std::sort(values.begin(), values.end());
	return values[values.size() / 2];
}

static void BenchmarkTier(ID3D11Device* device, ID3D11DeviceContext* context,
	ID3D11ComputeShader* shader, ID3D11SamplerState* sampler, ID3D11Buffer* constants,
	UINT width, UINT height, UINT percent)
{
	const UINT sourceWidth = std::max(1u, (width * percent + 50) / 100);
	const UINT sourceHeight = std::max(1u, (height * percent + 50) / 100);
	const Params params{ 3, width, height, sourceWidth, sourceHeight, 1.0f, 1.0f, 1.5f, 1.0f };
	const Params bilinearParams{ 0, sourceWidth, sourceHeight, width, height };
	const Params exactAreaParams{ 2, sourceWidth, sourceHeight, width, height };
	const Eye left = MakeEye(device, width, height, sourceWidth, sourceHeight);
	const Eye right = MakeEye(device, width, height, sourceWidth, sourceHeight);
	constexpr UINT warmup = 8;
	constexpr UINT repetitions = 64;
	constexpr UINT samples = 7;

	FullSetupBatch(context, shader, sampler, constants, left, right, params, width, height, warmup);
	WaitForIdle(context, device);
	std::vector<double> fullSetup;
	std::vector<double> dispatchOnly;
	std::vector<double> inputBilinear;
	std::vector<double> inputExactArea;
	for (UINT sample = 0; sample < samples; ++sample) {
		fullSetup.push_back(TimedBatch(context, [&] {
			FullSetupBatch(context, shader, sampler, constants, left, right, params, width, height, repetitions);
		}, repetitions));
		WaitForIdle(context, device);
		dispatchOnly.push_back(TimedBatch(context, [&] {
			DispatchOnlyBatch(context, shader, sampler, constants, left, params, width, height, repetitions);
		}, repetitions));
		WaitForIdle(context, device);
		inputBilinear.push_back(TimedBatch(context, [&] {
			DownsampleBatch(context, shader, sampler, constants, left, right, bilinearParams,
				sourceWidth, sourceHeight, repetitions);
		}, repetitions));
		WaitForIdle(context, device);
		inputExactArea.push_back(TimedBatch(context, [&] {
			DownsampleBatch(context, shader, sampler, constants, left, right, exactAreaParams,
				sourceWidth, sourceHeight, repetitions);
		}, repetitions));
		WaitForIdle(context, device);
	}

	std::cout << "tier=" << percent << " target=" << width << "x" << height
		<< " source=" << sourceWidth << "x" << sourceHeight
		<< " dispatch_only_stereo_median_ms=" << Median(dispatchOnly)
		<< " full_setup_stereo_median_ms=" << Median(fullSetup)
		<< " input_bilinear_stereo_median_ms=" << Median(inputBilinear)
		<< " input_exact_area_stereo_median_ms=" << Median(inputExactArea) << '\n';
	std::cout << "  dispatch_only_samples_ms=";
	for (const double value : dispatchOnly)
		std::cout << value << ' ';
	std::cout << '\n' << "  full_setup_samples_ms=";
	for (const double value : fullSetup)
		std::cout << value << ' ';
	std::cout << '\n' << "  input_bilinear_samples_ms=";
	for (const double value : inputBilinear)
		std::cout << value << ' ';
	std::cout << '\n' << "  input_exact_area_samples_ms=";
	for (const double value : inputExactArea)
		std::cout << value << ' ';
	std::cout << '\n';
}

int wmain(int argc, wchar_t** argv)
{
	try {
		if (argc != 2)
			throw std::runtime_error("Expected ModelResolutionCS.hlsl path");
		ComPtr<ID3DBlob> code;
		ComPtr<ID3DBlob> errors;
		const HRESULT compiled = D3DCompileFromFile(argv[1], nullptr, nullptr, "main", "cs_5_0",
			D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_WARNINGS_ARE_ERRORS, 0, &code, &errors);
		if (errors && errors->GetBufferSize() != 0)
			std::cerr << static_cast<const char*>(errors->GetBufferPointer()) << '\n';
		Check(compiled, "D3DCompileFromFile");

		ComPtr<ID3D11Device> device;
		ComPtr<ID3D11DeviceContext> context;
		Check(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0,
			D3D11_SDK_VERSION, &device, nullptr, &context), "D3D11CreateDevice hardware");
		ComPtr<IDXGIDevice> dxgiDevice;
		Check(device.As(&dxgiDevice), "Query IDXGIDevice");
		ComPtr<IDXGIAdapter> adapter;
		Check(dxgiDevice->GetAdapter(&adapter), "GetAdapter");
		DXGI_ADAPTER_DESC adapterDesc{};
		Check(adapter->GetDesc(&adapterDesc), "GetDesc");
		std::wcout << L"adapter=" << adapterDesc.Description << L'\n';

		ComPtr<ID3D11ComputeShader> shader;
		Check(device->CreateComputeShader(code->GetBufferPointer(), code->GetBufferSize(), nullptr,
			shader.GetAddressOf()), "CreateComputeShader");
		D3D11_SAMPLER_DESC samplerDesc{};
		samplerDesc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
		samplerDesc.AddressU = samplerDesc.AddressV = samplerDesc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
		samplerDesc.MaxLOD = D3D11_FLOAT32_MAX;
		ComPtr<ID3D11SamplerState> sampler;
		Check(device->CreateSamplerState(&samplerDesc, sampler.GetAddressOf()), "CreateSamplerState");
		D3D11_BUFFER_DESC constantsDesc{};
		constantsDesc.ByteWidth = sizeof(Params);
		constantsDesc.Usage = D3D11_USAGE_DEFAULT;
		constantsDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
		ComPtr<ID3D11Buffer> constants;
		Check(device->CreateBuffer(&constantsDesc, nullptr, constants.GetAddressOf()), "CreateBuffer");

		constexpr UINT width = 2496;
		constexpr UINT height = 2688;
		BenchmarkTier(device.Get(), context.Get(), shader.Get(), sampler.Get(), constants.Get(), width, height, 33);
		BenchmarkTier(device.Get(), context.Get(), shader.Get(), sampler.Get(), constants.Get(), width, height, 50);
		return 0;
	} catch (const std::exception& error) {
		std::cerr << error.what() << '\n';
		return 2;
	}
}
