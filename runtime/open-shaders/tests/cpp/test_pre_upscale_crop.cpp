#include "Features/Upscaling/NeuralRendering/PixelCrop.h"

#include <catch2/catch_test_macros.hpp>

using NeuralRendering::ComputePixelCrop;

TEST_CASE("equal normalized gaze crops keep equal pixel extents", "[neural-rendering][crop]")
{
	const auto left = ComputePixelCrop(0.173f, 0.211f, 0.5f, 0.6f, 1001, 801);
	const auto right = ComputePixelCrop(0.327f, 0.097f, 0.5f, 0.6f, 1001, 801);
	REQUIRE(left.width == right.width);
	REQUIRE(left.height == right.height);
}

TEST_CASE("gaze crops retain their extent while clamping at eye edges", "[neural-rendering][crop]")
{
	const auto crop = ComputePixelCrop(0.9f, 0.8f, 0.25f, 0.3f, 1000, 800);
	REQUIRE(crop.x + crop.width == 1000);
	REQUIRE(crop.y + crop.height == 800);
	REQUIRE(crop.width == 250);
	REQUIRE(crop.height == 240);
}
