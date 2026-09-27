#pragma once

#include <cstdint>

namespace NeuralRendering
{
	enum class AdaptiveQualityAxis : std::uint8_t
	{
		Passes,
		Crop,
		None,
	};

	/** Adaptive quality is limited to the two controls used by the UI. */
	[[nodiscard]] constexpr AdaptiveQualityAxis SelectAdaptiveDownshift(std::uint32_t order,
		bool passesCanDecrease, bool cropCanDecrease, bool = false)
	{
		if (order == 1) {
			if (cropCanDecrease) return AdaptiveQualityAxis::Crop;
			if (passesCanDecrease) return AdaptiveQualityAxis::Passes;
		} else {
			if (passesCanDecrease) return AdaptiveQualityAxis::Passes;
			if (cropCanDecrease) return AdaptiveQualityAxis::Crop;
		}
		return AdaptiveQualityAxis::None;
	}

	[[nodiscard]] constexpr AdaptiveQualityAxis SelectAdaptiveUpshift(std::uint32_t order,
		bool passesCanIncrease, bool cropCanIncrease, bool = false)
	{
		// Restore in reverse order so the quality control reduced last recovers first.
		if (order == 1) {
			if (passesCanIncrease) return AdaptiveQualityAxis::Passes;
			if (cropCanIncrease) return AdaptiveQualityAxis::Crop;
		} else {
			if (cropCanIncrease) return AdaptiveQualityAxis::Crop;
			if (passesCanIncrease) return AdaptiveQualityAxis::Passes;
		}
		return AdaptiveQualityAxis::None;
	}
}
