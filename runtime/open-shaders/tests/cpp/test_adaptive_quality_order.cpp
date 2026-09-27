#include "Features/Upscaling/NeuralRendering/AdaptiveQualityOrder.h"
#include "Features/Upscaling/NeuralRendering/AdaptivePassController.h"

#include <catch2/catch_test_macros.hpp>

using NeuralRendering::AdaptivePassController;
using NeuralRendering::AdaptivePassRecoveryStage;
using NeuralRendering::AdaptiveQualityAxis;
using NeuralRendering::GetAdaptivePassRecoveryStage;
using NeuralRendering::SelectAdaptiveDownshift;
using NeuralRendering::SelectAdaptiveUpshift;
using NeuralRendering::SetAdaptivePassRecoveryStage;

TEST_CASE("adaptive pressure uses only passes and crop", "[adaptive][order]")
{
	REQUIRE(SelectAdaptiveDownshift(0, true, true, false) == AdaptiveQualityAxis::Passes);
	REQUIRE(SelectAdaptiveDownshift(0, false, true, false) == AdaptiveQualityAxis::Crop);
	REQUIRE(SelectAdaptiveDownshift(0, false, false, false) == AdaptiveQualityAxis::None);

	REQUIRE(SelectAdaptiveDownshift(1, true, true, false) == AdaptiveQualityAxis::Crop);
	REQUIRE(SelectAdaptiveDownshift(1, true, false, false) == AdaptiveQualityAxis::Passes);
	REQUIRE(SelectAdaptiveDownshift(1, false, false, false) == AdaptiveQualityAxis::None);

	// Unknown/legacy order values conservatively keep pass-first behavior.
	REQUIRE(SelectAdaptiveDownshift(99, true, true, false) == AdaptiveQualityAxis::Passes);
}

TEST_CASE("crop-first recovery is P1 then crop then extra pass", "[adaptive][order][recovery]")
{
	SetAdaptivePassRecoveryStage(AdaptivePassRecoveryStage::RestorePrimary);
	REQUIRE(SelectAdaptiveUpshift(1, true, true, false) == AdaptiveQualityAxis::Passes);

	SetAdaptivePassRecoveryStage(AdaptivePassRecoveryStage::RestoreExtra);
	REQUIRE(SelectAdaptiveUpshift(1, true, true, false) == AdaptiveQualityAxis::Crop);
	REQUIRE(SelectAdaptiveUpshift(1, true, false, false) == AdaptiveQualityAxis::Passes);

	SetAdaptivePassRecoveryStage(AdaptivePassRecoveryStage::None);
	REQUIRE(SelectAdaptiveUpshift(1, false, true, false) == AdaptiveQualityAxis::Crop);
	REQUIRE(SelectAdaptiveUpshift(1, false, false, false) == AdaptiveQualityAxis::None);
}

TEST_CASE("adaptive pass controller identifies primary and extra-pass recovery", "[adaptive][passes][recovery]")
{
	AdaptivePassController controller;
	controller.Update(1, 1, true, false, false, false, false, 1, 1.0f, 1);
	REQUIRE(controller.ActiveMode(1) == 1); // P1 + P2
	REQUIRE(controller.IsNeuralEnabled());

	controller.Update(2, 1, true, true, false, true, false, 1, 1.0f, 1);
	REQUIRE(controller.ActiveMode(1) == 0); // P1 only
	REQUIRE(controller.IsNeuralEnabled());
	REQUIRE(controller.CanIncrease(1));
	REQUIRE(GetAdaptivePassRecoveryStage() == AdaptivePassRecoveryStage::RestoreExtra);

	controller.Update(3, 1, true, true, false, true, false, 1, 1.0f, 1);
	REQUIRE(controller.ActiveMode(1) == 0);
	REQUIRE_FALSE(controller.IsNeuralEnabled()); // NR fully off
	REQUIRE(controller.CanIncrease(1));
	REQUIRE(GetAdaptivePassRecoveryStage() == AdaptivePassRecoveryStage::RestorePrimary);
}

TEST_CASE("adaptive pass count removes exactly one quality step per pressure pulse", "[adaptive][passes]")
{
	AdaptivePassController controller;
	controller.Update(1, 2, true, false, false, false, false, 1, 1.0f, 1);
	REQUIRE(controller.ActiveMode(2) == 2); // P1 + P2 + P3

	controller.Update(2, 2, true, true, false, true, false, 1, 1.0f, 1);
	REQUIRE(controller.ActiveMode(2) == 1); // drop P3
	REQUIRE(controller.IsNeuralEnabled());

	controller.Update(3, 2, true, true, false, true, false, 1, 1.0f, 1);
	REQUIRE(controller.ActiveMode(2) == 0); // drop P2
	REQUIRE(controller.IsNeuralEnabled());

	controller.Update(4, 2, true, true, false, true, false, 1, 1.0f, 1);
	REQUIRE(controller.ActiveMode(2) == 0);
	REQUIRE_FALSE(controller.IsNeuralEnabled()); // finally drop P1 / NR off
}
