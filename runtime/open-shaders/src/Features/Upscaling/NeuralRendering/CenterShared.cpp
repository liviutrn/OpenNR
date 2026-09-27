#include "CenterShared.h"

#include "Globals.h"
#include "GpuPass.h"
#include "Util.h"
#include "Utils/D3D.h"
#include "Utils/Game.h"

#if defined(ENABLE_SKYRIM_VR)
#	include "RE/B/BSOpenVR.h"
#endif

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <d3d11.h>
#include <dxgi.h>
#include <wrl/client.h>

namespace NeuralRendering::CenterShared
{
	namespace
	{
		using Microsoft::WRL::ComPtr;

		struct Surface
		{
			ComPtr<ID3D11Texture2D> texture;
			ComPtr<ID3D11ShaderResourceView> srv;
			ComPtr<ID3D11UnorderedAccessView> uav;
		};

		struct alignas(16) Constants
		{
			float eyeFrustum[2][4]{};
			float eyeOffset[2][4]{};
			float eyeCrop[2][4]{};
			float eyeMotionScale[2][4]{};
			float centerFrustum[4]{};
			float centerCrop[4]{};
			float sourceRect[2][4]{};
			float frameSize[4]{};
			float guideSize[4]{};
			float depthRange[4]{};
			std::uint32_t debugMode = 0;
			float padding[3]{};
		};

		struct State
		{
			Surface originalStereo;
			Surface centerBase;
			Surface centerNeural;
			Surface centerDepthColor;
			Surface centerConfidence;
			Surface centerDepthGuide;
			Surface centerMotionGuide;
			Surface centerResidual;
			Surface finalStereo;
			ComPtr<ID3D11ComputeShader> buildShader;
			ComPtr<ID3D11ComputeShader> guideShader;
			ComPtr<ID3D11ComputeShader> residualShader;
			ComPtr<ID3D11ComputeShader> warpShader;
			ComPtr<ID3D11Buffer> constants;
			ComPtr<ID3D11SamplerState> pointSampler;
			ComPtr<ID3D11SamplerState> linearSampler;
			std::uint32_t frameWidth = 0;
			std::uint32_t frameHeight = 0;
			std::uint32_t cropWidth = 0;
			std::uint32_t cropHeight = 0;
			std::uint32_t guideWidth = 0;
			std::uint32_t guideHeight = 0;
			DXGI_FORMAT colorFormat = DXGI_FORMAT_UNKNOWN;
			float previousCrop[2][4]{};
			bool previousCropValid = false;
		};

		State state;

		bool CreateSurface(ID3D11Device* device, Surface& surface, std::uint32_t width,
			std::uint32_t height, DXGI_FORMAT resourceFormat, DXGI_FORMAT viewFormat,
			bool unorderedAccess, const char* name)
		{
			D3D11_TEXTURE2D_DESC desc{};
			desc.Width = width;
			desc.Height = height;
			desc.MipLevels = 1;
			desc.ArraySize = 1;
			desc.Format = resourceFormat;
			desc.SampleDesc.Count = 1;
			desc.Usage = D3D11_USAGE_DEFAULT;
			desc.BindFlags = D3D11_BIND_SHADER_RESOURCE |
				(unorderedAccess ? D3D11_BIND_UNORDERED_ACCESS : 0);
			if (FAILED(device->CreateTexture2D(&desc, nullptr, &surface.texture)))
				return false;
			Util::SetResourceName(surface.texture.Get(), name);
			D3D11_SHADER_RESOURCE_VIEW_DESC srvDesc{};
			srvDesc.Format = viewFormat;
			srvDesc.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
			srvDesc.Texture2D.MipLevels = 1;
			if (FAILED(device->CreateShaderResourceView(surface.texture.Get(), &srvDesc, &surface.srv)))
				return false;
			Util::SetResourceName(surface.srv.Get(), name);
			if (unorderedAccess) {
				D3D11_UNORDERED_ACCESS_VIEW_DESC uavDesc{};
				uavDesc.Format = viewFormat;
				uavDesc.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
				if (FAILED(device->CreateUnorderedAccessView(surface.texture.Get(), &uavDesc, &surface.uav)))
					return false;
				Util::SetResourceName(surface.uav.Get(), name);
			}
			return true;
		}

		bool CreateShader(ComPtr<ID3D11ComputeShader>& shader, const wchar_t* path, const char* name)
		{
			shader.Attach(static_cast<ID3D11ComputeShader*>(Util::CompileShader(path, {}, "cs_5_0")));
			if (!shader)
				return false;
			Util::SetResourceName(shader.Get(), name);
			return true;
		}

		bool EnsureShaders(ID3D11Device* device)
		{
			if (!state.buildShader &&
				!CreateShader(state.buildShader,
					L"Data\\Shaders\\Upscaling\\NeuralRendering\\CenterSharedBuildCS.hlsl",
					"NeuralRendering::CenterSharedBuild"))
				return false;
			if (!state.guideShader &&
				!CreateShader(state.guideShader,
					L"Data\\Shaders\\Upscaling\\NeuralRendering\\CenterSharedGuideCS.hlsl",
					"NeuralRendering::CenterSharedGuide"))
				return false;
			if (!state.residualShader &&
				!CreateShader(state.residualShader,
					L"Data\\Shaders\\Upscaling\\NeuralRendering\\CenterSharedResidualCS.hlsl",
					"NeuralRendering::CenterSharedResidual"))
				return false;
			if (!state.warpShader &&
				!CreateShader(state.warpShader,
					L"Data\\Shaders\\Upscaling\\NeuralRendering\\CenterSharedWarpCS.hlsl",
					"NeuralRendering::CenterSharedWarp"))
				return false;
			if (!state.constants) {
				D3D11_BUFFER_DESC desc{};
				desc.ByteWidth = sizeof(Constants);
				desc.Usage = D3D11_USAGE_DYNAMIC;
				desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				desc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
				if (FAILED(device->CreateBuffer(&desc, nullptr, &state.constants)))
					return false;
				Util::SetResourceName(state.constants.Get(), "NeuralRendering::CenterSharedConstants");
			}
			if (!state.pointSampler || !state.linearSampler) {
				D3D11_SAMPLER_DESC desc{};
				desc.Filter = D3D11_FILTER_MIN_MAG_MIP_POINT;
				desc.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
				desc.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
				desc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
				desc.MaxLOD = D3D11_FLOAT32_MAX;
				if (FAILED(device->CreateSamplerState(&desc, &state.pointSampler)))
					return false;
				Util::SetResourceName(state.pointSampler.Get(), "NeuralRendering::CenterSharedPointSampler");
				desc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
				if (FAILED(device->CreateSamplerState(&desc, &state.linearSampler)))
					return false;
				Util::SetResourceName(state.linearSampler.Get(), "NeuralRendering::CenterSharedLinearSampler");
			}
			return true;
		}

		bool EnsureSurfaces(ID3D11Device* device, std::uint32_t frameWidth,
			std::uint32_t frameHeight, std::uint32_t cropWidth, std::uint32_t cropHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight, DXGI_FORMAT colorFormat)
		{
			if (state.originalStereo.texture && state.frameWidth == frameWidth &&
				state.frameHeight == frameHeight && state.cropWidth == cropWidth &&
				state.cropHeight == cropHeight && state.guideWidth == guideWidth &&
				state.guideHeight == guideHeight && state.colorFormat == colorFormat)
				return true;
			Renderer::Instance().ResetHistory();
			state.originalStereo = {};
			state.centerBase = {};
			state.centerNeural = {};
			state.centerDepthColor = {};
			state.centerConfidence = {};
			state.centerDepthGuide = {};
			state.centerMotionGuide = {};
			state.centerResidual = {};
			state.finalStereo = {};
			state.frameWidth = frameWidth;
			state.frameHeight = frameHeight;
			state.cropWidth = cropWidth;
			state.cropHeight = cropHeight;
			state.guideWidth = guideWidth;
			state.guideHeight = guideHeight;
			state.colorFormat = colorFormat;
		state.previousCropValid = false;
			return
				CreateSurface(device, state.originalStereo, frameWidth, frameHeight,
					colorFormat, colorFormat, false, "NeuralRendering::OriginalStereo") &&
				CreateSurface(device, state.centerBase, cropWidth, cropHeight,
					colorFormat, colorFormat, true, "NeuralRendering::CenterBase") &&
				CreateSurface(device, state.centerNeural, cropWidth, cropHeight,
					colorFormat, colorFormat, true, "NeuralRendering::CenterNeural") &&
				CreateSurface(device, state.centerDepthColor, cropWidth, cropHeight,
					DXGI_FORMAT_R32_FLOAT, DXGI_FORMAT_R32_FLOAT, true,
					"NeuralRendering::CenterDepthColor") &&
				CreateSurface(device, state.centerConfidence, cropWidth, cropHeight,
					DXGI_FORMAT_R16_FLOAT, DXGI_FORMAT_R16_FLOAT, true,
					"NeuralRendering::CenterConfidence") &&
				CreateSurface(device, state.centerDepthGuide, guideWidth, guideHeight,
					DXGI_FORMAT_R32_TYPELESS, DXGI_FORMAT_R32_FLOAT, true,
					"NeuralRendering::CenterDepthGuide") &&
				CreateSurface(device, state.centerMotionGuide, guideWidth, guideHeight,
					DXGI_FORMAT_R16G16_FLOAT, DXGI_FORMAT_R16G16_FLOAT, true,
					"NeuralRendering::CenterMotionGuide") &&
				CreateSurface(device, state.centerResidual, cropWidth, cropHeight,
					DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT, true,
					"NeuralRendering::CenterResidual") &&
				CreateSurface(device, state.finalStereo, frameWidth, frameHeight,
					colorFormat, colorFormat, true, "NeuralRendering::CenterFinalStereo");
		}

		bool LoadGeometry(Constants& constants, const std::array<EyeInput, 2>& eyes)
		{
#if defined(ENABLE_SKYRIM_VR)
			auto* openVR = RE::BSOpenVR::GetSingleton();
			if (!openVR || !openVR->vrSystem || !globals::game::isVR)
				return false;
			float eyeTranslation[2][3]{};
			for (std::uint32_t eye = 0; eye < 2; ++eye) {
				const auto vrEye = eye == 0 ? vr::Eye_Left : vr::Eye_Right;
				openVR->vrSystem->GetProjectionRaw(vrEye,
					&constants.eyeFrustum[eye][0], &constants.eyeFrustum[eye][1],
					&constants.eyeFrustum[eye][2], &constants.eyeFrustum[eye][3]);
				const auto eyeToHead = openVR->vrSystem->GetEyeToHeadTransform(vrEye);
				for (std::uint32_t axis = 0; axis < 3; ++axis)
					eyeTranslation[eye][axis] = eyeToHead.m[axis][3];
				const auto& crop = eyes[eye].crop;
				constants.eyeCrop[eye][0] = crop.x;
				constants.eyeCrop[eye][1] = crop.y;
				constants.eyeCrop[eye][2] = crop.w;
				constants.eyeCrop[eye][3] = crop.h;
			}
			const float openVRSeparation = std::abs(eyeTranslation[1][0] - eyeTranslation[0][0]);
			const auto leftWorld = Util::GetEyePosition(0);
			const auto rightWorld = Util::GetEyePosition(1);
			const float dx = rightWorld.x - leftWorld.x;
			const float dy = rightWorld.y - leftWorld.y;
			const float dz = rightWorld.z - leftWorld.z;
			const float gameSeparation = std::sqrt(dx * dx + dy * dy + dz * dz);
			if (openVRSeparation < 0.03f || openVRSeparation > 0.10f ||
				gameSeparation < 0.1f || gameSeparation > 20.0f)
				return false;
			const float gameUnitsPerMeter = gameSeparation / openVRSeparation;
			for (std::uint32_t eye = 0; eye < 2; ++eye) {
				for (std::uint32_t axis = 0; axis < 3; ++axis) {
					constants.eyeOffset[eye][axis] =
						(eyeTranslation[eye][axis] -
							(eyeTranslation[0][axis] + eyeTranslation[1][axis]) * 0.5f) *
						gameUnitsPerMeter;
				}
			}
			for (std::uint32_t axis = 0; axis < 4; ++axis)
				constants.centerFrustum[axis] =
					(constants.eyeFrustum[0][axis] + constants.eyeFrustum[1][axis]) * 0.5f;
			constants.centerCrop[0] = (constants.eyeCrop[0][0] + constants.eyeCrop[1][0]) * 0.5f;
			constants.centerCrop[1] = (constants.eyeCrop[0][1] + constants.eyeCrop[1][1]) * 0.5f;
			constants.centerCrop[2] = constants.eyeCrop[0][2];
			constants.centerCrop[3] = constants.eyeCrop[0][3];
			const auto cameraData = Util::GetCameraData();
			constants.depthRange[0] = cameraData.y;
			constants.depthRange[1] = cameraData.x;
			return cameraData.y > 0.0f && cameraData.x > cameraData.y &&
				constants.centerFrustum[1] > constants.centerFrustum[0] &&
				std::abs(constants.centerFrustum[3] - constants.centerFrustum[2]) > 0.01f;
#else
			(void)constants;
			(void)eyes;
			return false;
#endif
		}

		bool UpdateConstants(ID3D11DeviceContext* context, const Constants& constants)
		{
			D3D11_MAPPED_SUBRESOURCE mapped{};
			if (FAILED(context->Map(state.constants.Get(), 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped)) ||
				!mapped.pData)
				return false;
			std::memcpy(mapped.pData, &constants, sizeof(constants));
			context->Unmap(state.constants.Get(), 0);
			return true;
		}

		void Dispatch(ID3D11DeviceContext* context, ID3D11ComputeShader* shader,
			const std::array<ID3D11ShaderResourceView*, 9>& sources,
			const std::array<ID3D11UnorderedAccessView*, 3>& targets,
			std::uint32_t width, std::uint32_t height)
		{
			context->CSSetShader(shader, nullptr, 0);
			ID3D11Buffer* cb = state.constants.Get();
			context->CSSetConstantBuffers(0, 1, &cb);
			ID3D11SamplerState* samplers[2]{ state.pointSampler.Get(), state.linearSampler.Get() };
			context->CSSetSamplers(0, 2, samplers);
			context->CSSetShaderResources(0, static_cast<UINT>(sources.size()), sources.data());
			context->CSSetUnorderedAccessViews(0, static_cast<UINT>(targets.size()), targets.data(), nullptr);
			context->Dispatch((width + 7) / 8, (height + 7) / 8, 1);
			std::array<ID3D11ShaderResourceView*, 9> nullSources{};
			std::array<ID3D11UnorderedAccessView*, 3> nullTargets{};
			context->CSSetShaderResources(0, static_cast<UINT>(nullSources.size()), nullSources.data());
			context->CSSetUnorderedAccessViews(0, static_cast<UINT>(nullTargets.size()), nullTargets.data(), nullptr);
			ID3D11Buffer* nullCB = nullptr;
			context->CSSetConstantBuffers(0, 1, &nullCB);
			context->CSSetShader(nullptr, nullptr, 0);
		}
	}

	bool Apply(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Resource* stereoColor,
		const std::array<EyeInput, 2>& eyes, std::uint32_t guideWidth, std::uint32_t guideHeight,
		std::uint32_t cropWidth, std::uint32_t cropHeight, std::uint32_t eyeWidth,
		std::uint32_t eyeHeight, const Tuning& tuning, std::uint32_t debugMode)
	{
		CS_GPU_PASS("Feature18CenterShared::Total");
		if (!device || !context || !stereoColor || !guideWidth || !guideHeight ||
			!cropWidth || !cropHeight || !eyeWidth || !eyeHeight)
			return false;
		ComPtr<ID3D11Texture2D> sourceTexture;
		if (FAILED(stereoColor->QueryInterface(IID_PPV_ARGS(&sourceTexture))))
			return false;
		D3D11_TEXTURE2D_DESC sourceDesc{};
		sourceTexture->GetDesc(&sourceDesc);
		if (sourceDesc.Width != 2 * eyeWidth || sourceDesc.Height != eyeHeight ||
			sourceDesc.SampleDesc.Count != 1 || sourceDesc.MipLevels != 1)
			return false;
		for (const auto& eye : eyes) {
			if (!eye.guide.depth || !eye.guide.depthSRV || !eye.guide.motionVectors ||
				!eye.motionSRV || eye.crop.w <= 0.0f || eye.crop.h <= 0.0f)
				return false;
			ComPtr<ID3D11Texture2D> depth;
			if (FAILED(eye.guide.depth->QueryInterface(IID_PPV_ARGS(&depth))))
				return false;
			D3D11_TEXTURE2D_DESC depthDesc{};
			depth->GetDesc(&depthDesc);
			if (depthDesc.Width != guideWidth || depthDesc.Height != guideHeight)
				return false;
		}
		if (std::abs(eyes[0].crop.w - eyes[1].crop.w) > 0.0001f ||
			std::abs(eyes[0].crop.h - eyes[1].crop.h) > 0.0001f)
			return false;
		Constants constants{};
		if (!LoadGeometry(constants, eyes))
			return false;
		constants.frameSize[0] = static_cast<float>(sourceDesc.Width);
		constants.frameSize[1] = static_cast<float>(sourceDesc.Height);
		constants.frameSize[2] = 1.0f / cropWidth;
		constants.frameSize[3] = 1.0f / cropHeight;
		constants.guideSize[0] = static_cast<float>(guideWidth);
		constants.guideSize[1] = static_cast<float>(guideHeight);
		constants.guideSize[2] = 1.0f / guideWidth;
		constants.guideSize[3] = 1.0f / guideHeight;
		constants.debugMode = std::min(debugMode, 6u);
		for (std::uint32_t eye = 0; eye < 2; ++eye) {
			constants.sourceRect[eye][0] = static_cast<float>(eyes[eye].guide.sourceX);
			constants.sourceRect[eye][1] = static_cast<float>(eyes[eye].guide.sourceY);
			constants.sourceRect[eye][2] = static_cast<float>(cropWidth);
			constants.sourceRect[eye][3] = static_cast<float>(cropHeight);
			constants.eyeMotionScale[eye][0] = eyes[eye].guide.motionVectorScaleX / guideWidth;
			constants.eyeMotionScale[eye][1] = eyes[eye].guide.motionVectorScaleY / guideHeight;
			if (eyes[eye].guide.sourceX + cropWidth > sourceDesc.Width ||
				eyes[eye].guide.sourceY + cropHeight > sourceDesc.Height)
				return false;
		}
		if (!EnsureShaders(device) ||
			!EnsureSurfaces(device, sourceDesc.Width, sourceDesc.Height, cropWidth, cropHeight,
				guideWidth, guideHeight, sourceDesc.Format) ||
			!UpdateConstants(context, constants))
			return false;
		if (state.previousCropValid) {
			bool cropChanged = false;
			for (std::uint32_t eye = 0; eye < 2; ++eye)
				for (std::uint32_t component = 0; component < 4; ++component)
					cropChanged |= std::abs(state.previousCrop[eye][component] -
						constants.eyeCrop[eye][component]) > 0.0001f;
			if (cropChanged)
				Renderer::Instance().ResetHistory();
		}
		std::memcpy(state.previousCrop, constants.eyeCrop, sizeof(state.previousCrop));
		state.previousCropValid = true;

		context->CopyResource(state.originalStereo.texture.Get(), stereoColor);
		const std::array<ID3D11ShaderResourceView*, 9> buildSources{
			state.originalStereo.srv.Get(), eyes[0].guide.depthSRV, eyes[1].guide.depthSRV,
			eyes[0].motionSRV, eyes[1].motionSRV };
		{
			CS_GPU_PASS("Feature18CenterShared::StereoToCenter");
			Dispatch(context, state.guideShader.Get(), buildSources,
				{ state.centerDepthGuide.uav.Get(), state.centerMotionGuide.uav.Get() },
				guideWidth, guideHeight);
			Dispatch(context, state.buildShader.Get(), buildSources,
				{ state.centerBase.uav.Get(), state.centerDepthColor.uav.Get(),
					state.centerConfidence.uav.Get() }, cropWidth, cropHeight);
		}
		context->CopyResource(state.centerNeural.texture.Get(), state.centerBase.texture.Get());
		Tuning centerTuning = tuning;
		centerTuning.multiPass = 0;
		centerTuning.temporalReuseCadence = 0;
		centerTuning.adaptiveResolution = false;
		{
			CS_GPU_PASS("Feature18CenterShared::Feature18");
			if (!Renderer::Instance().Apply(device, context, 0,
					state.centerNeural.texture.Get(), state.centerDepthGuide.texture.Get(),
					state.centerDepthGuide.srv.Get(), state.centerMotionGuide.texture.Get(),
					guideWidth, guideHeight, cropWidth, cropHeight,
					static_cast<float>(guideWidth), static_cast<float>(guideHeight), centerTuning))
				return false;
		}
		{
			CS_GPU_PASS("Feature18CenterShared::ResidualToStereo");
			const std::array<ID3D11ShaderResourceView*, 9> residualSources{
				state.centerNeural.srv.Get(), state.centerBase.srv.Get() };
			Dispatch(context, state.residualShader.Get(), residualSources,
				{ state.centerResidual.uav.Get() }, cropWidth, cropHeight);
			const std::array<ID3D11ShaderResourceView*, 9> warpSources{
				state.originalStereo.srv.Get(), eyes[0].guide.depthSRV,
				eyes[1].guide.depthSRV, eyes[0].motionSRV, eyes[1].motionSRV,
				state.centerResidual.srv.Get(), state.centerDepthColor.srv.Get(),
				state.centerConfidence.srv.Get(), state.centerBase.srv.Get() };
			Dispatch(context, state.warpShader.Get(), warpSources,
				{ state.finalStereo.uav.Get() }, sourceDesc.Width, sourceDesc.Height);
			context->CopyResource(stereoColor, state.finalStereo.texture.Get());
		}
		return true;
	}

	void Reset()
	{
		state = {};
	}
}
