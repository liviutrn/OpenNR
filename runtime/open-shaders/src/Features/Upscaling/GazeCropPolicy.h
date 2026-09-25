#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace FoveatedRenderImpl::GazeCropPolicy
{
	inline bool ShouldResetHistory(bool hasGaze, bool cropWasDynamic, bool inputsChanged)
	{
		return !hasGaze || !cropWasDynamic || inputsChanged;
	}

	struct Region
	{
		float x = 0.0f;
		float y = 0.0f;
		float w = 1.0f;
		float h = 1.0f;
	};

	/** Expand a normalized crop by the same pixel margin on all four sides. */
	inline Region ExpandRegion(Region region,
		std::uint32_t width, std::uint32_t height, std::uint32_t paddingPixels)
	{
		if (!width || !height || !paddingPixels)
			return region;

		const float padX = static_cast<float>(paddingPixels) / static_cast<float>(width);
		const float padY = static_cast<float>(paddingPixels) / static_cast<float>(height);
		const float newWidth = std::min(1.0f, region.w + 2.0f * padX);
		const float newHeight = std::min(1.0f, region.h + 2.0f * padY);
		const float centerX = region.x + region.w * 0.5f;
		const float centerY = region.y + region.h * 0.5f;
		region.w = newWidth;
		region.h = newHeight;
		region.x = std::clamp(centerX - newWidth * 0.5f, 0.0f, 1.0f - newWidth);
		region.y = std::clamp(centerY - newHeight * 0.5f, 0.0f, 1.0f - newHeight);
		return region;
	}

	/** Smooth fixation noise only; deliberate eye movement bypasses the filter. */
	inline std::array<float, 2> Filter(const std::array<float, 2>& previous,
		const std::array<float, 2>& sample, float deltaMs, float smoothingMs,
		std::uint32_t width, std::uint32_t height)
	{
		if (!width || !height ||
			std::abs(sample[0] - previous[0]) * static_cast<float>(width) > 2.0f ||
			std::abs(sample[1] - previous[1]) * static_cast<float>(height) > 2.0f)
			return sample;
		const float duration = std::clamp(std::isfinite(smoothingMs) ? smoothingMs : 0.0f, 0.0f, 250.0f);
		const float elapsed = std::clamp(std::isfinite(deltaMs) ? deltaMs : 16.67f, 0.1f, 250.0f);
		const float alpha = duration > 0.0f ? elapsed / (duration + elapsed) : 1.0f;
		return { previous[0] + (sample[0] - previous[0]) * alpha,
			previous[1] + (sample[1] - previous[1]) * alpha };
	}

	inline std::array<float, 2> Predict(const std::array<float, 2>& previousRaw,
		const std::array<float, 2>& sample, float deltaMs, float predictionMs,
		std::uint32_t width, std::uint32_t height)
	{
		const float dt = std::clamp(std::isfinite(deltaMs) ? deltaMs : 16.67f, 0.1f, 250.0f);
		const float horizon = std::clamp(std::isfinite(predictionMs) ? predictionMs : 0.0f, 0.0f, 15.0f);
		if (!width || !height || horizon == 0.0f)
			return sample;
		float dx = (sample[0] - previousRaw[0]) * (horizon / dt);
		float dy = (sample[1] - previousRaw[1]) * (horizon / dt);
		const float lengthPixels = std::hypot(dx * width, dy * height);
		if (lengthPixels > 48.0f) {
			const float scale = 48.0f / lengthPixels;
			dx *= scale;
			dy *= scale;
		}
		return { std::clamp(sample[0] + dx, 0.0f, 1.0f),
			std::clamp(sample[1] + dy, 0.0f, 1.0f) };
	}

	inline std::array<float, 2> FilterAdaptive(const std::array<float, 2>& previous,
		const std::array<float, 2>& sample, float deltaMs, float fixationMs,
		float catchupMs, std::uint32_t deadbandPixels,
		std::uint32_t width, std::uint32_t height)
	{
		if (!width || !height)
			return sample;
		const float dx = (sample[0] - previous[0]) * width;
		const float dy = (sample[1] - previous[1]) * height;
		const float distance = std::hypot(dx, dy);
		if (distance <= static_cast<float>(deadbandPixels))
			return previous;
		const float tau = distance >= 8.0f ? catchupMs : fixationMs;
		const float dt = std::clamp(std::isfinite(deltaMs) ? deltaMs : 16.67f, 0.1f, 250.0f);
		const float duration = std::clamp(std::isfinite(tau) ? tau : 0.0f, 0.0f, 100.0f);
		const float alpha = duration > 0.0f ? 1.0f - std::exp(-dt / duration) : 1.0f;
		return { previous[0] + (sample[0] - previous[0]) * alpha,
			previous[1] + (sample[1] - previous[1]) * alpha };
	}

	/** Hold the crop inside its movement guard and ease toward the live origin outside it. */
	inline float ResolveOrigin(float previous, float sample, float extent,
		std::uint32_t pixels, std::uint32_t quantizationPixels, bool havePrevious,
		float deltaMs = 16.67f, float catchupMs = 0.0f)
	{
		const float maxOrigin = std::max(0.0f, 1.0f - extent);
		const float desired = std::clamp(sample - extent * 0.5f, 0.0f, maxOrigin);
		const float guard = std::max(std::min(0.02f, extent * 0.05f),
			pixels ? static_cast<float>(quantizationPixels) / static_cast<float>(pixels) : 0.0f);
		if (havePrevious && std::abs(desired - previous) <= guard)
			return previous;
		if (!havePrevious)
			return desired;

		const float dt = std::clamp(std::isfinite(deltaMs) ? deltaMs : 16.67f, 0.1f, 250.0f);
		const float duration = std::clamp(std::isfinite(catchupMs) ? catchupMs : 0.0f, 0.0f, 100.0f);
		const float alpha = duration > 0.0f ? 1.0f - std::exp(-dt / duration) : 1.0f;
		return std::clamp(previous + (desired - previous) * alpha, 0.0f, maxOrigin);
	}
}
