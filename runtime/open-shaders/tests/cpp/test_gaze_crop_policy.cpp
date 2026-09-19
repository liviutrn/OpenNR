#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>
#include "Features/Upscaling/GazeCropPolicy.h"

using namespace FoveatedRenderImpl;

TEST_CASE("Gaze pursuit and saccades bypass saved smoothing", "[gaze]")
{
	for (const float smoothing : { 0.0f, 20.0f, 250.0f }) {
		for (const float dt : { 8.33f, 11.11f, 22.22f, 33.33f }) {
			const std::array<float, 2> sample{ 0.53f, 0.49f };
			REQUIRE(GazeCropPolicy::Filter({ 0.5f, 0.5f }, sample, dt, smoothing, 2000, 2000) == sample);
		}
	}
}

TEST_CASE("Gaze fixation noise is bounded and optional", "[gaze]")
{
	const std::array<float, 2> sample{ 0.5005f, 0.4995f };
	const auto filtered = GazeCropPolicy::Filter({ 0.5f, 0.5f }, sample, 11.11f, 20.0f, 2000, 2000);
	REQUIRE(filtered[0] > 0.5f);
	REQUIRE(filtered[0] < sample[0]);
	REQUIRE(filtered[1] < 0.5f);
	REQUIRE(filtered[1] > sample[1]);
	REQUIRE(GazeCropPolicy::Filter({ 0.5f, 0.5f }, sample, 11.11f, 0.0f, 2000, 2000) == sample);
}

TEST_CASE("Gaze guard absorbs jitter without accumulating crop drift", "[gaze]")
{
	float origin = 0.2f;
	for (int frame = 0; frame < 1000; ++frame) {
		const float sample = 0.5f + (frame % 2 ? 0.005f : -0.005f);
		origin = GazeCropPolicy::ResolveOrigin(origin, sample, 0.6f, 2000, 8, true);
		REQUIRE(origin == 0.2f);
	}
}

TEST_CASE("Gaze guard recenters immediately on escape and remains bounded", "[gaze]")
{
	for (const float extent : { 0.1f, 0.3f, 0.6f, 0.9f, 1.0f }) {
		for (const auto quantization : { 0u, 8u, 64u }) {
			for (int index = 0; index <= 100; ++index) {
				const float sample = index / 100.0f;
				const float origin = GazeCropPolicy::ResolveOrigin(0.0f, sample, extent, 1664, quantization, false);
				const float desired = std::clamp(sample - extent * 0.5f, 0.0f, 1.0f - extent);
				REQUIRE(origin >= 0.0f);
				REQUIRE(origin + extent <= 1.000001f);
				REQUIRE(std::abs(origin - desired) <= std::min(0.02f, extent * 0.05f) + 0.000001f);
			}
		}
	}
	REQUIRE(GazeCropPolicy::ResolveOrigin(0.2f, 0.7f, 0.6f, 2000, 0, true) == Catch::Approx(0.4f));
}

TEST_CASE("Moving gaze remains inside the crop during continuous pursuit", "[gaze]")
{
	float origin = 0.2f;
	std::array<float, 2> previous{ 0.5f, 0.5f };
	unsigned moves = 0;
	for (int frame = 0; frame < 400; ++frame) {
		const float raw = 0.5f + 0.35f * std::sin(frame * 0.02f);
		const auto filtered = GazeCropPolicy::Filter(previous, { raw, 0.5f }, 11.11f, 20.0f, 2000, 2000);
		const float next = GazeCropPolicy::ResolveOrigin(origin, filtered[0], 0.6f, 2000, 8, true);
		moves += next != origin ? 1 : 0;
		origin = next;
		previous = filtered;
		REQUIRE(raw >= origin);
		REQUIRE(raw <= origin + 0.6f);
		const float desired = std::clamp(raw - 0.3f, 0.0f, 0.4f);
		REQUIRE(std::abs(desired - origin) < 0.025f);
	}
	REQUIRE(moves > 0);
	REQUIRE(moves < 150);
}
