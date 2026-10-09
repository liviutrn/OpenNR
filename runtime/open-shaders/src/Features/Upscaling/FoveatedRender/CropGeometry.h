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

	struct Sampling
	{
		std::array<float, 2> scale{ 1.0f, 1.0f };
		std::array<float, 2> offset{};
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
		const auto input = MakePixelRect(x, y, width, height, fullInputWidth, fullInputHeight);
		if (!input.width || !input.height || !fullOutputWidth || !fullOutputHeight)
			return {};
		const auto extent = [](std::uint32_t crop, std::uint32_t source, std::uint32_t target) {
			return std::clamp(static_cast<std::uint32_t>(std::lround(double(crop) * target / source)), 1u, target);
		};
		const auto outWidth = extent(input.width, fullInputWidth, fullOutputWidth);
		const auto outHeight = extent(input.height, fullInputHeight, fullOutputHeight);
		return { input, {
			std::min(static_cast<std::uint32_t>(std::uint64_t(input.x) * fullOutputWidth / fullInputWidth), fullOutputWidth - outWidth),
			std::min(static_cast<std::uint32_t>(std::uint64_t(input.y) * fullOutputHeight / fullInputHeight), fullOutputHeight - outHeight),
			outWidth, outHeight } };
	}

	/** Map display-grid centers to the crop-local SR sampling grid. */
	inline Sampling ColorSampling(const FramePlan& plan, std::uint32_t eye)
	{
		Sampling result;
		const auto& crop = plan.eyes[eye];
		if (!crop.input.width || !crop.input.height || !plan.fullOutputWidth || !plan.fullOutputHeight)
			return result;
		result.scale = {
			float(double(plan.fullInputWidth) * crop.output.width / (double(plan.fullOutputWidth) * crop.input.width)),
			float(double(plan.fullInputHeight) * crop.output.height / (double(plan.fullOutputHeight) * crop.input.height)) };
		result.offset = {
			float((double(crop.output.x) * plan.fullInputWidth / plan.fullOutputWidth - crop.input.x) * crop.output.width / crop.input.width),
			float((double(crop.output.y) * plan.fullInputHeight / plan.fullOutputHeight - crop.input.y) * crop.output.height / crop.input.height) };
		return result;
	}

	/** Map display-aligned guide centers to the original cropped render guides. */
	inline Sampling GuideSampling(const FramePlan& plan, std::uint32_t eye)
	{
		auto result = ColorSampling(plan, eye);
		const auto& crop = plan.eyes[eye];
		if (crop.output.width && crop.output.height) {
			result.offset[0] *= float(crop.input.width) / crop.output.width;
			result.offset[1] *= float(crop.input.height) / crop.output.height;
		}
		return result;
	}

	/** Describe a reduced model grid anchored to full-eye color coordinates. */
	inline std::array<float, 4> ModelSampling(std::uint32_t colorWidth, std::uint32_t colorHeight,
		std::uint32_t modelWidth, std::uint32_t modelHeight, std::uint32_t percent,
		std::uint32_t originX, std::uint32_t originY, bool anchored)
	{
		const double pitchX = anchored ? 100.0 / std::max(percent, 1u) : double(colorWidth) / std::max(modelWidth, 1u);
		const double pitchY = anchored ? 100.0 / std::max(percent, 1u) : double(colorHeight) / std::max(modelHeight, 1u);
		return { float(pitchX), float(pitchY),
			anchored ? float(std::floor(double(originX) / pitchX) * pitchX - originX) : 0.0f,
			anchored ? float(std::floor(double(originY) / pitchY) * pitchY - originY) : 0.0f };
	}

	/** Return scale and translation for full-eye NDC to cropped NDC. */
	inline std::array<float, 4> ClipTransform(std::uint32_t fullWidth, std::uint32_t fullHeight, const PixelRect& crop)
	{
		if (!crop.width || !crop.height)
			return { 1, 1, 0, 0 };
		return { float(fullWidth) / crop.width, float(fullHeight) / crop.height,
			float((double(fullWidth) - 2.0 * crop.x - crop.width) / crop.width),
			float((2.0 * crop.y + crop.height - fullHeight) / crop.height) };
	}

	/** Native NR consumes guide-pixel units, independently of shader model-pixel reprojection. */
	inline float NativeGuideMotionScale(float guideScale, std::uint32_t modelExtent, std::uint32_t colorExtent)
	{
		return colorExtent ? guideScale * static_cast<float>(modelExtent) / colorExtent : 0.0f;
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
