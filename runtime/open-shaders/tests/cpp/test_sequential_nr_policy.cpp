#include "Features/Upscaling/NeuralRendering/RuntimePolicy.h"
#include "Features/Upscaling/NeuralRendering/Runtime.h"
#include <catch2/catch_test_macros.hpp>

using NeuralRendering::ResolveMultiPassMode;
using NeuralRendering::Tuning;

TEST_CASE("Sequential NR remains enabled for fixed-size static and eye-tracked crops", "[nr][foveated]")
{
	REQUIRE(ResolveMultiPassMode(1, true, false) == 1);
	REQUIRE(ResolveMultiPassMode(2, true, false) == 2);
	REQUIRE(ResolveMultiPassMode(1, false, false) == 1);
}

TEST_CASE("Cropped sequential NR composes with adaptive resolution", "[nr][foveated][adaptive]")
{
	REQUIRE(ResolveMultiPassMode(1, true, true) == 1);
	REQUIRE(ResolveMultiPassMode(2, true, true) == 2);
	REQUIRE(ResolveMultiPassMode(2, false, true) == 2);
	REQUIRE(ResolveMultiPassMode(0, true, false) == 0);
	REQUIRE(ResolveMultiPassMode(3, false, false) == 2);
}

TEST_CASE("sequential NR applies independent tuning to each pass", "[nr][passes]")
{
	Tuning tuning;
	tuning.passParameters[0].style = 0;
	tuning.passParameters[0].intensity = 0.8f;
	tuning.passParameters[1].style = 1;
	tuning.passParameters[1].intensity = 1.35f;
	tuning.passParameters[2].style = 3;
	tuning.passParameters[2].intensity = 1.75f;

	const auto first = tuning.ForPass(0);
	const auto second = tuning.ForPass(1);
	const auto third = tuning.ForPass(2);
	REQUIRE(first.style == 0);
	REQUIRE(first.intensity == 0.8f);
	REQUIRE(second.style == 1);
	REQUIRE(second.intensity == 1.35f);
	REQUIRE(third.style == 3);
	REQUIRE(third.intensity == 1.75f);
	REQUIRE(tuning.ForPass(3).intensity == tuning.intensity);

	tuning.passParameterOffset = 1;
	REQUIRE(tuning.ForPass(0).style == 1);
	REQUIRE(tuning.ForPass(0).intensity == 1.35f);
	REQUIRE(tuning.ForPass(1).style == 3);
	REQUIRE(tuning.ForPass(1).intensity == 1.75f);
}
