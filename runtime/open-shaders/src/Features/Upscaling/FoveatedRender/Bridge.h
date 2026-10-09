#pragma once

#include <array>
#include "CropGeometry.h"

// FoveatedRenderImpl::Bridge — single point of contact between the FoveatedRender
// subsystem and the rest of Community Shaders (Upscaling, Streamline).
//
// Consumers read FoveatedRender settings directly from
// globals::features::upscaling.foveatedRender; Bridge exposes only the
// cross-cutting concerns that require route-aware logic (active check, boot
// sequence, mvec scale, execute-frame flag).

#include <cstdint>

namespace FoveatedRenderImpl::Bridge
{
	// True when VR + FoveatedRender enabled-at-boot + DLSS or FSR selected.
	bool IsRouteActive();

	// Boot-time latches. Run once during BSShaderRenderTargets::Create.
	// Latches enable + qualityMode so settings cannot drift mid-frame.
	void BootSequence();

	// Compute motion-vector scale for the given eye (0=left, 1=right). Asymmetric
	// presets (e.g. Nasal Convergence) can size the two eyes' subrects differently.
	// Returns {1,1} when route is inactive or that eye's subrect is full-eye.
	void ComputeMvecScale(uint32_t eyeIndex, float& outX, float& outY);
	/** Publish exact integer crop scales shared by SR and NR for one frame. */
	void SetMvecScaleForFrame(uint32_t frame, const std::array<std::array<float, 2>, 2>& scales);
	inline std::array<std::array<float, 2>, 2> mvecScales{};
	inline uint32_t mvecScaleFrame = UINT32_MAX;

	// Set/cleared by ExecuteFoveatedRoute to indicate that the foveated subrect
	// execute path is actually running this frame. SetConstants checks this so
	// mvecScale correction is not applied to the standard full-frame DLSS path
	// (e.g. menus, frames where foveated is skipped).
	inline bool foveatedEvaluating = false;
	inline bool gazeHistoryReset = false;
	inline CropGeometry::FramePlan currentCrop{}, previousCrop{};
	inline uint32_t cropFrame = UINT32_MAX, previousCropFrame = UINT32_MAX;
	inline bool cropHistoryValid = false;

	/** Publish the SR crop without advancing its successfully reconstructed history. */
	inline void SetCropForFrame(uint32_t frame, const CropGeometry::FramePlan& plan)
	{
		currentCrop = plan;
		cropFrame = frame;
	}

	/** Advance crop camera history only after both SR eyes have succeeded. */
	inline void CommitCropFrame(bool succeeded)
	{
		cropHistoryValid = succeeded;
		if (succeeded) {
			previousCrop = currentCrop;
			previousCropFrame = cropFrame;
		}
	}
}
