#pragma once

#include <algorithm>
#include <array>
#include <cmath>

namespace Sharpening
{
	inline constexpr float kMaximumStrength = 5.0f;

	/** Sanitizes the UI/configuration strength before rendering. */
	inline float Sanitize(float strength)
	{
		return std::isfinite(strength) ? std::clamp(strength, 0.0f, kMaximumStrength) : 0.0f;
	}

	/** Keeps the RCAS kernel bounded; extended strength amplifies its resolved detail. */
	inline std::array<float, 2> Resolve(float strength)
	{
		strength = Sanitize(strength);
		return { strength > 0.0f ? std::exp2(2.0f * std::min(strength, 1.0f) - 2.0f) : 0.0f,
			std::max(strength, 1.0f) };
	}
}
