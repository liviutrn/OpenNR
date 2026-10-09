#pragma once

#include <array>
#include <cmath>
#include <cstdint>

namespace FoveatedRenderImpl::CropMotion
{
	struct Region
	{
		std::uint32_t x = 0, y = 0, width = 0, height = 0;
	};

	struct History
	{
		Region region{};
		std::array<float, 2> scale{};
		std::uint32_t frame = 0;
		bool valid = false;
	};

	/** Convert current-to-previous crop displacement to stored motion-vector units. */
	inline std::array<float, 2> Offset(const History& previous, const Region& current,
		std::array<float, 2> scale, std::uint32_t frame, bool& reset)
	{
		const double dx = double(current.x) - previous.region.x;
		const double dy = double(current.y) - previous.region.y;
		reset = reset || !previous.valid || std::uint32_t(frame - previous.frame) != 1 ||
			current.width != previous.region.width || current.height != previous.region.height ||
			!current.width || !current.height || scale != previous.scale ||
			!std::isfinite(scale[0]) || !std::isfinite(scale[1]) || !scale[0] || !scale[1];
		if (reset)
			return {};
		return { float(dx / (double(current.width) * scale[0])),
			float(dy / (double(current.height) * scale[1])) };
	}
}
