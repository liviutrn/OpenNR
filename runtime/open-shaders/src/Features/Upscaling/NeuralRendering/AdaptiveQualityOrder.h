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

	// The pass controller exposes whether recovery is bringing NR back from
	// completely off (P1) or considering an additional sequential pass (P2/P3).
	// Crop-first recovery uses this distinction to guarantee:
	// P1 -> crop restore -> extra pass.
	enum class AdaptivePassRecoveryStage : std::uint8_t
	{
		None,
		RestorePrimary,
		RestoreExtra,
	};

	inline thread_local AdaptivePassRecoveryStage adaptivePassRecoveryStage = AdaptivePassRecoveryStage::None;

	inline void SetAdaptivePassRecoveryStage(AdaptivePassRecoveryStage stage)
	{
		adaptivePassRecoveryStage = stage;
	}

	[[nodiscard]] inline AdaptivePassRecoveryStage GetAdaptivePassRecoveryStage()
	{
		return adaptivePassRecoveryStage;
	}

	/** Adaptive quality is intentionally limited to pass count and crop size. */
	[[nodiscard]] constexpr AdaptiveQualityAxis SelectAdaptiveDownshift(std::uint32_t order,
		bool passesCanDecrease, bool cropCanDecrease, bool = false)
	{
		if (order == 1) {
			// Crop-first pressure: exhaust the cheaper crop steps before dropping P2/P3,
			// then eventually P1/NR-off if pressure persists.
			if (cropCanDecrease) return AdaptiveQualityAxis::Crop;
			if (passesCanDecrease) return AdaptiveQualityAxis::Passes;
		} else {
			if (passesCanDecrease) return AdaptiveQualityAxis::Passes;
			if (cropCanDecrease) return AdaptiveQualityAxis::Crop;
		}
		return AdaptiveQualityAxis::None;
	}

	[[nodiscard]] inline AdaptiveQualityAxis SelectAdaptiveUpshift(std::uint32_t order,
		bool passesCanIncrease, bool cropCanIncrease, bool = false)
	{
		if (order == 1) {
			// Deliberately asymmetric recovery for the crop-first policy:
			// 1) if NR was fully off, restore P1 first;
			// 2) restore crop extent while there is cheap headroom;
			// 3) only then consider P2/P3, whose activation is cost-gated separately.
			if (passesCanIncrease && GetAdaptivePassRecoveryStage() == AdaptivePassRecoveryStage::RestorePrimary)
				return AdaptiveQualityAxis::Passes;
			if (cropCanIncrease)
				return AdaptiveQualityAxis::Crop;
			if (passesCanIncrease)
				return AdaptiveQualityAxis::Passes;
		} else {
			// Pass-first pressure keeps the previous reverse recovery behavior.
			if (cropCanIncrease) return AdaptiveQualityAxis::Crop;
			if (passesCanIncrease) return AdaptiveQualityAxis::Passes;
		}
		return AdaptiveQualityAxis::None;
	}
}
