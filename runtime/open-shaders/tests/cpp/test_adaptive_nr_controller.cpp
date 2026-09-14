#include "Features/Upscaling/NeuralRendering/AdaptiveController.h"
#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>
#include <limits>

using NRController = NeuralRendering::AdaptiveController;

TEST_CASE("NR recursive weights follow an elapsed-time smoothstep", "[adaptive][nr]")
{
	NRController controller;
	NRController::Config config;
	config.enabled = true;
	config.minimumDwellFrames = 30;
	config.downshiftFrames = 4;
	for (unsigned frame = 0; frame < 30; ++frame)
		controller.Update(frame, config, true, 32.0f, 25.0f);
	REQUIRE(controller.ActiveResolution() == 95);
	float oldWeight = 1.0f;
	config.allowDownshift = false;
	for (unsigned step = 1; step <= 3; ++step) {
		controller.Update(29 + step, config, true, 25.0f, 30.0f);
		oldWeight *= 1.0f - controller.HandoffAlpha();
		const float t = step * 30.0f / 120.0f;
		REQUIRE(1.0f - oldWeight == Catch::Approx(t * t * (3.0f - 2.0f * t)));
	}
}

TEST_CASE("adaptive NR ignores unavailable paced workload", "[adaptive][nr]")
{
	NRController controller;
	NRController::Config config;
	config.enabled = true;
	config.refreshHz = 72;
	config.minimumDwellFrames = 4;
	for (unsigned frame = 0; frame < 100; ++frame)
		controller.Update(frame, config, true);
	REQUIRE(controller.ActiveResolution() == 100);
	REQUIRE_FALSE(controller.LastSampleOverBudget());
	controller.Update(101, config, true, std::numeric_limits<float>::quiet_NaN());
	REQUIRE_FALSE(controller.LastSampleHadHeadroom());
}

TEST_CASE("adaptive NR supports a custom FPS budget", "[adaptive][nr]")
{
	NRController controller;
	NRController::Config config;
	config.enabled = true;
	config.targetFps = 60;
	controller.Update(0, config, true);
	REQUIRE(controller.ApplicationTargetFps() == Catch::Approx(60.0f));
	REQUIRE(controller.ApplicationDeadlineMs() == Catch::Approx(1000.0f / 60.0f));

	config.targetFps = 15;
	controller.Update(1, config, true);
	REQUIRE(controller.ApplicationTargetFps() == Catch::Approx(15.0f));
	REQUIRE(controller.ApplicationDeadlineMs() == Catch::Approx(1000.0f / 15.0f));
}

TEST_CASE("adaptive NR clamps custom FPS budgets", "[adaptive][nr]")
{
	NRController controller;
	NRController::Config config;
	config.enabled = true;
	config.targetFps = 1;
	controller.Update(0, config, true);
	REQUIRE(controller.ApplicationTargetFps() == Catch::Approx(15.0f));

	config.targetFps = 120;
	controller.Update(1, config, true);
	REQUIRE(controller.ApplicationTargetFps() == Catch::Approx(60.0f));
}

TEST_CASE("adaptive NR recovers one tier from workload headroom", "[adaptive][nr]")
{
	NRController controller;
	NRController::Config config;
	config.enabled = true;
	config.refreshHz = 72;
	config.minimumDwellFrames = 30;
	config.upshiftFrames = 12;
	for (unsigned frame = 0; frame < 31; ++frame)
		controller.Update(frame, config, true, 32.0f, 27.78f);
	REQUIRE(controller.ActiveResolution() == 95);
	config.allowDownshift = false;
	for (unsigned frame = 31; frame < 70; ++frame)
		controller.Update(frame, config, true, 20.0f, 27.78f);
	REQUIRE(controller.ActiveResolution() == 100);
}

TEST_CASE("crop transition blocks NR restoration and legal config edits preserve tier", "[adaptive][nr]")
{
	NRController controller;
	NRController::Config config;
	config.enabled = true;
	config.minimumDwellFrames = 30;
	for (unsigned frame = 0; frame < 31; ++frame)
		controller.Update(frame, config, true, 32.0f, 27.78f);
	REQUIRE(controller.ActiveResolution() == 95);
	config.allowDownshift = false;
	config.allowUpshift = false;
	config.guardTimeMs = 2.0f;
	for (unsigned frame = 31; frame < 100; ++frame)
		controller.Update(frame, config, true, 15.0f, 27.78f);
	REQUIRE(controller.ActiveResolution() == 95);
	controller.Update(101, config, false, 15.0f);
	REQUIRE(controller.ActiveResolution() == 100);
}
