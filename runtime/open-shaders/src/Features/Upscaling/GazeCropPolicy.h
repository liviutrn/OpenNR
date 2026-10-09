#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace FoveatedRenderImpl::GazeCropPolicy
{
	/** Continuous, frame-rate-independent fixation filtering with fast saccade response. */
	inline std::array<float, 2> Filter(const std::array<float, 2>& previous,
		const std::array<float, 2>& sample, float deltaMs, float smoothingMs,
		std::uint32_t width, std::uint32_t height)
	{
		if (!width || !height)
			return sample;
		const float elapsed = std::clamp(std::isfinite(deltaMs) ? deltaMs : 16.67f, 0.1f, 50.0f);
		const float requested = std::clamp(std::isfinite(smoothingMs) ? smoothingMs : 0.0f, 0.0f, 250.0f);
		const float dx = (sample[0] - previous[0]) * static_cast<float>(width);
		const float dy = (sample[1] - previous[1]) * static_cast<float>(height);
		const float distancePixels = std::sqrt(dx * dx + dy * dy);

		if (requested == 0.0f)
			return sample;
		const float effectiveMs = requested;
		const float baseAlpha = 1.0f - std::exp(-elapsed / std::max(effectiveMs, 0.1f));
		const float motionBoost = std::clamp((distancePixels - 2.0f) / 24.0f, 0.0f, 1.0f);
		const float alpha = std::clamp(baseAlpha + (1.0f - baseAlpha) * motionBoost, 0.0f, 1.0f);
		return { previous[0] + (sample[0] - previous[0]) * alpha,
			previous[1] + (sample[1] - previous[1]) * alpha };
	}

	/** Resolve a bounded origin using the selected dead zone and quantization. */
	inline float ResolveOrigin(float previous, float sample, float extent,
		std::uint32_t pixels, std::uint32_t quantizationPixels, bool havePrevious,
		bool continuousOrigin = true, float deadZonePercent = 0.0f)
	{
		const float maxOrigin = std::max(0.0f, 1.0f - extent);
		const float desired = std::clamp(sample - extent * 0.5f, 0.0f, maxOrigin);
		if (!havePrevious || !std::isfinite(previous))
			return desired;
		previous = std::clamp(previous, 0.0f, maxOrigin);

		const float pixel = pixels ? 1.0f / static_cast<float>(pixels) : 0.0f;
		const float microPixels = std::clamp(static_cast<float>(std::max(quantizationPixels, 1u)) * 0.25f, 1.5f, 3.0f);
		const float microGuard = pixel * microPixels;
		const float userGuard = std::clamp((std::isfinite(deadZonePercent) ? deadZonePercent : 0.0f) * 0.01f, 0.0f, 0.10f);
		const bool directOrigin = continuousOrigin || (deadZonePercent == 0.0f && quantizationPixels == 0u);
		const float guard = directOrigin ? userGuard : std::max(microGuard, userGuard);
		if (std::abs(desired - previous) <= guard)
			return previous;

		const float step = pixels && quantizationPixels ?
			static_cast<float>(quantizationPixels) / static_cast<float>(pixels) : 0.0f;
		return step > 0.0f ? std::clamp(std::round(desired / step) * step, 0.0f, maxOrigin) : desired;
	}
}
