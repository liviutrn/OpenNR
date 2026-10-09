#pragma once

#include <algorithm>
#include <array>
#include <cmath>

namespace FoveatedRenderImpl::GazeCropPolicy
{
	struct AdaptiveSettings
	{
		float smoothingMs = 60.0f;
		float responsiveness = 8.0f;
		float slowPercent = 10.0f;
		float fastPercent = 100.0f;
		float jumpPercent = 100.0f;
		float jumpSpeed = 20.0f;
		float maxLagPercent = 25.0f;
	};

	inline float FiniteClamp(float value, float fallback, float minimum, float maximum)
	{
		return std::clamp(std::isfinite(value) ? value : fallback, minimum, maximum);
	}

	/** Filter crop-relative noise with bounded lag and immediate large-movement response. */
	struct AdaptiveFilter
	{
		std::array<float, 2> previousSample{};
		std::array<float, 2> velocity{};
		bool valid = false;

		void Reset(const std::array<float, 2>& sample)
		{
			previousSample = sample;
			velocity = {};
			valid = true;
		}

		std::array<float, 2> Update(const std::array<float, 2>& previous,
			const std::array<float, 2>& sample, float deltaMs,
			float referenceWidth, float referenceHeight, const AdaptiveSettings& config)
		{
			if (!std::isfinite(sample[0]) || !std::isfinite(sample[1]))
				return previous;
			if (!valid) {
				Reset(sample);
				return sample;
			}
			const float elapsed = FiniteClamp(deltaMs, 11.1f, 0.1f, 100.0f);
			const std::array<float, 2> extent{
				FiniteClamp(referenceWidth, 0.5f, 0.01f, 1.0f),
				FiniteClamp(referenceHeight, 0.5f, 0.01f, 1.0f) };
			const float derivativeAlpha = 1.0f - std::exp(-elapsed / 20.0f);
			std::array<float, 2> displacement{};
			float rawSpeedSquared = 0.0f;
			for (unsigned axis = 0; axis < 2; ++axis) {
				const float derivative = (sample[axis] - previousSample[axis]) / extent[axis] * 1000.0f / elapsed;
				velocity[axis] += derivativeAlpha * (derivative - velocity[axis]);
				rawSpeedSquared += derivative * derivative;
				displacement[axis] = (sample[axis] - previous[axis]) / extent[axis];
			}
			previousSample = sample;
			const float distance = std::hypot(displacement[0], displacement[1]);
			const float speed = std::hypot(velocity[0], velocity[1]);
			const float smoothing = FiniteClamp(config.smoothingMs, 60.0f, 0.0f, 250.0f);
			const float jump = FiniteClamp(config.jumpPercent, 100.0f, 5.0f, 200.0f) * 0.01f;
			const float jumpSpeed = FiniteClamp(config.jumpSpeed, 20.0f, 1.0f, 100.0f);
			if (smoothing == 0.0f || distance >= jump || std::sqrt(rawSpeedSquared) >= jumpSpeed) {
				Reset(sample);
				return sample;
			}
			const float slow = FiniteClamp(config.slowPercent, 10.0f, 0.0f, 50.0f) * 0.01f;
			const float fast = std::max(slow + 0.01f, FiniteClamp(config.fastPercent, 100.0f, 5.0f, 200.0f) * 0.01f);
			const float t = std::clamp((distance - slow) / (fast - slow), 0.0f, 1.0f);
			const float distanceResponse = t * t * (3.0f - 2.0f * t);
			const float gain = FiniteClamp(config.responsiveness, 8.0f, 0.0f, 50.0f);
			const float timeConstant = smoothing / (1.0f + gain * speed);
			const float baseAlpha = 1.0f - std::exp(-elapsed / std::max(timeConstant, 0.1f));
			float alpha = baseAlpha + (1.0f - baseAlpha) * distanceResponse;
			const float maxLag = FiniteClamp(config.maxLagPercent, 25.0f, 0.0f, 50.0f) * 0.01f;
			if (distance > 0.0f)
				alpha = std::max(alpha, 1.0f - maxLag / distance);
			return { std::clamp(previous[0] + (sample[0] - previous[0]) * alpha, 0.0f, 1.0f),
				std::clamp(previous[1] + (sample[1] - previous[1]) * alpha, 0.0f, 1.0f) };
		}
	};
}
