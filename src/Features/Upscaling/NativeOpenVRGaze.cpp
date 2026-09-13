#include "NativeOpenVRGaze.h"

#include "../../Globals.h"
#include "../../State.h"
#include "../../Utils/Game.h"

#if defined(ENABLE_SKYRIM_VR)
#	include "RE/B/BSOpenVR.h"
#endif
#include "RE/C/Console.h"

#ifndef NOMINMAX
#	define NOMINMAX
#endif
#include <Windows.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <limits>
#include <mutex>

namespace FoveatedRenderImpl::NativeOpenVRGaze
{
	namespace
	{
		using Clock = std::chrono::steady_clock;
		using TimePoint = Clock::time_point;

		// These are the public OpenVR ABI types represented locally so this
		// experiment does not replace CommonLibSSE-NG's older IVRSystem_019
		// header or call a newer method through the old interface pointer.
		struct RawHmdVector2
		{
			float v[2];
		};

		using GetGenericInterfaceFn = void* (__cdecl*)(const char*, std::int32_t*);
		using IsInterfaceVersionValidFn = bool (__cdecl*)(const char*);
		using GetInitTokenFn = std::uint32_t (__cdecl*)();
		using GetEyeTrackedFoveationCenterFn = bool (__cdecl*)(void*, RawHmdVector2*, RawHmdVector2*);

		constexpr char kInterfaceVersion[] = "IVRSystem_026";
		// GetEyeTrackedFoveationCenter is the 36th virtual method in the
		// OpenVR IVRSystem_026 contract (zero-based vtable slot 35). This
		// value is verified against the Valve OpenVR 2.15.6/current header.
		constexpr std::size_t kEyeTrackedFoveationCenterVtableIndex = 35;
		constexpr float kMaxAcceptedNdc = 1.25f;
		constexpr float kDefaultFrameDeltaMs = 16.67f;
		constexpr float kStaleHoldMs = 50.0f;
		constexpr float kReturnToStaticMs = 150.0f;
		constexpr float kJumpResetRatio = 0.125f;

		struct RuntimeState
		{
			HMODULE module = nullptr;
			void* system = nullptr;
			GetEyeTrackedFoveationCenterFn eyeTrackedFoveationCenter = nullptr;
			std::uint32_t initToken = 0;
			bool initTokenValid = false;
			bool moduleAvailable = false;
			bool interfaceAvailable = false;

			bool sampleStateValid = false;
			bool haveFiltered = false;
			bool wasInvalid = false;
			bool wasDynamic = false;
			std::array<float, 2> filteredLeft{};
			std::array<float, 2> filteredRight{};
			std::array<float, 2> rawLeft{};
			std::array<float, 2> rawRight{};
			TimePoint lastSampleAt{};
			TimePoint lastValidAt{};
			std::uint64_t sampleSequence = 0;

			bool cacheValid = false;
			std::uint32_t cachedFrame = std::numeric_limits<std::uint32_t>::max();
			Config cachedConfig{};
			Util::Subrect::UVRegion cachedBaseLeft{};
			Util::Subrect::UVRegion cachedBaseRight{};
			std::uint32_t cachedEyeWidth = 0;
			std::uint32_t cachedEyeHeight = 0;
			bool cachedAllowDynamic = false;
			ResolvedCrop cachedResult{};

			bool loggedStatus = false;
			Status lastLoggedStatus = Status::Disabled;
		};

		std::mutex stateMutex;
		RuntimeState state;

		bool NearlyEqual(float a_lhs, float a_rhs)
		{
			return std::abs(a_lhs - a_rhs) <= 0.000001f;
		}

		bool SameRegion(const Util::Subrect::UVRegion& a_lhs, const Util::Subrect::UVRegion& a_rhs)
		{
			return NearlyEqual(a_lhs.x, a_rhs.x) && NearlyEqual(a_lhs.y, a_rhs.y) &&
				NearlyEqual(a_lhs.w, a_rhs.w) && NearlyEqual(a_lhs.h, a_rhs.h);
		}

		bool SameConfig(const Config& a_lhs, const Config& a_rhs)
		{
			return a_lhs.enabled == a_rhs.enabled && NearlyEqual(a_lhs.smoothingMs, a_rhs.smoothingMs) &&
				a_lhs.quantizationPixels == a_rhs.quantizationPixels;
		}

		void ClearSampleStateLocked()
		{
			state.sampleStateValid = false;
			state.haveFiltered = false;
			state.wasInvalid = false;
			state.wasDynamic = false;
			state.filteredLeft = {};
			state.filteredRight = {};
			state.rawLeft = {};
			state.rawRight = {};
			state.lastSampleAt = {};
			state.lastValidAt = {};
		}

		void ClearInterfaceLocked()
		{
			state.system = nullptr;
			state.eyeTrackedFoveationCenter = nullptr;
			state.interfaceAvailable = false;
			// A lost/recreated OpenVR system invalidates any gaze sample and its
			// crop-history contract. The next successful query must reacquire and
			// request a renderer history reset instead of resuming stale gaze.
			ClearSampleStateLocked();
		}

		void EnsureInterfaceLocked()
		{
			const auto module = GetModuleHandleW(L"openvr_api.dll");
			if (module != state.module) {
				state.module = module;
				state.initToken = 0;
				state.initTokenValid = false;
				ClearInterfaceLocked();
				ClearSampleStateLocked();
			}
			state.moduleAvailable = module != nullptr;
			if (!module) {
				ClearInterfaceLocked();
				return;
			}

			auto getToken = reinterpret_cast<GetInitTokenFn>(GetProcAddress(module, "VR_GetInitToken"));
			if (getToken) {
				const auto token = getToken();
				if (!state.initTokenValid || token != state.initToken) {
					state.initToken = token;
					state.initTokenValid = true;
					ClearInterfaceLocked();
					ClearSampleStateLocked();
				}
			}

			if (state.interfaceAvailable && state.system && state.eyeTrackedFoveationCenter)
				return;

			auto isValid = reinterpret_cast<IsInterfaceVersionValidFn>(GetProcAddress(module, "VR_IsInterfaceVersionValid"));
			auto getInterface = reinterpret_cast<GetGenericInterfaceFn>(GetProcAddress(module, "VR_GetGenericInterface"));
			if (!isValid || !getInterface || !isValid(kInterfaceVersion)) {
				ClearInterfaceLocked();
				return;
			}

			std::int32_t error = 0;
			void* system = getInterface(kInterfaceVersion, &error);
			if (!system || error != 0) {
				ClearInterfaceLocked();
				return;
			}

			void** vtable = *reinterpret_cast<void***>(system);
			if (!vtable || !vtable[kEyeTrackedFoveationCenterVtableIndex]) {
				ClearInterfaceLocked();
				return;
			}

			state.system = system;
			state.eyeTrackedFoveationCenter = reinterpret_cast<GetEyeTrackedFoveationCenterFn>(vtable[kEyeTrackedFoveationCenterVtableIndex]);
			state.interfaceAvailable = true;
		}

		bool IsFocusedByGameInput()
		{
#if defined(ENABLE_SKYRIM_VR)
			auto* openvr = RE::BSOpenVR::GetSingleton();
			if (!openvr || !openvr->vrSystem)
				return false;
			return openvr->vrSystem->IsInputAvailable();
#else
			// Non-VR target builds never reach the native provider. Keep the
			// fallback true here so the source remains buildable in the merged
			// multi-target configuration.
			return true;
#endif
		}

		bool MapNdcToUV(const RawHmdVector2& a_ndc, std::array<float, 2>& a_out)
		{
			if (!std::isfinite(a_ndc.v[0]) || !std::isfinite(a_ndc.v[1]) ||
				std::abs(a_ndc.v[0]) > kMaxAcceptedNdc || std::abs(a_ndc.v[1]) > kMaxAcceptedNdc)
				return false;

			a_out[0] = std::clamp((a_ndc.v[0] + 1.0f) * 0.5f, 0.0f, 1.0f);
			// OpenVR NDC Y grows upward; texture UV Y grows downward.
			a_out[1] = std::clamp((1.0f - a_ndc.v[1]) * 0.5f, 0.0f, 1.0f);
			return true;
		}

		Util::Subrect::UVRegion SanitizeRegion(Util::Subrect::UVRegion a_region)
		{
			if (!std::isfinite(a_region.x) || !std::isfinite(a_region.y) ||
				!std::isfinite(a_region.w) || !std::isfinite(a_region.h))
				return {};

			a_region.w = std::clamp(a_region.w, 0.01f, 1.0f);
			a_region.h = std::clamp(a_region.h, 0.01f, 1.0f);
			a_region.x = std::clamp(a_region.x, 0.0f, 1.0f - a_region.w);
			a_region.y = std::clamp(a_region.y, 0.0f, 1.0f - a_region.h);
			return a_region;
		}

		std::array<float, 2> RegionCenter(const Util::Subrect::UVRegion& a_region)
		{
			return { a_region.x + a_region.w * 0.5f, a_region.y + a_region.h * 0.5f };
		}

		float ClampSmoothingMs(float a_value)
		{
			return std::clamp(std::isfinite(a_value) ? a_value : 20.0f, 0.0f, 250.0f);
		}

		float ElapsedMs(TimePoint a_start, TimePoint a_end)
		{
			if (a_start == TimePoint{})
				return 0.0f;
			return std::max(0.0f, std::chrono::duration<float, std::milli>(a_end - a_start).count());
		}

		std::array<float, 2> Lerp(const std::array<float, 2>& a_from, const std::array<float, 2>& a_to, float a_t)
		{
			return {
				a_from[0] + (a_to[0] - a_from[0]) * a_t,
				a_from[1] + (a_to[1] - a_from[1]) * a_t,
			};
		}

		Util::Subrect::UVRegion CropFromCenter(
			const Util::Subrect::UVRegion& a_base,
			const std::array<float, 2>& a_center,
			std::uint32_t a_eyeWidth,
			std::uint32_t a_eyeHeight,
			std::uint32_t a_quantizationPixels)
		{
			auto result = a_base;
			result.x = std::clamp(a_center[0] - result.w * 0.5f, 0.0f, 1.0f - result.w);
			result.y = std::clamp(a_center[1] - result.h * 0.5f, 0.0f, 1.0f - result.h);

			if (a_quantizationPixels > 0 && a_eyeWidth > 0 && a_eyeHeight > 0) {
				const float stepX = static_cast<float>(a_quantizationPixels) / static_cast<float>(a_eyeWidth);
				const float stepY = static_cast<float>(a_quantizationPixels) / static_cast<float>(a_eyeHeight);
				result.x = std::clamp(std::round(result.x / stepX) * stepX, 0.0f, 1.0f - result.w);
				result.y = std::clamp(std::round(result.y / stepY) * stepY, 0.0f, 1.0f - result.h);
			}
			return result;
		}

		void FillDiagnosticsBase(Diagnostics& a_diag, const Config& a_config, std::uint32_t a_frame, bool a_allowDynamic)
		{
			a_diag = {};
			a_diag.experimentEnabled = a_config.enabled;
			a_diag.contextAllowed = a_allowDynamic;
			a_diag.frame = a_frame;
			a_diag.sampleSequence = state.sampleSequence;
			a_diag.interfaceVersion = kInterfaceVersion;
		}

		void LogStatusChangeLocked(const Diagnostics& a_diag)
		{
			if (state.loggedStatus && state.lastLoggedStatus == a_diag.status)
				return;
			state.loggedStatus = true;
			state.lastLoggedStatus = a_diag.status;
			logger::debug("[DLSSNR] native OpenVR gaze status={} api={} focus={} valid={} dynamic={} fallback={}",
				StatusName(a_diag.status), a_diag.interfaceAvailable, a_diag.focused,
				a_diag.gazeValid, a_diag.dynamic, a_diag.usingFallback);
		}

		ResolvedCrop ResolveLocked(
			const Config& a_config,
			const Util::Subrect::UVRegion& a_baseLeftUV,
			const Util::Subrect::UVRegion& a_baseRightUV,
			std::uint32_t a_eyeWidth,
			std::uint32_t a_eyeHeight,
			std::uint32_t a_frame,
			bool a_allowDynamic)
		{
			const auto baseLeft = SanitizeRegion(a_baseLeftUV);
			const auto baseRight = SanitizeRegion(a_baseRightUV);
			ResolvedCrop result{ .leftUV = baseLeft, .rightUV = baseRight };
			FillDiagnosticsBase(result.diagnostics, a_config, a_frame, a_allowDynamic);

			const bool inputKeyChanged = !state.sampleStateValid ||
				!SameConfig(a_config, state.cachedConfig) ||
				!NearlyEqual(baseLeft.w, state.cachedBaseLeft.w) ||
				!NearlyEqual(baseLeft.h, state.cachedBaseLeft.h) ||
				!NearlyEqual(baseRight.w, state.cachedBaseRight.w) ||
				!NearlyEqual(baseRight.h, state.cachedBaseRight.h) ||
				a_eyeWidth != state.cachedEyeWidth ||
				a_eyeHeight != state.cachedEyeHeight ||
				state.cachedAllowDynamic != a_allowDynamic;
			if (inputKeyChanged) {
				ClearSampleStateLocked();
				result.historyReset = a_config.enabled && a_allowDynamic;
			}
			state.sampleStateValid = true;
			state.cachedConfig = a_config;
			state.cachedBaseLeft = baseLeft;
			state.cachedBaseRight = baseRight;
			state.cachedEyeWidth = a_eyeWidth;
			state.cachedEyeHeight = a_eyeHeight;
			state.cachedAllowDynamic = a_allowDynamic;

			if (!a_config.enabled) {
				result.diagnostics.status = Status::Disabled;
				LogStatusChangeLocked(result.diagnostics);
				return result;
			}
			if (!a_allowDynamic) {
				result.diagnostics.status = Status::InactiveContext;
				LogStatusChangeLocked(result.diagnostics);
				return result;
			}
			if (a_eyeWidth == 0 || a_eyeHeight == 0) {
				result.diagnostics.status = Status::InvalidDimensions;
				LogStatusChangeLocked(result.diagnostics);
				return result;
			}
			if (!NearlyEqual(baseLeft.w, baseRight.w) || !NearlyEqual(baseLeft.h, baseRight.h)) {
				result.diagnostics.status = Status::StereoSizeMismatch;
				LogStatusChangeLocked(result.diagnostics);
				return result;
			}
			if (baseLeft.IsFullEye() && baseRight.IsFullEye()) {
				result.diagnostics.status = Status::StaticCropRequired;
				LogStatusChangeLocked(result.diagnostics);
				return result;
			}

			EnsureInterfaceLocked();
			result.diagnostics.moduleAvailable = state.moduleAvailable;
			result.diagnostics.interfaceAvailable = state.interfaceAvailable;
			if (!state.moduleAvailable) {
				result.diagnostics.status = Status::OpenVRUnavailable;
				LogStatusChangeLocked(result.diagnostics);
				return result;
			}
			if (!state.interfaceAvailable || !state.system || !state.eyeTrackedFoveationCenter) {
				result.diagnostics.status = Status::InterfaceUnavailable;
				LogStatusChangeLocked(result.diagnostics);
				return result;
			}

			const bool focused = IsFocusedByGameInput();
			result.diagnostics.focused = focused;
			RawHmdVector2 rawLeft{};
			RawHmdVector2 rawRight{};
			const bool nativeQueryValid = state.eyeTrackedFoveationCenter(state.system, &rawLeft, &rawRight);
			result.diagnostics.nativeQueryValid = nativeQueryValid;
			std::array<float, 2> leftUV{};
			std::array<float, 2> rightUV{};
			const bool mapped = nativeQueryValid && MapNdcToUV(rawLeft, leftUV) && MapNdcToUV(rawRight, rightUV);
			const bool valid = mapped && focused;
			const auto now = Clock::now();
			const float dtMs = state.lastSampleAt == TimePoint{} ? kDefaultFrameDeltaMs :
				std::clamp(ElapsedMs(state.lastSampleAt, now), 0.1f, 250.0f);
			state.lastSampleAt = now;

			if (valid) {
				result.diagnostics.gazeValid = true;
				result.diagnostics.rawLeftUV = leftUV;
				result.diagnostics.rawRightUV = rightUV;
				state.rawLeft = leftUV;
				state.rawRight = rightUV;
				++state.sampleSequence;

				const bool reacquired = !state.haveFiltered || state.wasInvalid || inputKeyChanged;
				const auto previousLeft = state.filteredLeft;
				const auto previousRight = state.filteredRight;
				const float jumpLimit = std::max(0.01f, std::min(baseLeft.w, baseLeft.h) * kJumpResetRatio);
				const bool largeJump = state.haveFiltered && !reacquired &&
					(std::max(std::abs(leftUV[0] - previousLeft[0]), std::abs(leftUV[1] - previousLeft[1])) > jumpLimit ||
						std::max(std::abs(rightUV[0] - previousRight[0]), std::abs(rightUV[1] - previousRight[1])) > jumpLimit);
				if (reacquired || largeJump) {
					state.filteredLeft = leftUV;
					state.filteredRight = rightUV;
					result.historyReset = true;
				} else {
					const float smoothingMs = ClampSmoothingMs(a_config.smoothingMs);
					const float alpha = smoothingMs <= 0.0f ? 1.0f : std::clamp(dtMs / (smoothingMs + dtMs), 0.0f, 1.0f);
					state.filteredLeft = Lerp(previousLeft, leftUV, alpha);
					state.filteredRight = Lerp(previousRight, rightUV, alpha);
				}
				state.haveFiltered = true;
				state.wasInvalid = false;
				state.lastValidAt = now;
				state.wasDynamic = true;

				result.leftUV = CropFromCenter(baseLeft, state.filteredLeft, a_eyeWidth, a_eyeHeight, a_config.quantizationPixels);
				result.rightUV = CropFromCenter(baseRight, state.filteredRight, a_eyeWidth, a_eyeHeight, a_config.quantizationPixels);
				result.dynamic = true;
				result.diagnostics.dynamic = true;
				result.diagnostics.usingFallback = false;
				result.diagnostics.filteredLeftUV = state.filteredLeft;
				result.diagnostics.filteredRightUV = state.filteredRight;
				result.diagnostics.sampleAgeMs = 0.0f;
				result.diagnostics.sampleSequence = state.sampleSequence;
				result.diagnostics.status = Status::Active;
				LogStatusChangeLocked(result.diagnostics);
				return result;
			}

			result.diagnostics.sampleSequence = state.sampleSequence;
			result.diagnostics.filteredLeftUV = state.filteredLeft;
			result.diagnostics.filteredRightUV = state.filteredRight;
			if (state.haveFiltered) {
				state.wasInvalid = true;
				const float ageMs = ElapsedMs(state.lastValidAt, now);
				result.diagnostics.sampleAgeMs = ageMs;
				if (ageMs <= kStaleHoldMs) {
					result.leftUV = CropFromCenter(baseLeft, state.filteredLeft, a_eyeWidth, a_eyeHeight, a_config.quantizationPixels);
					result.rightUV = CropFromCenter(baseRight, state.filteredRight, a_eyeWidth, a_eyeHeight, a_config.quantizationPixels);
					result.dynamic = true;
					result.diagnostics.dynamic = true;
					result.diagnostics.holding = true;
					result.diagnostics.usingFallback = false;
					result.diagnostics.status = Status::Holding;
					LogStatusChangeLocked(result.diagnostics);
					return result;
				}
				if (ageMs < kStaleHoldMs + kReturnToStaticMs) {
					const float progress = std::clamp((ageMs - kStaleHoldMs) / kReturnToStaticMs, 0.0f, 1.0f);
					const auto leftCenter = Lerp(state.filteredLeft, RegionCenter(baseLeft), progress);
					const auto rightCenter = Lerp(state.filteredRight, RegionCenter(baseRight), progress);
					result.leftUV = CropFromCenter(baseLeft, leftCenter, a_eyeWidth, a_eyeHeight, a_config.quantizationPixels);
					result.rightUV = CropFromCenter(baseRight, rightCenter, a_eyeWidth, a_eyeHeight, a_config.quantizationPixels);
					result.dynamic = true;
					result.diagnostics.dynamic = true;
					result.diagnostics.usingFallback = false;
					result.diagnostics.status = Status::Returning;
					LogStatusChangeLocked(result.diagnostics);
					return result;
				}
			}

			if (state.wasDynamic) {
				// The next static-frame handoff must not inherit a moving-crop
				// guide/history contract.
				result.historyReset = true;
				state.wasDynamic = false;
			}
			result.diagnostics.status = Status::NoValidGaze;
			result.diagnostics.usingFallback = true;
			LogStatusChangeLocked(result.diagnostics);
			return result;
		}
	}

	const char* StatusName(Status a_status)
	{
		switch (a_status) {
		case Status::Disabled:
			return "Disabled";
		case Status::InactiveContext:
			return "Gameplay-only fallback";
		case Status::StaticCropRequired:
			return "Select a cropped region";
		case Status::InvalidDimensions:
			return "Invalid eye dimensions";
		case Status::StereoSizeMismatch:
			return "Stereo crop sizes differ";
		case Status::OpenVRUnavailable:
			return "OpenVR runtime unavailable";
		case Status::InterfaceUnavailable:
			return "IVRSystem_026 unavailable";
		case Status::NoValidGaze:
			return "No valid gaze; static fallback";
		case Status::Holding:
			return "Holding last gaze";
		case Status::Returning:
			return "Returning to static crop";
		case Status::Active:
			return "Active";
		default:
			return "Unknown";
		}
	}

	bool IsDynamicGazeAllowed()
	{
		if (!globals::game::isVR || !globals::state)
			return false;
		if (globals::state->IsPausedOrMenuOpen(globals::game::ui))
			return false;
		if (globals::state->isLoadingMenuOpen)
			return false;
		if (globals::game::ui && globals::game::ui->IsMenuOpen(RE::Console::MENU_NAME))
			return false;
		return IsFocusedByGameInput();
	}

	ResolvedCrop ResolveForFrame(
		const Config& a_config,
		const Util::Subrect::UVRegion& a_baseLeftUV,
		const Util::Subrect::UVRegion& a_baseRightUV,
		std::uint32_t a_eyeWidth,
		std::uint32_t a_eyeHeight,
		std::uint32_t a_frame,
		bool a_allowDynamic)
	{
		std::lock_guard lock(stateMutex);
		// Params resolves the crop in the DLSS input coordinate space and the
		// NR writeback path resolves it again later in the same game frame. Do
		// not let their output-space dimensions create a second crop/history
		// decision; the first result is the frame's shared contract.
		if (state.cacheValid && state.cachedFrame == a_frame &&
			SameConfig(a_config, state.cachedConfig) && SameRegion(a_baseLeftUV, state.cachedBaseLeft) &&
			SameRegion(a_baseRightUV, state.cachedBaseRight) && state.cachedAllowDynamic == a_allowDynamic)
			return state.cachedResult;

		state.cachedResult = ResolveLocked(a_config, a_baseLeftUV, a_baseRightUV,
			a_eyeWidth, a_eyeHeight, a_frame, a_allowDynamic);
		state.cachedResult.diagnostics.historyReset = state.cachedResult.historyReset;
		state.cachedFrame = a_frame;
		state.cacheValid = true;
		return state.cachedResult;
	}

	Diagnostics GetDiagnostics()
	{
		std::lock_guard lock(stateMutex);
		return state.cacheValid ? state.cachedResult.diagnostics : Diagnostics{};
	}

	void Reset()
	{
		std::lock_guard lock(stateMutex);
		state = RuntimeState{};
	}
}
