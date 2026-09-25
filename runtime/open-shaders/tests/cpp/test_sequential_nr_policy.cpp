#include "Features/Upscaling/NeuralRendering/RuntimePolicy.h"
#include <catch2/catch_test_macros.hpp>

using NeuralRendering::ResolveMultiPassMode;

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
