#pragma once

#include <algorithm>
#include <cstdint>

namespace NeuralRendering::SimpleFramePolicy
{
	struct Config
	{
		bool singlePassLadder = false;
		float budget = 20.0f;
		float reserve = 1.0f;
		float passIncrease = 14.0f;
		float cropIncrease = 16.0f;
		float cropDecrease = 18.0f;
		float passDecrease = 20.0f;
		bool firstPassPriority = false;
		float firstPassIncrease = 14.0f;
		bool costGuard = false;
		float firstPassCost = 6.0f;
		float safetyMargin = 1.0f;
		float decreaseHold = 350.0f;
		float increaseHold = 1200.0f;
		float firstPassHold = 1200.0f;
		float cooldown = 1000.0f;
		float smoothing = 250.0f;
		float retryDelay = 3000.0f;
		std::uint32_t cropFloor = 60;
		std::uint32_t cropStep = 20;
		std::uint32_t transitionFrames = 8;
		bool operator==(const Config&) const = default;
	};

	struct State
	{
		float filteredMs = 0.0f;
		std::uint32_t passes = 1;
		std::uint32_t ceiling = 1;
		bool canShrink = false;
		bool canGrow = false;
		bool atFloor = false;
		bool atCeiling = false;
		bool transitioning = false;
		float retryRemaining = 0.0f;
	};

	/** Select one action; timing holds and cooldown remain owned by the caller. */
	inline std::uint32_t Select(const Config& config, const State& state)
	{
		if (state.transitioning)
			return 0;
		if (state.canShrink && state.filteredMs > config.cropDecrease)
			return 1;
		if (state.atFloor && state.passes > 0 && state.filteredMs > config.passDecrease)
			return 3;
		if (config.firstPassPriority && state.passes == 0 && state.ceiling > 0) {
			const bool affordable = !config.costGuard ||
				state.filteredMs + config.firstPassCost + config.safetyMargin < config.cropDecrease;
			return state.retryRemaining <= 0.0f && state.filteredMs < config.firstPassIncrease && affordable ? 4u : 0u;
		}
		if (state.canGrow && state.filteredMs < config.cropIncrease)
			return 2;
		if (state.atCeiling && state.passes < state.ceiling && state.filteredMs < config.passIncrease)
			return 4;
		return 0;
	}

	/** Return a legal relative crop target without exceeding the selected crop. */
	inline std::uint32_t StepCrop(std::uint32_t current, std::uint32_t floor,
		std::uint32_t step, bool increase)
	{
		floor = std::clamp(floor, 60u, 100u);
		current = std::clamp(current, floor, 100u);
		step = std::clamp(step, 5u, 20u);
		return increase ? std::min(100u, current + step) : std::max(floor, current - step);
	}
}
