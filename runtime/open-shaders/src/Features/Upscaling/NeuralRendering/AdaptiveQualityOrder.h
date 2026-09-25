#pragma once

#include <array>
#include <cstdint>

namespace NeuralRendering
{
	enum class AdaptiveQualityAxis : std::uint8_t
	{
		Passes,
		Crop,
		Resolution,
		None,
	};

	inline constexpr std::array<std::array<AdaptiveQualityAxis, 3>, 6> kAdaptiveQualityOrders{{
		{ AdaptiveQualityAxis::Passes, AdaptiveQualityAxis::Crop, AdaptiveQualityAxis::Resolution },
		{ AdaptiveQualityAxis::Passes, AdaptiveQualityAxis::Resolution, AdaptiveQualityAxis::Crop },
		{ AdaptiveQualityAxis::Crop, AdaptiveQualityAxis::Passes, AdaptiveQualityAxis::Resolution },
		{ AdaptiveQualityAxis::Crop, AdaptiveQualityAxis::Resolution, AdaptiveQualityAxis::Passes },
		{ AdaptiveQualityAxis::Resolution, AdaptiveQualityAxis::Passes, AdaptiveQualityAxis::Crop },
		{ AdaptiveQualityAxis::Resolution, AdaptiveQualityAxis::Crop, AdaptiveQualityAxis::Passes },
	}};

	[[nodiscard]] constexpr std::array<AdaptiveQualityAxis, 3> GetAdaptiveQualityOrder(std::uint32_t index)
	{
		return kAdaptiveQualityOrders[index < kAdaptiveQualityOrders.size() ? index : 0];
	}

	[[nodiscard]] constexpr AdaptiveQualityAxis SelectAdaptiveDownshift(std::uint32_t order,
		bool passesCanDecrease, bool cropCanDecrease, bool resolutionCanDecrease)
	{
		for (const auto axis : GetAdaptiveQualityOrder(order)) {
			if ((axis == AdaptiveQualityAxis::Passes && passesCanDecrease) ||
				(axis == AdaptiveQualityAxis::Crop && cropCanDecrease) ||
				(axis == AdaptiveQualityAxis::Resolution && resolutionCanDecrease))
				return axis;
		}
		return AdaptiveQualityAxis::None;
	}

	[[nodiscard]] constexpr AdaptiveQualityAxis SelectAdaptiveUpshift(std::uint32_t order,
		bool passesCanIncrease, bool cropCanIncrease, bool resolutionCanIncrease)
	{
		const auto priority = GetAdaptiveQualityOrder(order);
		for (auto index = priority.size(); index > 0; --index) {
			const auto axis = priority[index - 1];
			if ((axis == AdaptiveQualityAxis::Passes && passesCanIncrease) ||
				(axis == AdaptiveQualityAxis::Crop && cropCanIncrease) ||
				(axis == AdaptiveQualityAxis::Resolution && resolutionCanIncrease))
				return axis;
		}
		return AdaptiveQualityAxis::None;
	}
}
