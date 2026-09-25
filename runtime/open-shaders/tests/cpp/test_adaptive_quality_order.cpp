#include "Features/Upscaling/NeuralRendering/AdaptiveQualityOrder.h"
#include "Features/Upscaling/NeuralRendering/AdaptivePassController.h"

#include <catch2/catch_test_macros.hpp>

using NeuralRendering::AdaptivePassController;
using NeuralRendering::AdaptiveQualityAxis;
using NeuralRendering::SelectAdaptiveDownshift;
using NeuralRendering::SelectAdaptiveUpshift;

TEST_CASE("adaptive quality order picks the first available cost reduction and reverses restoration", "[adaptive][order]")
{
	REQUIRE(SelectAdaptiveDownshift(0, true, true, true) == AdaptiveQualityAxis::Passes);
	REQUIRE(SelectAdaptiveDownshift(0, false, true, true) == AdaptiveQualityAxis::Crop);
	REQUIRE(SelectAdaptiveDownshift(0, false, false, true) == AdaptiveQualityAxis::Resolution);
	REQUIRE(SelectAdaptiveUpshift(0, true, true, true) == AdaptiveQualityAxis::Resolution);
	REQUIRE(SelectAdaptiveUpshift(0, true, true, false) == AdaptiveQualityAxis::Crop);
	REQUIRE(SelectAdaptiveUpshift(0, true, false, false) == AdaptiveQualityAxis::Passes);
	REQUIRE(SelectAdaptiveDownshift(99, true, true, true) == AdaptiveQualityAxis::Passes);
}

TEST_CASE("adaptive pass count downshifts one mode per pressure step and restores in reverse", "[adaptive][passes]")
{
	AdaptivePassController controller;
	controller.Update(1, 2, true, false, false, false, false, 1, 1, 1);
	REQUIRE(controller.ActiveMode(2) == 2);
	controller.Update(2, 2, true, true, false, true, false, 1, 1, 1);
	REQUIRE(controller.ActiveMode(2) == 1);
	controller.Update(3, 2, true, false, false, true, false, 1, 1, 1);
	REQUIRE(controller.ActiveMode(2) == 1);
	controller.Update(4, 2, true, true, false, true, false, 1, 1, 1);
	REQUIRE(controller.ActiveMode(2) == 0);
	controller.Update(5, 2, true, false, true, false, true, 1, 1, 1);
	REQUIRE(controller.ActiveMode(2) == 1);
	controller.Update(6, 2, true, false, true, false, true, 1, 1, 1);
	REQUIRE(controller.ActiveMode(2) == 2);
}
