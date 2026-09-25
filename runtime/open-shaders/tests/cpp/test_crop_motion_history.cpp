#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>
#include <tuple>
#include "Features/Upscaling/CropMotionHistory.h"

using namespace FoveatedRenderImpl::CropMotion;

TEST_CASE("Temporal crop history crosses an origin shift only with compensated motion", "[gaze][motion]")
{
	REQUIRE(OriginCompatible(100, 80, 100, 80, false));
	REQUIRE_FALSE(OriginCompatible(100, 80, 108, 74, false));
	REQUIRE(OriginCompatible(100, 80, 108, 74, true));
}

TEST_CASE("Moving crop reprojects a stationary sample without resetting", "[gaze][motion]")
{
	const History left{ { 100, 80, 800, 600 }, { 1.6f, 1.5f }, 40, true };
	bool reset = false;
	const auto offset = Offset(left, { 108, 74, 800, 600 }, left.scale, 41, reset);
	REQUIRE_FALSE(reset);
	REQUIRE(offset[0] * 800.0f * 1.6f == Catch::Approx(8.0f));
	REQUIRE(offset[1] * 600.0f * 1.5f == Catch::Approx(-6.0f));
	const History right{ { 900, 80, 800, 600 }, left.scale, 40, true };
	reset = false;
	const auto rightOffset = Offset(right, { 896, 80, 800, 600 }, right.scale, 41, reset);
	REQUIRE_FALSE(reset);
	REQUIRE(rightOffset[0] * 800.0f * 1.6f == Catch::Approx(-4.0f));
}

TEST_CASE("Crop history breaks at a missing frame, resize, scale change or large gaze jump", "[gaze][motion]")
{
	const History previous{ { 100, 80, 800, 600 }, { 1.6f, 1.5f }, 40, true };
	for (const auto [region, scale, frame] : {
		std::tuple{ Region{ 108, 80, 800, 600 }, previous.scale, 42u },
		std::tuple{ Region{ 108, 80, 801, 600 }, previous.scale, 41u },
		std::tuple{ Region{ 108, 80, 800, 600 }, std::array{ 2.0f, 1.5f }, 41u },
		std::tuple{ Region{ 301, 80, 800, 600 }, previous.scale, 41u }
	}) {
		bool reset = false;
		REQUIRE((Offset(previous, region, scale, frame, reset) == std::array<float, 2>{}));
		REQUIRE(reset);
	}
}
