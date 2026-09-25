#pragma once

#include <algorithm>
#include <cstdint>

namespace NeuralRendering
{
	struct SecondPassCropRect
	{
		std::uint32_t x = 0;
		std::uint32_t y = 0;
		std::uint32_t width = 0;
		std::uint32_t height = 0;
	};

	struct SecondPassCropPlan
	{
		SecondPassCropRect color;
		SecondPassCropRect guides;
		SecondPassCropRect output;
		bool enabled = false;
	};

	[[nodiscard]] constexpr std::uint32_t ScaleCropDimension(std::uint32_t dimension, std::uint32_t percent)
	{
		return std::max<std::uint32_t>(1, static_cast<std::uint32_t>(
			(static_cast<std::uint64_t>(dimension) * percent + 50) / 100));
	}

	[[nodiscard]] constexpr SecondPassCropRect CenteredCrop(std::uint32_t width, std::uint32_t height,
		std::uint32_t reductionXPercent, std::uint32_t reductionYPercent)
	{
		const auto retainedXPercent = reductionXPercent <= 50 ? 100 - reductionXPercent : 100;
		const auto retainedYPercent = reductionYPercent <= 50 ? 100 - reductionYPercent : 100;
		const auto cropWidth = std::min(width, ScaleCropDimension(width, retainedXPercent));
		const auto cropHeight = std::min(height, ScaleCropDimension(height, retainedYPercent));
		return {
			.x = (width - cropWidth) / 2,
			.y = (height - cropHeight) / 2,
			.width = cropWidth,
			.height = cropHeight,
		};
	}

	[[nodiscard]] constexpr SecondPassCropRect CenteredCrop(std::uint32_t width, std::uint32_t height,
		std::uint32_t reductionPercent)
	{
		return CenteredCrop(width, height, reductionPercent, reductionPercent);
	}

	[[nodiscard]] constexpr SecondPassCropRect ScaleCrop(const SecondPassCropRect& crop,
		std::uint32_t sourceWidth, std::uint32_t sourceHeight,
		std::uint32_t destinationWidth, std::uint32_t destinationHeight)
	{
		if (sourceWidth == 0 || sourceHeight == 0 || destinationWidth == 0 || destinationHeight == 0)
			return {};
		const auto left = static_cast<std::uint32_t>(static_cast<std::uint64_t>(crop.x) * destinationWidth / sourceWidth);
		const auto top = static_cast<std::uint32_t>(static_cast<std::uint64_t>(crop.y) * destinationHeight / sourceHeight);
		const auto rightNumerator = static_cast<std::uint64_t>(crop.x + crop.width) * destinationWidth;
		const auto bottomNumerator = static_cast<std::uint64_t>(crop.y + crop.height) * destinationHeight;
		const auto right = std::min(destinationWidth, static_cast<std::uint32_t>(
			(rightNumerator + sourceWidth - 1) / sourceWidth));
		const auto bottom = std::min(destinationHeight, static_cast<std::uint32_t>(
			(bottomNumerator + sourceHeight - 1) / sourceHeight));
		return {
			.x = left,
			.y = top,
			.width = std::max<std::uint32_t>(1, right - left),
			.height = std::max<std::uint32_t>(1, bottom - top),
		};
	}

	[[nodiscard]] constexpr SecondPassCropPlan MakeSecondPassCropPlan(std::uint32_t width,
		std::uint32_t height, std::uint32_t guideWidth, std::uint32_t guideHeight,
		std::uint32_t reductionXPercent, std::uint32_t reductionYPercent)
	{
		const auto crop = CenteredCrop(width, height, reductionXPercent, reductionYPercent);
		const auto guides = ScaleCrop(crop, width, height, guideWidth, guideHeight);
		return {
			.color = crop,
			.guides = guides,
			.output = crop,
			.enabled = (reductionXPercent != 0 || reductionYPercent != 0) &&
				width > 0 && height > 0 && guideWidth > 0 && guideHeight > 0,
		};
	}

	[[nodiscard]] constexpr SecondPassCropPlan MakeSecondPassCropPlan(std::uint32_t width,
		std::uint32_t height, std::uint32_t guideWidth, std::uint32_t guideHeight,
		std::uint32_t reductionPercent)
	{
		return MakeSecondPassCropPlan(width, height, guideWidth, guideHeight,
			reductionPercent, reductionPercent);
	}
}
