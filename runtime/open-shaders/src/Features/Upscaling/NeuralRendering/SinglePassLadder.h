#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <cmath>

namespace NeuralRendering::SinglePassLadder
{
	struct Quality { std::uint32_t crop, model; bool nrEnabled = true; };
	inline constexpr std::array<Quality, 6> levels{ Quality{100,100}, {80,100}, {60,100}, {60,85}, {60,70}, {100,100,false} };
	inline constexpr std::uint32_t minimumActiveStage = 4, suspendedStage = 5;
	struct Config
	{
		float budget = 20.0f, reserve = 1.0f;
		float disableAbove = 24.0f, enableBelow = 14.0f;
		float decreaseHold = 350.0f, increaseHold = 1200.0f;
		float cooldown = 1000.0f, smoothing = 250.0f;
		std::uint32_t cropFloor = 60, cropStep = 20, transitionFrames = 8, forcedStage = 0;
		bool operator==(const Config&) const = default;
	};
	inline std::uint32_t NormalizeCropStep(std::uint32_t step) { return step == 10 || step == 15 ? step : 20; }
	inline Quality Level(std::uint32_t stage, std::uint32_t step = 20) {
		auto quality = levels[std::min(stage, suspendedStage)];
		if (stage > 0 && stage < suspendedStage)
			quality.crop = 100 - NormalizeCropStep(step) * std::min(stage, 2u);
		return quality;
	}
	inline std::uint32_t Select(std::uint32_t stage, float ms, const Config& config,
		bool transitioning, bool growthBlocked)
	{
		if (config.forcedStage != 0 || transitioning || stage >= levels.size() || !std::isfinite(ms) || ms <= 0.0f ||
			!std::isfinite(config.budget) || !std::isfinite(config.reserve) ||
			config.budget <= 0.0f || config.reserve < 0.0f || config.reserve >= config.budget) return 0;
		const bool validBoundary = std::isfinite(config.disableAbove) && std::isfinite(config.enableBelow) &&
			config.enableBelow > 0.0f && config.disableAbove > config.enableBelow;
		// Only the adjacent NR-on/off endpoint stages may cross this boundary.
		if (stage == suspendedStage)
			return validBoundary && ms < config.enableBelow ? 2u : 0u;
		if (stage == minimumActiveStage && validBoundary && ms > config.disableAbove) return 1;
		if (stage < minimumActiveStage && ms > config.budget) return 1;
		if (stage > 0 && !growthBlocked && ms < config.budget - config.reserve) return 2;
		return 0;
	}
}
