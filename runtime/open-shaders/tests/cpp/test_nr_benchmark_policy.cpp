#include "Features/Upscaling/NeuralRendering/BenchmarkPolicy.h"
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

using namespace NeuralRendering::Benchmark;

TEST_CASE("Benchmark schedule brackets every variant with baselines", "[nr][benchmark]")
{
	const auto schedule = BuildSchedule(3, 1);
	REQUIRE(schedule == std::vector<int>{ kBaselineBlock, 0, kBaselineBlock, 1, kBaselineBlock, 2, kBaselineBlock });
}

TEST_CASE("Benchmark repeats alternate variant order to balance drift", "[nr][benchmark]")
{
	const auto schedule = BuildSchedule(2, 2);
	REQUIRE(schedule == std::vector<int>{ kBaselineBlock, 0, kBaselineBlock, 1, kBaselineBlock, 1, kBaselineBlock, 0, kBaselineBlock });
	REQUIRE(BuildSchedule(0, 3).empty());
	REQUIRE(BuildSchedule(4, 0).empty());
}

TEST_CASE("Benchmark percentiles ignore non-finite samples", "[nr][benchmark]")
{
	REQUIRE(Median({ 5.0f, 1.0f, 3.0f }) == Catch::Approx(3.0f));
	REQUIRE(Median({ 4.0f, 1.0f, 3.0f, 2.0f }) == Catch::Approx(2.0f));
	REQUIRE(Percentile({ 1.0f, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f, 7.0f, 8.0f, 9.0f, 10.0f }, 90.0f) == Catch::Approx(9.0f));
	REQUIRE(Median({ std::numeric_limits<float>::quiet_NaN(), 2.0f }) == Catch::Approx(2.0f));
	REQUIRE(std::isnan(Median({})));
}

TEST_CASE("Benchmark deltas reference the mean of both bracketing baselines", "[nr][benchmark]")
{
	// B=40, V0=36, B=42, V1=45, B=42 -> V0 delta = 36 - 41 = -5 (drift 2), V1 = 45 - 42 = +3.
	const std::vector<BlockStats> blocks{
		{ kBaselineBlock, 40.0f, 41.0f, 90 },
		{ 0, 36.0f, 37.0f, 90 },
		{ kBaselineBlock, 42.0f, 43.0f, 90 },
		{ 1, 45.0f, 46.0f, 90 },
		{ kBaselineBlock, 42.0f, 43.0f, 90 },
	};
	const auto deltas = ComputeDeltas(blocks, 2);
	REQUIRE(deltas.size() == 2);
	REQUIRE(deltas[0].deltaMs == Catch::Approx(-5.0f));
	REQUIRE(deltas[0].baselineMedianMs == Catch::Approx(41.0f));
	REQUIRE(deltas[0].uncertaintyMs == Catch::Approx(2.0f));
	REQUIRE(deltas[1].deltaMs == Catch::Approx(3.0f));
	REQUIRE(deltas[1].uncertaintyMs == Catch::Approx(0.0f));
	REQUIRE(deltas[1].repeats == 1);
}

TEST_CASE("Benchmark deltas average repeats and report their disagreement", "[nr][benchmark]")
{
	const std::vector<BlockStats> blocks{
		{ kBaselineBlock, 40.0f, 0.0f, 90 },
		{ 0, 38.0f, 0.0f, 90 },
		{ kBaselineBlock, 40.0f, 0.0f, 90 },
		{ 0, 37.0f, 0.0f, 90 },
		{ kBaselineBlock, 40.0f, 0.0f, 90 },
	};
	const auto deltas = ComputeDeltas(blocks, 1);
	REQUIRE(deltas[0].repeats == 2);
	REQUIRE(deltas[0].deltaMs == Catch::Approx(-2.5f));
	REQUIRE(deltas[0].uncertaintyMs == Catch::Approx(1.0f));
}

TEST_CASE("Benchmark skips empty blocks and uses the nearest valid baseline", "[nr][benchmark]")
{
	const std::vector<BlockStats> blocks{
		{ kBaselineBlock, 40.0f, 0.0f, 90 },
		{ 0, 30.0f, 0.0f, 90 },
		{ kBaselineBlock, 0.0f, 0.0f, 0 },  // interrupted baseline
		{ 1, 0.0f, 0.0f, 0 },               // interrupted variant
		{ kBaselineBlock, 44.0f, 0.0f, 90 },
	};
	const auto deltas = ComputeDeltas(blocks, 2);
	REQUIRE(deltas[0].deltaMs == Catch::Approx(30.0f - 42.0f));
	REQUIRE(deltas[1].repeats == 0);
	REQUIRE(std::isnan(deltas[1].deltaMs));
}
