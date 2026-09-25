#pragma once

#include "Utils/Subrect.h"

#include <array>
#include <cstdint>
#include <string>

// Isolated, native OpenVR eye-gaze provider for the OpenNR experiment.
//
// The provider owns only the gaze sample, freshness policy, and crop-center
// mapping. It does not initialize or shut down OpenVR, hook the compositor, or
// replace the existing Feature 18/Streamline ownership path. Unsupported or
// stale gaze always resolves to the caller's persisted static crop.
namespace FoveatedRenderImpl::NativeOpenVRGaze
{
	enum class Status : std::uint8_t
	{
		Disabled,
		InactiveContext,
		StaticCropRequired,
		InvalidDimensions,
		StereoSizeMismatch,
		OpenVRUnavailable,
		InterfaceUnavailable,
		NoValidGaze,
		Holding,
		Returning,
		Active,
	};

	struct Config
	{
		bool enabled = false;
		float smoothingMs = 0.0f;
		std::uint32_t policy = 0;
		float catchupMs = 8.0f;
		std::uint32_t deadbandPixels = 1;
		std::uint32_t holdMs = 50;
		float predictionMs = 0.0f;
		std::uint32_t quantizationPixels = 8;
		std::uint32_t cropPaddingPixels = 0;
	};

	struct Diagnostics
	{
		Status status = Status::Disabled;
		bool experimentEnabled = false;
		bool contextAllowed = false;
		bool moduleAvailable = false;
		bool interfaceAvailable = false;
		bool focused = false;
		bool nativeQueryValid = false;
		bool gazeValid = false;
		bool dynamic = false;
		bool holding = false;
		bool usingFallback = true;
		bool historyReset = false;
		std::uint32_t frame = 0;
		std::uint64_t sampleSequence = 0;
		float sampleAgeMs = 0.0f;
		float providerQueryMs = 0.0f;
		bool cropChanged = false;
		std::uint64_t cropChangeCount = 0;
		std::uint64_t historyResetCount = 0;
		std::array<float, 4> leftCropUV{};
		std::array<float, 4> rightCropUV{};
		std::array<float, 2> rawLeftUV{};
		std::array<float, 2> rawRightUV{};
		std::array<float, 2> filteredLeftUV{};
		std::array<float, 2> filteredRightUV{};
		std::string interfaceVersion = "IVRSystem_026";
	};

	struct ResolvedCrop
	{
		Util::Subrect::UVRegion leftUV{};
		Util::Subrect::UVRegion rightUV{};
		bool dynamic = false;
		bool historyReset = false;
		Diagnostics diagnostics{};
	};

	const char* StatusName(Status status);

	// The caller uses this shared safety predicate so the foveated DLSS route and
	// the before-UI NR route resolve the same crop. Menus, loading, the console,
	// flat rendering, and a missing State/UI contract fail closed to static UVs.
	bool IsDynamicGazeAllowed();

	// Resolve once per game frame. Repeated calls from the foveated DLSS route and
	// the NR compositor hook return the same cached sample and reset decision.
	ResolvedCrop ResolveForFrame(
		const Config& config,
		const Util::Subrect::UVRegion& baseLeftUV,
		const Util::Subrect::UVRegion& baseRightUV,
		std::uint32_t eyeWidth,
		std::uint32_t eyeHeight,
		std::uint32_t frame,
		bool allowDynamic);

	Diagnostics GetDiagnostics();
	void Reset();
}
