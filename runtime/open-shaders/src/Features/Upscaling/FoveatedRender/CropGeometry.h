#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace FoveatedRenderImpl::CropGeometry
{
	struct PixelRect
	{
		std::uint32_t x = 0;
		std::uint32_t y = 0;
		std::uint32_t width = 0;
		std::uint32_t height = 0;
	};

	struct EyePlan
	{
		PixelRect input;
		PixelRect output;
	};

	struct FramePlan
	{
		std::uint32_t fullInputWidth = 0;
		std::uint32_t fullInputHeight = 0;
		std::uint32_t fullOutputWidth = 0;
		std::uint32_t fullOutputHeight = 0;
		std::array<EyePlan, 2> eyes{};
	};

	inline PixelRect MakePixelRect(float x, float y, float width, float height,
		std::uint32_t fullWidth, std::uint32_t fullHeight)
	{
		if (!fullWidth || !fullHeight)
			return {};

		const auto normalized = [](float value) {
			return std::clamp(std::isfinite(value) ? value : 0.0f, 0.0f, 1.0f);
		};
		const auto toPixels = [](float value, std::uint32_t dimension) {
			return static_cast<std::uint32_t>(static_cast<double>(value) * dimension);
		};
		const auto left = std::min(toPixels(normalized(x), fullWidth), fullWidth - 1);
		const auto top = std::min(toPixels(normalized(y), fullHeight), fullHeight - 1);
		const auto rectWidth = std::clamp(toPixels(normalized(width), fullWidth), 1u, fullWidth - left);
		const auto rectHeight = std::clamp(toPixels(normalized(height), fullHeight), 1u, fullHeight - top);
		return { left, top, rectWidth, rectHeight };
	}

	inline EyePlan MakeEyePlan(float x, float y, float width, float height,
		std::uint32_t fullInputWidth, std::uint32_t fullInputHeight,
		std::uint32_t fullOutputWidth, std::uint32_t fullOutputHeight)
	{
		return {
			.input = MakePixelRect(x, y, width, height, fullInputWidth, fullInputHeight),
			.output = MakePixelRect(x, y, width, height, fullOutputWidth, fullOutputHeight),
		};
	}

	inline std::array<float, 2> MotionVectorScale(std::uint32_t fullWidth, std::uint32_t fullHeight,
		const PixelRect& crop)
	{
		return {
			crop.width ? static_cast<float>(fullWidth) / crop.width : 1.0f,
			crop.height ? static_cast<float>(fullHeight) / crop.height : 1.0f,
		};
	}
}
