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
		bool overBudget = false, bool headroom = false, bool allowUpshift = true,
		bool nrTransitioning = false, bool allowDownshift = true, std::uint32_t configuredCoverage = 100,
		bool eligible = true, bool geometryCompatible = true)
	{
		controller.Update(frame, config, eligible, configuredCoverage, geometryCompatible,
			allowDownshift, allowUpshift, nrTransitioning, overBudget, headroom);
	}
}

TEST_CASE("crop boundary fade keeps the previous geometry without old display history", "[adaptive][crop]")
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

TEST_CASE("adaptive crop holds the previous geometry for both handoff directions", "[adaptive][crop]")
{
	auto config = FastConfig();
	config.transitionFrames = 8;
	Controller controller;
	Tick(controller, 1, config);

	// Force one downshift from 85% to 80%, then let that transition finish.
	for (std::uint32_t frame = 2; frame <= 8; ++frame)
		Tick(controller, frame, config, true);
	REQUIRE(controller.ActiveCoverage() == 80);
	REQUIRE(controller.IsTransitioning());
	REQUIRE(controller.RenderCoverage() == 85);

	config.hold = true;
	for (std::uint32_t frame = 9; frame <= 16; ++frame)
		Tick(controller, frame, config, true);
	REQUIRE_FALSE(controller.IsTransitioning());
	REQUIRE(controller.ActiveCoverage() == 80);
	REQUIRE(controller.RenderCoverage() == 80);

	// Restore one tier. The active tier changes immediately for controller
	// decisions, but the rendered geometry must remain at 80% until the
	// handoff completes, just as it did for the downshift.
	config.hold = false;
	for (std::uint32_t frame = 17; frame <= 24; ++frame)
		Tick(controller, frame, config, false, true);
	REQUIRE(controller.ActiveCoverage() == 85);
	REQUIRE(controller.IsTransitioning());
	REQUIRE(controller.RenderCoverage() == 80);
	REQUIRE(controller.VisibleCoverage() > 80.0f);
	REQUIRE(controller.VisibleCoverage() < 85.0f);
}

TEST_CASE("adaptive crop exposes five percent tiers from 85 to 30", "[adaptive][crop]")
{
	const std::array<std::uint32_t, 12> expected{ 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30 };
	REQUIRE(Controller::CoverageBuckets() == expected);
}

TEST_CASE("adaptive crop starts at the explicit adaptive maximum", "[adaptive][crop]")
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

	auto limited = config;
	limited.maximumCoverage = 75;
	Controller fromExplicitMaximum;
	Tick(fromExplicitMaximum, 1, limited, false, false, true, false, true, 100);
	REQUIRE(fromExplicitMaximum.IsRuntimeActive());
	REQUIRE(fromExplicitMaximum.ActiveCoverage() == 75);
	REQUIRE(fromExplicitMaximum.MaximumCoverage() == 75);
}

TEST_CASE("adaptive crop fails closed below the 30 percent floor", "[adaptive][crop]")
{
	const auto config = FastConfig();
	Controller controller;
	Tick(controller, 1, config, false, false, true, false, true, 29);
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

TEST_CASE("adaptive crop restores one tier only when selected by the coordinator", "[adaptive][crop]")
{
	const auto config = FastConfig();
	Controller controller;
	Tick(controller, 1, config);
	for (std::uint32_t frame = 2; frame <= 8; ++frame)
		Tick(controller, frame, config, true);
	REQUIRE(controller.ActiveCoverage() == 80);

	// Headroom cannot restore crop while another quality axis is selected.
	for (std::uint32_t frame = 9; frame <= 40; ++frame)
		Tick(controller, frame, config, false, true, false);
	REQUIRE(controller.ActiveCoverage() == 80);

	// Once crop becomes the selected restoration axis, it can recover even if
	// resolution remains below its configured maximum.
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

TEST_CASE("eye tracking keeps crop sizing active while incompatible geometry fails closed", "[adaptive][crop]")
{
	const auto config = FastConfig();
	Controller controller;
	Tick(controller, 1, config);
	REQUIRE(controller.IsRuntimeActive());

	Tick(controller, 2, config, false, false, true, false, true, 100, true, true);
	REQUIRE(controller.IsRuntimeActive());

	Tick(controller, 3, config, false, false, true, false, true, 100, true, false);
	REQUIRE_FALSE(controller.IsRuntimeActive());
	REQUIRE(controller.LastResetReason() == Controller::ResetReason::GeometryChange);
}

TEST_CASE("adaptive crop caps the maximum at a smaller gaze crop and can reduce to 30 percent", "[adaptive][crop][gaze]")
{
	auto config = FastConfig();
	config.maximumCoverage = 85;
	config.minimumCoverage = 30;
	config.minimumDwellFrames = 1;
	config.downshiftFrames = 1;
	Controller controller;
	Tick(controller, 1, config, false, false, true, false, true, 50, true, true);
	REQUIRE(controller.IsRuntimeActive());
	REQUIRE(controller.ActiveCoverage() == 50);
	REQUIRE(controller.MaximumCoverage() == 50);
	for (std::uint32_t frame = 2; frame <= 40; ++frame)
		Tick(controller, frame, config, true, false, true, false, true, 50, true, true);
	REQUIRE(controller.ActiveCoverage() == 30);
}
