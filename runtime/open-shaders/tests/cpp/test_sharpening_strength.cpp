#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>
#include <limits>
#include "Features/Upscaling/RCAS/Strength.h"

TEST_CASE("Extended sharpening keeps the RCAS denominator away from zero", "[sharpening]")
{
	float previous = 0.0f;
	for (int step = 0; step <= 500; ++step) {
		const auto strength = Sharpening::Resolve(step / 100.0f);
		REQUIRE(1.0f - 4.0f * 0.1875f * strength[0] >= 0.25f);
		const float effective = strength[0] * strength[1];
		REQUIRE(effective >= previous);
		previous = effective;
	}
	REQUIRE(Sharpening::Resolve(1.0f)[0] == Catch::Approx(1.0f));
	REQUIRE(Sharpening::Resolve(5.0f)[1] == Catch::Approx(5.0f));
}

TEST_CASE("Invalid sharpening settings cannot reach the GPU", "[sharpening]")
{
	REQUIRE(Sharpening::Sanitize(-1.0f) == 0.0f);
	REQUIRE(Sharpening::Sanitize(100.0f) == 5.0f);
	REQUIRE(Sharpening::Sanitize(std::numeric_limits<float>::infinity()) == 0.0f);
	REQUIRE(Sharpening::Sanitize(std::numeric_limits<float>::quiet_NaN()) == 0.0f);
	REQUIRE(Sharpening::Resolve(0.0f)[0] == 0.0f);
}
