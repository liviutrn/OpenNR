#include "Features/Upscaling/NeuralRendering/SecondPassCrop.h"
#include "Features/Upscaling/NeuralRendering/SecondPassCropFallback.h"

#include <catch2/catch_test_macros.hpp>

using NeuralRendering::MakeSecondPassCropPlan;
using NeuralRendering::SecondPassCropConfig;
using NeuralRendering::SecondPassCropFallbackLatch;

TEST_CASE("second-pass crop retains the configured centered fraction", "[nr][crop]")
{
	const auto off = MakeSecondPassCropPlan(1000, 800, 1000, 800, 0);
	REQUIRE_FALSE(off.enabled);
	REQUIRE(off.color.x == 0);
	REQUIRE(off.color.y == 0);
	REQUIRE(off.color.width == 1000);
	REQUIRE(off.color.height == 800);

	const auto twenty = MakeSecondPassCropPlan(1000, 800, 1000, 800, 20);
	REQUIRE(twenty.enabled);
	REQUIRE(twenty.color.x == 100);
	REQUIRE(twenty.color.y == 80);
	REQUIRE(twenty.color.width == 800);
	REQUIRE(twenty.color.height == 640);
	REQUIRE(twenty.output.x == twenty.color.x);
	REQUIRE(twenty.guides.x == twenty.color.x);

	const auto quarter = MakeSecondPassCropPlan(1000, 800, 1000, 800, 25);
	REQUIRE(quarter.color.x == 125);
	REQUIRE(quarter.color.y == 100);
	REQUIRE(quarter.color.width == 750);
	REQUIRE(quarter.color.height == 600);

	const auto asymmetric = MakeSecondPassCropPlan(1000, 800, 1000, 800, 40, 20);
	REQUIRE(asymmetric.color.x == 200);
	REQUIRE(asymmetric.color.y == 80);
	REQUIRE(asymmetric.color.width == 600);
	REQUIRE(asymmetric.color.height == 640);

	const auto half = MakeSecondPassCropPlan(1000, 800, 500, 400, 50);
	REQUIRE(half.color.x == 250);
	REQUIRE(half.color.y == 200);
	REQUIRE(half.color.width == 500);
	REQUIRE(half.color.height == 400);
	REQUIRE(half.guides.x == 125);
	REQUIRE(half.guides.y == 100);
	REQUIRE(half.guides.width == 250);
	REQUIRE(half.guides.height == 200);
}

TEST_CASE("second-pass crop clamps small extents and preserves mapped guide bounds", "[nr][crop]")
{
	const auto plan = MakeSecondPassCropPlan(7, 5, 3, 2, 50);
	REQUIRE(plan.color.width >= 1);
	REQUIRE(plan.color.height >= 1);
	REQUIRE(plan.color.x + plan.color.width <= 7);
	REQUIRE(plan.color.y + plan.color.height <= 5);
	REQUIRE(plan.guides.width >= 1);
	REQUIRE(plan.guides.height >= 1);
	REQUIRE(plan.guides.x + plan.guides.width <= 3);
	REQUIRE(plan.guides.y + plan.guides.height <= 2);
}

TEST_CASE("rejected second-pass crop is latched per configuration", "[nr][crop][fallback]")
{
	SecondPassCropFallbackLatch latch;
	const SecondPassCropConfig config{ 1000, 800, 500, 400, 20, 10 };
	REQUIRE_FALSE(latch.IsRejected(config));
	REQUIRE(latch.MarkRejected());
	REQUIRE(latch.IsRejected(config));
	REQUIRE_FALSE(latch.MarkRejected());

	const SecondPassCropConfig changedReduction{ 1000, 800, 500, 400, 25, 10 };
	REQUIRE_FALSE(latch.IsRejected(changedReduction));
	REQUIRE(latch.MarkRejected());
	const SecondPassCropConfig changedResources{ 1002, 800, 501, 400, 25, 10 };
	REQUIRE_FALSE(latch.IsRejected(changedResources));

	latch.MarkRejected();
	latch.Reset();
	REQUIRE_FALSE(latch.IsRejected(changedResources));
}
