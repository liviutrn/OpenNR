#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace FoveatedRenderImpl::GazeCropPolicy
{
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

	/** Retain a stable crop inside a small central guard; recenter without slew outside it. */
	inline float ResolveOrigin(float previous, float sample, float extent,
		std::uint32_t pixels, std::uint32_t quantizationPixels, bool havePrevious)
	{
		const float maxOrigin = std::max(0.0f, 1.0f - extent);
		const float desired = std::clamp(sample - extent * 0.5f, 0.0f, maxOrigin);
		const float guard = std::min(0.02f, extent * 0.05f);
		if (havePrevious && std::abs(desired - previous) <= guard)
			return previous;
		// Quantization must not place the tracked point outside the central guard.
		const float step = pixels ? std::min(static_cast<float>(quantizationPixels) / static_cast<float>(pixels), guard) : 0.0f;
		return step > 0.0f ? std::clamp(std::round(desired / step) * step, 0.0f, maxOrigin) : desired;
	}
}
