#include "Features/Upscaling/NeuralRendering/AdaptiveCropController.h"

#include <catch2/catch_test_macros.hpp>

#include <array>
#include <cstdint>
#include <string>

namespace
{
	using Controller = NeuralRendering::AdaptiveCropController;

	Controller::Config FastConfig()
	{
		Controller::Config config;
		config.enabled = true;
		config.minimumCoverage = 60;
		config.downshiftFrames = 1;
		config.upshiftFrames = 8;
		config.minimumDwellFrames = 8;
		config.transitionFrames = 2;
		return config;
	}

	void Tick(Controller& controller, std::uint32_t frame, const Controller::Config& config,
		bool overBudget = false, bool headroom = false, bool nrAtMaximum = true,
		bool nrTransitioning = false, bool allowDownshift = true, std::uint32_t configuredCoverage = 100,
		bool eligible = true, bool geometryCompatible = true, bool eyeTracking = false)
	{
		controller.Update(frame, config, eligible, configuredCoverage, geometryCompatible, eyeTracking,
			allowDownshift, nrTransitioning, nrAtMaximum, overBudget, headroom);
	}
}

TEST_CASE("crop boundary fade renders the union without old display history", "[adaptive][crop]")
{
	Controller controller;
	auto config = FastConfig();
	config.transitionFrames = 8;
	for (unsigned frame = 0; frame < 8; ++frame)
		Tick(controller, frame, config, true);
	REQUIRE(controller.ActiveCoverage() == 80);
	REQUIRE(controller.RenderCoverage() == 85);
	REQUIRE(controller.VisibleCoverage() > 80.0f);
	REQUIRE(controller.VisibleCoverage() < 85.0f);
	config.hold = true;
	for (unsigned frame = 8; frame < 100; ++frame)
		Tick(controller, frame, config, true);
	REQUIRE(controller.ActiveCoverage() == 80);
	REQUIRE(controller.RenderCoverage() == 80);
	REQUIRE(controller.VisibleCoverage() == 80.0f);
	for (unsigned frame = 100; frame < 200; ++frame)
		Tick(controller, frame, config, false, true);
	REQUIRE(controller.ActiveCoverage() == 80);
}

TEST_CASE("adaptive crop exposes the six-tier 85-to-60 ladder", "[adaptive][crop]")
{
	const std::array<std::uint32_t, 6> expected{ 85, 80, 75, 70, 65, 60 };
	REQUIRE(Controller::CoverageBuckets() == expected);
}

TEST_CASE("adaptive crop starts at the configured upper bound capped at 85", "[adaptive][crop]")
{
	const auto config = FastConfig();

	Controller fromFull;
	Tick(fromFull, 1, config, false, false, true, false, true, 100);
	REQUIRE(fromFull.IsRuntimeActive());
	REQUIRE(fromFull.ActiveCoverage() == 85);
	REQUIRE(fromFull.MaximumCoverage() == 85);

	Controller fromEighty;
	Tick(fromEighty, 1, config, false, false, true, false, true, 80);
	REQUIRE(fromEighty.IsRuntimeActive());
	REQUIRE(fromEighty.ActiveCoverage() == 80);
	REQUIRE(fromEighty.MaximumCoverage() == 80);

	Controller fromSixty;
	Tick(fromSixty, 1, config, false, false, true, false, true, 60);
	REQUIRE(fromSixty.IsRuntimeActive());
	REQUIRE(fromSixty.ActiveCoverage() == 60);
}

TEST_CASE("adaptive crop fails closed below the 60 percent floor", "[adaptive][crop]")
{
	const auto config = FastConfig();
	Controller controller;
	Tick(controller, 1, config, false, false, true, false, true, 59);
	REQUIRE_FALSE(controller.IsRuntimeActive());
	REQUIRE(controller.LastResetReason() == Controller::ResetReason::InvalidCoverage);
	REQUIRE(std::string(Controller::ResetReasonName(controller.LastResetReason())) == "invalid-coverage");
}

TEST_CASE("adaptive crop pressure advances one tier and waits for the handoff", "[adaptive][crop]")
{
	const auto config = FastConfig();
	Controller controller;
	Tick(controller, 1, config);

	for (std::uint32_t frame = 2; frame <= 8; ++frame)
		Tick(controller, frame, config, true);
	REQUIRE(controller.ActiveCoverage() == 80);
	REQUIRE(controller.TargetCoverage() == 80);
	REQUIRE(controller.IsTransitioning());

	// A short transition must not be replaced by another downshift on the next
	// over-budget frame, even when the minimum dwell is small enough to allow it.
	Tick(controller, 9, config, true);
	REQUIRE(controller.ActiveCoverage() == 80);
	REQUIRE(controller.TargetCoverage() == 80);

	Tick(controller, 10, config, true);
	REQUIRE_FALSE(controller.IsTransitioning());
}

TEST_CASE("adaptive crop restores one tier only after NR reaches a stable 100 percent", "[adaptive][crop]")
{
	const auto config = FastConfig();
	Controller controller;
	Tick(controller, 1, config);
	for (std::uint32_t frame = 2; frame <= 8; ++frame)
		Tick(controller, frame, config, true);
	REQUIRE(controller.ActiveCoverage() == 80);

	// Headroom while NR is still below its maximum cannot expand the crop.
	for (std::uint32_t frame = 9; frame <= 40; ++frame)
		Tick(controller, frame, config, false, true, false);
	REQUIRE(controller.ActiveCoverage() == 80);

	// Stable 100% NR permits one crop tier to restore. It must not jump to 85%.
	for (std::uint32_t frame = 41; frame <= 48; ++frame)
		Tick(controller, frame, config, false, true, true);
	REQUIRE(controller.ActiveCoverage() == 85);
	REQUIRE(controller.TargetCoverage() == 85);
	REQUIRE(controller.IsTransitioning());

	// The controller cannot skip directly to another tier while the first
	// restoration handoff is still in progress.
	Tick(controller, 49, config, false, true, true);
	REQUIRE(controller.ActiveCoverage() == 85);
}

TEST_CASE("adaptive crop preserves a legal tier across a soft configuration change", "[adaptive][crop]")
{
	auto config = FastConfig();
	Controller controller;
	Tick(controller, 1, config);
	for (std::uint32_t frame = 2; frame <= 8; ++frame)
		Tick(controller, frame, config, true);
	REQUIRE(controller.ActiveCoverage() == 80);

	// Changing only timing is a soft edit; the current tier remains 80%.
	config.transitionFrames = 6;
	Tick(controller, 9, config, false, false);
	REQUIRE(controller.ActiveCoverage() == 80);
	REQUIRE(controller.MaximumCoverage() == 85);

	// Raising the configured minimum makes 80% the nearest legal tier, not a
	// reset to the 85% maximum.
	config.minimumCoverage = 80;
	Tick(controller, 10, config, false, false);
	REQUIRE(controller.ActiveCoverage() == 80);
	REQUIRE(controller.MinimumCoverage() == 80);
}

TEST_CASE("eye tracking and incompatible geometry take ownership away cleanly", "[adaptive][crop]")
{
	const auto config = FastConfig();
	Controller controller;
	Tick(controller, 1, config);
	REQUIRE(controller.IsRuntimeActive());

	Tick(controller, 2, config, false, false, true, false, true, 100, true, true, true);
	REQUIRE_FALSE(controller.IsRuntimeActive());
	REQUIRE(controller.LastResetReason() == Controller::ResetReason::EyeTrackingOwnership);

	Tick(controller, 3, config, false, false, true, false, true, 100, true, false, false);
	REQUIRE_FALSE(controller.IsRuntimeActive());
	REQUIRE(controller.LastResetReason() == Controller::ResetReason::GeometryChange);
}
