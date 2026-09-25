#include <catch2/catch_test_macros.hpp>

#include "Features/Upscaling/NeuralRendering/TemporalStereoSchedule.h"

TEST_CASE("Stereo temporal anchors alternate eyes every host frame", "[neural-rendering][temporal]")
{
	using NeuralRendering::TemporalStereoSchedule::AnchorEye;
	using NeuralRendering::TemporalStereoSchedule::ReuseEye;

	REQUIRE(AnchorEye(0) == 0);
	REQUIRE(ReuseEye(0) == 1);
	REQUIRE(AnchorEye(1) == 1);
	REQUIRE(ReuseEye(1) == 0);
	REQUIRE(AnchorEye(2) == 0);
	REQUIRE(ReuseEye(2) == 1);
	REQUIRE(AnchorEye(3) == 1);
	REQUIRE(ReuseEye(3) == 0);
}
