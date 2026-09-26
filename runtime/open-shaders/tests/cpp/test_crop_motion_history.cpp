#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>
#include <limits>
#include <tuple>
#include "Features/Upscaling/CropMotionHistory.h"
#include "Features/Upscaling/FoveatedRender/CropGeometry.h"

using namespace FoveatedRenderImpl::CropMotion;

TEST_CASE("Crop geometry shares exact pixel rectangles across SR and post-NR", "[gaze][motion][crop]")
{
	const auto plan = FoveatedRenderImpl::CropGeometry::MakeEyePlan(
		0.173f, 0.227f, 0.55f, 0.52f, 1001, 777, 1501, 1165);
	REQUIRE(plan.input.x == 173);
	REQUIRE(plan.input.y == 176);
	REQUIRE(plan.input.width == 550);
	REQUIRE(plan.input.height == 404);
	REQUIRE(plan.output.x == 259);
	REQUIRE(plan.output.y == 264);
	REQUIRE(plan.output.width == 825);
	REQUIRE(plan.output.height == 605);

	const auto scale = FoveatedRenderImpl::CropGeometry::MotionVectorScale(1001, 777, plan.input);
	REQUIRE(scale[0] == Catch::Approx(1001.0f / 550.0f));
	REQUIRE(scale[1] == Catch::Approx(777.0f / 404.0f));
}

TEST_CASE("Padded gaze crop motion scale uses its actual extent", "[gaze][motion][crop]")
{
	const auto crop = FoveatedRenderImpl::CropGeometry::MakePixelRect(0.225f, 0.225f, 0.55f, 0.55f, 1280, 1280);
	const auto scale = FoveatedRenderImpl::CropGeometry::MotionVectorScale(1280, 1280, crop);
	REQUIRE(crop.width == 704);
	REQUIRE(scale[0] == Catch::Approx(1280.0f / 704.0f));
	REQUIRE(scale[0] * crop.width == Catch::Approx(1280.0f));
}

TEST_CASE("Crop geometry clamps invalid normalized regions to safe pixel bounds", "[gaze][crop]")
{
	const auto crop = FoveatedRenderImpl::CropGeometry::MakePixelRect(
		std::numeric_limits<float>::quiet_NaN(), -0.25f, 4.0f, 0.0f, 8, 6);
	REQUIRE(crop.x == 0);
	REQUIRE(crop.y == 0);
	REQUIRE(crop.width == 8);
	REQUIRE(crop.height == 1);
	REQUIRE(crop.x + crop.width <= 8);
	REQUIRE(crop.y + crop.height <= 6);
}

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
