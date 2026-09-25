#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace NeuralRendering
{
	struct PixelCrop
	{
		std::uint32_t x = 0;
		std::uint32_t y = 0;
		std::uint32_t width = 0;
		std::uint32_t height = 0;
	};

	[[nodiscard]] inline PixelCrop ComputePixelCrop(float x, float y, float width, float height,
		std::uint32_t targetWidth, std::uint32_t targetHeight)
	{
		if (!targetWidth || !targetHeight)
			return {};

		x = std::clamp(std::isfinite(x) ? x : 0.0f, 0.0f, 1.0f);
		y = std::clamp(std::isfinite(y) ? y : 0.0f, 0.0f, 1.0f);
		width = std::clamp(std::isfinite(width) ? width : 0.0f, 0.0f, 1.0f);
		height = std::clamp(std::isfinite(height) ? height : 0.0f, 0.0f, 1.0f);

		const auto cropWidth = std::clamp(static_cast<std::uint32_t>(std::lround(width * targetWidth)), 1u, targetWidth);
		const auto cropHeight = std::clamp(static_cast<std::uint32_t>(std::lround(height * targetHeight)), 1u, targetHeight);
		const auto xOrigin = static_cast<std::uint32_t>(std::floor(x * targetWidth));
		const auto yOrigin = static_cast<std::uint32_t>(std::floor(y * targetHeight));
		return {
			std::min(xOrigin, targetWidth - cropWidth),
			std::min(yOrigin, targetHeight - cropHeight),
			cropWidth,
			cropHeight
		};
	}
}
