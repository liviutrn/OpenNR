#pragma once

#include <algorithm>
#include <cstdint>

namespace NeuralRendering
{
	struct StageSplitPlan
	{
		bool runPreStage = false;
		bool runPostStage = true;
		std::uint32_t postMultiPassMode = 0;
		std::uint32_t postResourcePassCount = 1;
	};

	struct AdaptiveStageReadiness
	{
		bool preStageRequired = false;
		bool postStageRequired = true;
		std::uint32_t postPassCapacity = 1;
	};

	/**
	 * @brief Assigns the configured total NR pass count across pre-SR and post-SR.
	 * Modes are encoded as 0 = 1x, 1 = 2x, 2 = 3x.
	 */
	[[nodiscard]] constexpr StageSplitPlan ResolveStageSplitPlan(bool preStageRequested,
		bool preStageSucceeded, std::uint32_t activeTotalPassMode,
		std::uint32_t requestedTotalPassMode)
	{
		activeTotalPassMode = std::min(activeTotalPassMode, 2u);
		requestedTotalPassMode = std::min(requestedTotalPassMode, 2u);
		if (!preStageRequested || !preStageSucceeded)
			return {
				.runPreStage = false,
				.runPostStage = true,
				.postMultiPassMode = activeTotalPassMode,
				.postResourcePassCount = requestedTotalPassMode + 1,
			};
		if (activeTotalPassMode == 0)
			return { .runPreStage = true, .runPostStage = false };
		return {
			.runPreStage = true,
			.runPostStage = true,
			.postMultiPassMode = activeTotalPassMode - 1,
			.postResourcePassCount = std::max(1u, requestedTotalPassMode),
		};
	}

	[[nodiscard]] constexpr AdaptiveStageReadiness ResolveAdaptiveStageReadiness(
		bool preStageRequested, bool preStageFailed, std::uint32_t activeTotalPassMode,
		std::uint32_t requestedTotalPassMode)
	{
		const auto plan = ResolveStageSplitPlan(preStageRequested, !preStageFailed,
			activeTotalPassMode, requestedTotalPassMode);
		return {
			.preStageRequired = plan.runPreStage,
			.postStageRequired = plan.runPostStage,
			.postPassCapacity = plan.postResourcePassCount,
		};
	}
}
