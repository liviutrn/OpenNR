#pragma once

#include "Renderer.h"
#include "Utils/Subrect.h"

#include <array>
#include <cstdint>

struct ID3D11Device;
struct ID3D11DeviceContext;
struct ID3D11Resource;
struct ID3D11UnorderedAccessView;
struct ID3D11ShaderResourceView;

namespace NeuralRendering::CenterShared
{
	struct EyeInput
	{
		Renderer::StereoEyeInput guide;
		ID3D11ShaderResourceView* motionSRV = nullptr;
		Util::Subrect::UVRegion crop;
	};

	/** @brief Runs one center Feature 18 evaluation and adds its residual to the original stereo image. */
	bool Apply(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Resource* stereoColor,
		const std::array<EyeInput, 2>& eyes, std::uint32_t guideWidth, std::uint32_t guideHeight,
		std::uint32_t cropWidth, std::uint32_t cropHeight, std::uint32_t eyeWidth,
		std::uint32_t eyeHeight, const Tuning& tuning, std::uint32_t debugMode);

	/** @brief Releases center resources and shaders after a route or device reset. */
	void Reset();
}
