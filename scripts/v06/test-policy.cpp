#include "GazeAdaptivePolicy.h"
#include "SimpleFramePolicy.h"
#include "SinglePassLadder.h"
#include "../../runtime/open-shaders/src/Features/Upscaling/NeuralRendering/AdaptiveCropController.h"
#include "../../runtime/open-shaders/src/Features/Upscaling/FoveatedRender/CropGeometry.h"
#include "../../runtime/open-shaders/src/Features/Upscaling/CropMotionHistory.h"
#include "../../runtime/open-shaders/src/Features/Upscaling/GazeCropPolicy.h"

#include <cassert>
#include <iostream>
#include <limits>

using namespace FoveatedRenderImpl::GazeCropPolicy;
using namespace NeuralRendering;

int main()
{
	AdaptiveSettings config;
	AdaptiveFilter filter;
	std::array<float, 2> output{ 0.5f, 0.5f };
	filter.Reset(output);
	float filteredEnergy = 0.0f, rawEnergy = 0.0f;
	for (unsigned frame = 0; frame < 300; ++frame) {
		const std::array<float, 2> sample{ 0.5f + (frame % 2 ? 0.001f : -0.001f), 0.5f };
		output = filter.Update(output, sample, 11.1f, 0.5f, 0.5f, config);
		filteredEnergy += std::abs(output[0] - 0.5f);
		rawEnergy += std::abs(sample[0] - 0.5f);
	}
	assert(filteredEnergy < rawEnergy * 0.4f);
	output = filter.Update(output, { 0.9f, 0.1f }, 11.1f, 0.5f, 0.5f, config);
	assert(output[0] == 0.9f && output[1] == 0.1f);
	config.responsiveness = 0.0f;
	config.jumpSpeed = 100.0f;
	config.maxLagPercent = 5.0f;
	filter.Reset({ 0.5f, 0.5f });
	output = filter.Update({ 0.5f, 0.5f }, { 0.6f, 0.5f }, 11.1f, 0.5f, 0.5f, config);
	assert((0.6f - output[0]) / 0.5f <= 0.05001f);
	assert(filter.Update(output, { std::numeric_limits<float>::quiet_NaN(), 0.5f }, 11.1f, 0.5f, 0.5f, config) == output);
	config.smoothingMs = 0.0f;
	assert((filter.Update(output, { 0.55f, 0.5f }, 11.1f, 0.5f, 0.5f, config) == std::array<float, 2>{ 0.55f, 0.5f }));
	for (unsigned fullWidth : { 1201u, 2404u, 3400u }) {
		for (float origin : { 0.0f, 0.123456f, 0.5f, 1.0f }) {
			const auto rect = FoveatedRenderImpl::CropGeometry::MakePixelRect(origin, origin,
				0.4999f, 0.4999f, fullWidth, 2244);
			assert(rect.width > 0 && rect.x + rect.width <= fullWidth);
			assert(rect.height > 0 && rect.y + rect.height <= 2244);
			const auto scale = FoveatedRenderImpl::CropGeometry::MotionVectorScale(fullWidth, 2244, rect);
			assert(std::abs(scale[0] * float(rect.width) - fullWidth) < 0.001f);
		}
	}


	// A large crop move retains correspondence in the overlapping pixels.
	using namespace FoveatedRenderImpl::CropMotion;
	for (float scaleY : { 1.0f, -1.0f, 0.0005f }) {
		const std::array<float, 2> scale{ 2.0f, scaleY };
		const History previous{ { 100, 100, 100, 80 }, scale, 10, true };
		for (int displacement : { -120, -60, -26, 0, 26, 60, 120 }) {
			const Region current{ static_cast<unsigned>(100 + displacement + 20), 100, 100, 80 };
			bool reset = false;
			const auto offset = Offset(previous, current, scale, 11, reset);
			assert(!reset);
			unsigned retained = 0;
			for (unsigned x = 0; x < current.width; ++x) {
				const float previousUV = (float(x) + 0.5f) / float(current.width) + offset[0] * scale[0];
				const double expectedPreviousX = double(current.x) + x - previous.region.x;
				assert(std::abs(previousUV * float(current.width) - 0.5f - expectedPreviousX) < 0.0001);
				if (previousUV >= 0.005f - 0.00001f && previousUV <= 0.995f + 0.00001f)
					++retained;
			}
			const auto shift = std::abs(double(current.x) - previous.region.x);
			assert(retained == (shift < 100 ? 100u - static_cast<unsigned>(shift) : 0u));
		}

		for (unsigned currentY : { 0u, 40u, 74u, 100u, 126u, 160u, 200u }) {
			bool reset = false;
			const auto offset = Offset(previous, { 100, currentY, 100, 80 }, scale, 11, reset);
			assert(!reset);
			unsigned retained = 0;
			for (unsigned y = 0; y < 80; ++y) {
				const float previousY = float(y) + 0.5f + offset[1] * scale[1] * 80.0f;
				if (previousY >= 0.5f - 0.001f && previousY <= 79.5f + 0.001f)
					++retained;
			}
			const auto shift = std::abs(double(currentY) - 100.0);
			assert(retained == (shift < 80 ? 80u - static_cast<unsigned>(shift) : 0u));
		}
		// Scene motion can restore correspondence even with no geometric crop overlap.
		bool compensatedReset = false;
		const auto farOffset = Offset(previous, { 240, 100, 100, 80 }, scale, 11, compensatedReset);
		assert(!compensatedReset);
		const float sceneMotion = -farOffset[0];
		assert(std::abs(0.5f + (sceneMotion + farOffset[0]) * scale[0] - 0.5f) < 0.0001f);

		bool reset = false;
		Offset(previous, { 100, 100, 100, 80 }, scale, 12, reset);
		assert(reset);
		reset = false;
		Offset(previous, { 100, 100, 90, 80 }, scale, 11, reset);
		assert(reset);
		reset = false;
		Offset(previous, { 100, 100, 100, 80 }, { 2.0f, 0.0f }, 11, reset);
		assert(reset);
		reset = true;
		Offset(previous, { 160, 100, 100, 80 }, scale, 11, reset);
		assert(reset);
	}


	const std::array<unsigned, 5> expectedCrops{100,80,60,60,60};
	const std::array<unsigned, 5> expectedModels{100,100,100,85,70};
	for (unsigned stage = 0; stage < 5; ++stage) {
		const auto level = SinglePassLadder::Level(stage);
		assert(level.crop == expectedCrops[stage] && level.model == expectedModels[stage]);
		assert(SinglePassLadder::Select(stage, 21, 20, 1, false, false) == (stage < 4 ? 1u : 0u));
		assert(SinglePassLadder::Select(stage, 18, 20, 1, false, false) == (stage > 0 ? 2u : 0u));
		assert(SinglePassLadder::Select(stage, 19.5f, 20, 1, false, false) == 0);
		assert(SinglePassLadder::Select(stage, 25, 20, 1, true, false) == 0);
		assert(SinglePassLadder::Select(stage, 15, 20, 1, false, true) == 0);
	}
	assert(SinglePassLadder::Level(999).model == 70);
	assert(SinglePassLadder::Select(2, 23, 22, 2, false, false) == 1);
	assert(SinglePassLadder::Select(2, 19.9f, 22, 2, false, false) == 2);
	assert(SinglePassLadder::Select(2, 20, 22, 2, false, false) == 0);
	assert(SinglePassLadder::Select(2, 22, 22, 2, false, false) == 0);
	for (float invalid : { 0.0f, -1.0f, std::numeric_limits<float>::infinity(), std::numeric_limits<float>::quiet_NaN() }) {
		assert(SinglePassLadder::Select(2, invalid, 20, 1, false, false) == 0);
		assert(SinglePassLadder::Select(2, 25, invalid, 1, false, false) == 0);
	}
	assert(SinglePassLadder::Select(999, 25, 20, 1, false, false) == 0);
	assert(SinglePassLadder::Select(2, 25, 20, 20, false, false) == 0);
	assert(SinglePassLadder::Select(2, 25, 20, -1, false, false) == 0);
	assert(SinglePassLadder::Select(2, 25, 20, std::numeric_limits<float>::quiet_NaN(), false, false) == 0);
	SimpleFramePolicy::Config policy;
	SimpleFramePolicy::State state{ .filteredMs = 12.0f, .passes = 0, .ceiling = 2,
		.canGrow = true, .atFloor = true };
	assert(SimpleFramePolicy::Select(policy, state) == 2);
	policy.firstPassPriority = true;
	assert(SimpleFramePolicy::Select(policy, state) == 4);
	state.passes = 1;
	assert(SimpleFramePolicy::Select(policy, state) == 2);
	state.canGrow = false;
	state.atCeiling = true;
	assert(SimpleFramePolicy::Select(policy, state) == 4);
	state.passes = 0;
	policy.costGuard = true;
	assert(SimpleFramePolicy::Select(policy, state) == 0);
	state.filteredMs = 10.0f;
	assert(SimpleFramePolicy::Select(policy, state) == 4);
	state.retryRemaining = 1.0f;
	assert(SimpleFramePolicy::Select(policy, state) == 0);
	state.retryRemaining = 0.0f;
	state.transitioning = true;
	assert(SimpleFramePolicy::Select(policy, state) == 0);
	state.transitioning = false;
	state.filteredMs = 21.0f;
	state.canShrink = true;
	assert(SimpleFramePolicy::Select(policy, state) == 1);
	state.canShrink = false;
	state.passes = 1;
	assert(SimpleFramePolicy::Select(policy, state) == 3);
	assert(SimpleFramePolicy::StepCrop(80, 75, 20, false) == 75);
	assert(SimpleFramePolicy::StepCrop(95, 60, 20, true) == 100);

	for (unsigned step : { 5u, 10u, 15u, 20u }) {
		AdaptiveCropController actuator;
		AdaptiveCropController::Config crop;
		crop.enabled = true;
		crop.minimumCoverage = 65;
		crop.stepCoverage = step;
		crop.downshiftFrames = crop.upshiftFrames = crop.minimumDwellFrames = 1;
		unsigned frame = 0;
		for (; frame < 100; ++frame) {
			actuator.Update(frame, crop, true, 100, true, false, true, false, true, true, false);
			assert(actuator.VisibleCoverage() <= actuator.RenderCoverage());
			assert(actuator.RenderCoverage() >= 65 && actuator.RenderCoverage() <= 100);
		}
		assert(actuator.RenderCoverage() == 65);
		for (; frame < 200; ++frame) {
			actuator.Update(frame, crop, true, 100, true, false, false, false, true, false, true);
			assert(actuator.VisibleCoverage() <= actuator.RenderCoverage());
		}
		assert(actuator.RenderCoverage() == 100);
	}
	// A held transition must keep both geometry and its visible mask stationary.
	AdaptiveCropController held;
	AdaptiveCropController::Config heldConfig;
	heldConfig.enabled = true;
	heldConfig.downshiftFrames = heldConfig.upshiftFrames = heldConfig.minimumDwellFrames = 1;
	held.Update(0, heldConfig, true, 100, true, false, true, false, true, true, false);
	const auto heldRender = held.RenderCoverage();
	const auto heldAlpha = held.HandoffAlpha();
	heldConfig.hold = true;
	for (unsigned frame = 1; frame < 40; ++frame) {
		held.Update(frame, heldConfig, true, 100, true, false, true, false, true, true, false);
		assert(held.RenderCoverage() == heldRender && held.HandoffAlpha() == heldAlpha);
	}
	heldConfig.hold = false;
	for (unsigned frame = 40; frame < 60; ++frame)
		held.Update(frame, heldConfig, true, 100, true, false, false, false, true, false, false);
	assert(held.RenderCoverage() == 80);

	AdaptiveCropController joined;
	unsigned joinedFrame = 0;
	const auto reach = [&](unsigned stage) {
		const auto quality = SinglePassLadder::Level(stage);
		for (unsigned n = 0; n < 30; ++n) {
			const auto current = joined.ActiveCoverage();
			joined.Update(joinedFrame++, heldConfig, true, 100, true, false,
				current > quality.crop, false, true, current > quality.crop, current < quality.crop);
			assert(joined.VisibleCoverage() <= static_cast<float>(joined.RenderCoverage()));
		}
		assert(joined.RenderCoverage() == quality.crop && !joined.IsTransitioning());
		const auto alpha = joined.HandoffAlpha();
		joined.Update(joinedFrame - 1, heldConfig, true, 100, true, false, true, false, true, true, false);
		assert(joined.RenderCoverage() == quality.crop && joined.HandoffAlpha() == alpha);
	};
	for (unsigned stage = 0; stage < 5; ++stage) reach(stage);
	for (unsigned stage = 4; stage > 0; --stage) reach(stage - 1);

	const float continuous = ResolveOrigin(0.25f, 0.5005f, 0.5f, 1000, 0, true, true, 0);
	const float legacy = ResolveOrigin(0.25f, 0.5005f, 0.5f, 1000, 0, true, false, 0);
	assert(continuous > 0.25f && legacy == continuous);
	assert(ResolveOrigin(0.25f, 0.5005f, 0.5f, 1000, 1, true, false, 0) == 0.25f);
	assert(ResolveOrigin(0.25f, 0.5005f, 0.5f, 1000, 0, true, true, 1) == 0.25f);
	assert(ResolveOrigin(0.9f, 1.0f, 0.8f, 1000, 0, true, true, 10) <= 0.2f);
	assert(std::isfinite(ResolveOrigin(std::numeric_limits<float>::quiet_NaN(), 0.5f, 0.5f, 1000, 0, true)));
	std::cout << "v6 gaze, overlap correspondence, priority, bounds and transition tests passed\n";
}
