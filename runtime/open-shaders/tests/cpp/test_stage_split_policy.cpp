#include "Features/Upscaling/NeuralRendering/StageSplitPolicy.h"

#include <catch2/catch_test_macros.hpp>

using NeuralRendering::ResolveStageSplitPlan;
using NeuralRendering::ResolveAdaptiveStageReadiness;

TEST_CASE("Stage split keeps total NR evaluation count and routes the first pass before SR", "[nr][stage-split]")
{
	const auto twoPass = ResolveStageSplitPlan(true, true, 1, 1);
	REQUIRE(twoPass.runPreStage);
	REQUIRE(twoPass.runPostStage);
	REQUIRE(twoPass.postMultiPassMode == 0);
	REQUIRE(twoPass.postResourcePassCount == 1);

	const auto threePass = ResolveStageSplitPlan(true, true, 2, 2);
	REQUIRE(threePass.runPreStage);
	REQUIRE(threePass.runPostStage);
	REQUIRE(threePass.postMultiPassMode == 1);
	REQUIRE(threePass.postResourcePassCount == 2);

	const auto pressureReduced = ResolveStageSplitPlan(true, true, 0, 2);
	REQUIRE(pressureReduced.runPreStage);
	REQUIRE_FALSE(pressureReduced.runPostStage);
}

TEST_CASE("Unavailable pre-SR stage falls back to the full post-SR cascade", "[nr][stage-split]")
{
	const auto fallback = ResolveStageSplitPlan(true, false, 1, 2);
	REQUIRE_FALSE(fallback.runPreStage);
	REQUIRE(fallback.runPostStage);
	REQUIRE(fallback.postMultiPassMode == 1);
	REQUIRE(fallback.postResourcePassCount == 3);
}

TEST_CASE("Adaptive tier readiness follows the effective stage after pre-SR failure", "[nr][stage-split][adaptive]")
{
	const auto fallback = ResolveAdaptiveStageReadiness(true, true, 1, 2);
	REQUIRE_FALSE(fallback.preStageRequired);
	REQUIRE(fallback.postStageRequired);
	REQUIRE(fallback.postPassCapacity == 3);

	const auto split = ResolveAdaptiveStageReadiness(true, false, 1, 2);
	REQUIRE(split.preStageRequired);
	REQUIRE(split.postStageRequired);
	REQUIRE(split.postPassCapacity == 2);

	const auto preOnly = ResolveAdaptiveStageReadiness(true, false, 0, 2);
	REQUIRE(preOnly.preStageRequired);
	REQUIRE_FALSE(preOnly.postStageRequired);
}
