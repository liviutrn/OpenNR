#pragma once

#include <algorithm>
#include <cstdint>

namespace NeuralRendering
{
	/** Hysteretic pass-count controller used by the shared adaptive quality policy. */
	class AdaptivePassController
	{
	public:
		void Reset()
		{
			initialized_ = false;
			lastFrame_ = UINT32_MAX;
			requestedMode_ = 0;
			activeMode_ = 0;
			dwellFrames_ = 0;
			overrunFrames_ = 0;
			headroomFrames_ = 0;
		}

		void Update(std::uint32_t frame, std::uint32_t requestedMode, bool adaptiveEnabled,
			bool allowDownshift, bool allowUpshift, bool overBudget, bool headroom,
			std::uint32_t downshiftFrames, std::uint32_t upshiftFrames, std::uint32_t minimumDwellFrames)
		{
			requestedMode = std::min(requestedMode, 2u);
			if (!adaptiveEnabled) {
				initialized_ = false;
				requestedMode_ = requestedMode;
				activeMode_ = requestedMode;
				overrunFrames_ = headroomFrames_ = dwellFrames_ = 0;
				lastFrame_ = frame;
				return;
			}
			if (lastFrame_ == frame)
				return;
			lastFrame_ = frame;

			if (!initialized_ || requestedMode_ != requestedMode) {
				initialized_ = true;
				requestedMode_ = requestedMode;
				activeMode_ = requestedMode;
				overrunFrames_ = headroomFrames_ = dwellFrames_ = 0;
				return;
			}

			activeMode_ = std::min(activeMode_, requestedMode_);
			++dwellFrames_;
			if (allowDownshift && overBudget) {
				++overrunFrames_;
				headroomFrames_ = 0;
			} else if (allowUpshift && headroom) {
				overrunFrames_ = 0;
				++headroomFrames_;
			} else {
				overrunFrames_ = headroomFrames_ = 0;
			}

			const auto minDwell = std::max(minimumDwellFrames, 1u);
			if (dwellFrames_ < minDwell)
				return;
			if (allowDownshift && overrunFrames_ >= std::max(downshiftFrames, 1u) && activeMode_ > 0) {
				--activeMode_;
				ResetDwell();
			} else if (allowUpshift && headroomFrames_ >= std::max(upshiftFrames, 1u) && activeMode_ < requestedMode_) {
				++activeMode_;
				ResetDwell();
			}
		}

		[[nodiscard]] std::uint32_t ActiveMode(std::uint32_t fallback) const
		{
			return initialized_ ? activeMode_ : std::min(fallback, 2u);
		}
		[[nodiscard]] bool CanDecrease(std::uint32_t fallback) const { return ActiveMode(fallback) > 0; }
		[[nodiscard]] bool CanIncrease(std::uint32_t fallback) const { return ActiveMode(fallback) < std::min(fallback, 2u); }

	private:
		void ResetDwell()
		{
			dwellFrames_ = overrunFrames_ = headroomFrames_ = 0;
		}

		bool initialized_ = false;
		std::uint32_t lastFrame_ = UINT32_MAX;
		std::uint32_t requestedMode_ = 0;
		std::uint32_t activeMode_ = 0;
		std::uint32_t dwellFrames_ = 0;
		std::uint32_t overrunFrames_ = 0;
		std::uint32_t headroomFrames_ = 0;
	};
}
