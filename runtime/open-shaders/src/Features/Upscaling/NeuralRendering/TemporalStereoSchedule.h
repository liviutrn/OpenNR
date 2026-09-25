#pragma once

#include <cstdint>

namespace NeuralRendering::TemporalStereoSchedule
{
	// The first frame seeds both eyes. Thereafter exactly one eye is anchored
	// per host frame, alternating left/right; the other eye uses residual reuse.
	[[nodiscard]] constexpr std::uint32_t AnchorEye(std::uint64_t frameIndex)
	{
		return static_cast<std::uint32_t>(frameIndex & 1u);
	}

	[[nodiscard]] constexpr std::uint32_t ReuseEye(std::uint64_t frameIndex)
	{
		return AnchorEye(frameIndex) ^ 1u;
	}
}
