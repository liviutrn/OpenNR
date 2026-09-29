#include "Features/Upscaling/NeuralRendering/RuntimePolicy.h"
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

using namespace NeuralRendering;

TEST_CASE("Guide-pixel motion converts to display pixels for color-space passes", "[nr][policy]")
{
	// Post-upscale VR: UV motion scaled by the 1468 px guide must land in 2496 px color space.
	const float guideScale = 1468.0f;
	const float colorScale = GuideToColorMotionScale(guideScale, 2496, 1468);
	REQUIRE(colorScale == Catch::Approx(2496.0f));
	// A 0.01 UV step moves 24.96 display pixels, not the 14.68 the old shaders applied.
	REQUIRE(0.01f * colorScale == Catch::Approx(24.96f));
	// Equal extents (flat/pre-upscale) are unchanged; a zero guide extent is passed through.
	REQUIRE(GuideToColorMotionScale(1920.0f, 1920, 1920) == Catch::Approx(1920.0f));
	REQUIRE(GuideToColorMotionScale(3.0f, 100, 0) == Catch::Approx(3.0f));
}

TEST_CASE("NR coverage presets normalize to the supported set", "[nr][policy]")
{
	for (const auto preset : kNeuralCoveragePresets)
		REQUIRE(NormalizeNeuralCoverage(preset) == preset);
	REQUIRE(NormalizeNeuralCoverage(0) == 100);
	REQUIRE(NormalizeNeuralCoverage(83) == 100);
	REQUIRE(NormalizeNeuralCoverage(200) == 100);
}

TEST_CASE("Full coverage is the whole eye", "[nr][policy]")
{
	const auto rect = ComputeNeuralCoverageRect(2496, 2688, 1468, 1580, 100);
	REQUIRE(rect.IsValid());
	REQUIRE(rect.guideX == 0);
	REQUIRE(rect.guideY == 0);
	REQUIRE(rect.guideWidth == 1468);
	REQUIRE(rect.guideHeight == 1580);
	REQUIRE(rect.colorX == 0);
	REQUIRE(rect.colorY == 0);
	REQUIRE(rect.colorWidth == 2496);
	REQUIRE(rect.colorHeight == 2688);
}

TEST_CASE("Centered coverage keeps color and guide rectangles aligned and inside the eye", "[nr][policy]")
{
	constexpr std::uint32_t eyeWidth = 2496, eyeHeight = 2688, guideWidth = 1468, guideHeight = 1580;
	for (const auto coverage : kNeuralCoveragePresets) {
		const auto rect = ComputeNeuralCoverageRect(eyeWidth, eyeHeight, guideWidth, guideHeight, coverage);
		REQUIRE(rect.IsValid());
		// Exactly centered in guide space.
		REQUIRE(rect.guideX * 2 + rect.guideWidth == guideWidth);
		REQUIRE(rect.guideY * 2 + rect.guideHeight == guideHeight);
		REQUIRE(rect.colorX + rect.colorWidth <= eyeWidth);
		REQUIRE(rect.colorY + rect.colorHeight <= eyeHeight);
		// Both edges of the color rect map to the guide rect within half a display pixel.
		const double ratioX = static_cast<double>(eyeWidth) / guideWidth;
		const double ratioY = static_cast<double>(eyeHeight) / guideHeight;
		REQUIRE(std::abs(rect.colorX - rect.guideX * ratioX) <= 0.5);
		REQUIRE(std::abs(rect.colorX + rect.colorWidth - (rect.guideX + rect.guideWidth) * ratioX) <= 0.5);
		REQUIRE(std::abs(rect.colorY - rect.guideY * ratioY) <= 0.5);
		REQUIRE(std::abs(rect.colorY + rect.colorHeight - (rect.guideY + rect.guideHeight) * ratioY) <= 0.5);
		// The linear coverage matches the preset within one guide pixel.
		REQUIRE(std::abs(static_cast<double>(rect.guideWidth) - guideWidth * coverage / 100.0) <= 1.5);
	}
}

TEST_CASE("Coverage 80% keeps about 64% of the NR area", "[nr][policy]")
{
	const auto rect = ComputeNeuralCoverageRect(2496, 2688, 1468, 1580, 80);
	const double area = static_cast<double>(rect.colorWidth) * rect.colorHeight / (2496.0 * 2688.0);
	REQUIRE(area == Catch::Approx(0.64).margin(0.01));
}

TEST_CASE("Degenerate coverage inputs are rejected", "[nr][policy]")
{
	REQUIRE_FALSE(ComputeNeuralCoverageRect(0, 2688, 1468, 1580, 80).IsValid());
	REQUIRE_FALSE(ComputeNeuralCoverageRect(2496, 2688, 1, 1580, 80).IsValid());
}

TEST_CASE("Eye stagger alternates the native eye every frame", "[nr][policy]")
{
	REQUIRE(StaggeredNativeEye(0) == 0);
	REQUIRE(StaggeredNativeEye(1) == 1);
	REQUIRE(StaggeredNativeEye(2) == 0);
	REQUIRE(StaggeredNativeEye(0xFFFFFFFFull) == 1);
}

TEST_CASE("This build keeps NR at full resolution", "[nr][policy]")
{
	STATIC_REQUIRE(kFullResolutionNeuralRenderingOnly);
}
