#include <array>
#include <cmath>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include "../../runtime/open-shaders/src/Features/Upscaling/NeuralRendering/FeatherPlan.h"
#include "../../runtime/open-shaders/src/Features/Upscaling/ShaderDetailMask.h"

struct Region { float x, y, w, h; };
struct Offset { float x = 0, y = 0; };
struct Profile { bool available = false; float coverageScale = 1, centerHorizontalScale = 1; std::array<Offset, 2> centerOffsets{}; };
void Require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }

int main()
{
	using namespace NeuralRendering;
	std::mt19937 generator(20261009);
	std::uniform_real_distribution<float> unit(0, 1);
	unsigned plans = 0, corners = 0;
	for (unsigned width : { 1201u, 1202u, 1700u })
	for (unsigned height : { 1122u, 1586u })
	for (float ratio : { 1.0f, 1.5f, 2.0f, 3.0f })
	for (float coverage : { 0.01f, 0.25f, 0.5f, 0.65f, 0.9f, 1.0f })
	for (float expansion : { 0.0f, 25.0f, 50.0f, 100.0f })
	for (unsigned placement = 0; placement < 100; ++placement) {
		const Region left{ unit(generator) * (1 - coverage), unit(generator) * (1 - coverage), coverage, coverage };
		const Region right{ unit(generator) * (1 - coverage), unit(generator) * (1 - coverage), coverage, coverage };
		const auto outputWidth = static_cast<unsigned>(std::lround(float(width) * ratio));
		const auto outputHeight = static_cast<unsigned>(std::lround(float(height) * ratio));
		const auto plan = FeatherPlan::Make(left, right, true, expansion, width, height, outputWidth, outputHeight);
		Require(plan.sr.eyes[0].input.width == plan.sr.eyes[1].input.width &&
			plan.sr.eyes[0].input.height == plan.sr.eyes[1].input.height, "Asymmetric SR backing extents");
		Profile profile;
		const bool masking = ShaderDetailMask::ProtectRenderRectangles(profile, plan.sr);
		for (unsigned eye = 0; eye < 2; ++eye) {
			const auto& sr = plan.sr.eyes[eye];
			const auto& core = plan.core.eyes[eye];
			Require(FeatherPlan::Contains(sr.input, core.input), "SR input clips chosen core");
			Require(FeatherPlan::Contains(sr.output, core.output), "SR output clips chosen core");
			if (!plan.expanded)
				Require(sr.input.x == core.input.x && sr.input.y == core.input.y && sr.input.width == core.input.width &&
					sr.output.x == core.output.x && sr.output.width == core.output.width, "R7 crop changed while extension inactive");
			for (float pitch : { 1.0f, 100.0f / 85.0f, 100.0f / 70.0f }) {
				const auto mapping = FeatherPlan::Mapping(core, sr, pitch, 10.0f, 2.0f);
				Require(FeatherGeometry::IsValid(mapping), "Nonlinear mapping contract failed");
			}
			if (!masking) continue;
			const auto& input = sr.input;
			for (float x : { float(input.x) + 0.5f, float(input.x + input.width) - 0.5f })
			for (float y : { float(input.y) + 0.5f, float(input.y + input.height) - 0.5f })
			for (float jitter : { -1.0f, 0.0f, 1.0f }) {
				const float px = std::clamp(x + jitter, 0.0f, float(width));
				const float py = std::clamp(y + jitter, 0.0f, float(height));
				const float nx = (px / float(width) - 0.5f - profile.centerOffsets[eye].x) /
					(profile.coverageScale * profile.centerHorizontalScale * 0.5f);
				const float ny = (py / float(height) - 0.5f - profile.centerOffsets[eye].y) / (profile.coverageScale * 0.5f);
				Require(nx * nx * nx * nx + ny * ny * ny * ny <= 1.000001f, "Actual SR/jitter corner loses full detail");
				++corners;
			}
		}
		++plans;
	}
	auto invalid = FeatherGeometry::Mapping{};
	invalid.x.packedExtent = std::numeric_limits<float>::quiet_NaN();
	Require(!FeatherGeometry::IsValid(invalid), "Nonfinite map accepted");
	const auto empty = FeatherPlan::Make(Region{ 0, 0, 0.5f, 0.5f }, Region{ 0, 0, 0.5f, 0.5f }, true, 50.0f, 0, 0, 0, 0);
	Profile emptyProfile;
	Require(!ShaderDetailMask::ProtectRenderRectangles(emptyProfile, empty.sr), "Empty render grid accepted");
	std::cout << plans << " integrated plans; " << corners << " actual SR/jitter corner samples; core containment and inactive R7 parity passed\n";
}
