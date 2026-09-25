#pragma once

#include "CropMotionHistory.h"

struct ID3D11Resource;

namespace FoveatedRenderImpl::CropMotion
{
	/** Prepare private compensated vectors; slots 0/1 are SR, 2/3 post-NR, 4/5 pre-NR. */
	ID3D11Resource* Prepare(std::uint32_t slot, ID3D11Resource* source,
		const Region& region, std::uint32_t guideWidth, std::uint32_t guideHeight,
		std::array<float, 2> scale, std::uint32_t frame, bool& reset);
	/** Advance history only after the corresponding reconstruction succeeds. */
	void Commit(std::uint32_t slot, bool succeeded);
	/** Invalidate a stage without reallocating GPU resources. */
	void Invalidate(std::uint32_t firstSlot = 0, std::uint32_t count = 4);
	/** Release resources on device/shader teardown. */
	void Clear();
}
