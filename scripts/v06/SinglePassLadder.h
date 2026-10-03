#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <cmath>

namespace NeuralRendering::SinglePassLadder
{
	struct Quality { std::uint32_t crop, model; };
	inline constexpr std::array<Quality, 5> levels{ Quality{100,100}, {80,100}, {60,100}, {60,85}, {60,70} };
	inline Quality Level(std::uint32_t stage) { return levels[std::min(stage, 4u)]; }
	inline std::uint32_t Select(std::uint32_t stage, float ms, float budget, float reserve,
		bool transitioning, bool growthBlocked)
	{
		if (transitioning || stage >= levels.size() || !std::isfinite(ms) || !std::isfinite(budget) ||
			!std::isfinite(reserve) || ms <= 0.0f || budget <= 0.0f || reserve < 0.0f || reserve >= budget) return 0;
		if (ms > budget && stage < 4) return 1;
		if (ms < budget - reserve && stage > 0 && !growthBlocked) return 2;
		return 0;
	}
}
