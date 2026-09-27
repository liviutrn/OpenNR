#pragma once

#include <algorithm>
#include <chrono>
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
			lastUpdateTime_ = {};
			requestedMode_ = 0;
			activeMode_ = 0;
			neuralEnabled_ = true;
			dwellFrames_ = 0;
			overrunFrames_ = 0;
			headroomFrames_ = 0;
			headroomMs_ = 0.0f;
		}

		void Update(std::uint32_t frame, std::uint32_t requestedMode, bool adaptiveEnabled,
			bool allowDownshift, bool allowUpshift, bool overBudget, bool headroom,
			std::uint32_t downshiftFrames, float upshiftDelayMs, std::uint32_t minimumDwellFrames)
		{
			requestedMode = std::min(requestedMode, 2u);
			const auto now = std::chrono::steady_clock::now();
			if (!adaptiveEnabled) {
				initialized_ = false;
				requestedMode_ = requestedMode;
				activeMode_ = requestedMode;
				neuralEnabled_ = true;
				overrunFrames_ = headroomFrames_ = dwellFrames_ = 0;
				headroomMs_ = 0.0f;
				lastFrame_ = frame;
				lastUpdateTime_ = now;
				return;
			}
			if (lastFrame_ == frame)
				return;
			const float elapsedMs = lastUpdateTime_ == std::chrono::steady_clock::time_point{} ? 0.0f :
				std::clamp(std::chrono::duration<float, std::milli>(now - lastUpdateTime_).count(), 0.0f, 50.0f);
			lastFrame_ = frame;
			lastUpdateTime_ = now;

			if (!initialized_ || requestedMode_ != requestedMode) {
				initialized_ = true;
				requestedMode_ = requestedMode;
				activeMode_ = requestedMode;
				neuralEnabled_ = true;
				headroomMs_ = 0.0f;
				overrunFrames_ = headroomFrames_ = dwellFrames_ = 0;
				return;
			}

			activeMode_ = std::min(activeMode_, requestedMode_);
			++dwellFrames_;
			if (allowDownshift && overBudget) {
				++overrunFrames_;
				headroomFrames_ = 0;
				headroomMs_ = 0.0f;
			} else if (allowUpshift && headroom) {
				overrunFrames_ = 0;
				++headroomFrames_;
				headroomMs_ += elapsedMs;
			} else {
				overrunFrames_ = headroomFrames_ = 0;
				headroomMs_ = 0.0f;
			}

			const auto minDwell = std::max(minimumDwellFrames, 1u);
			if (dwellFrames_ < minDwell)
				return;
			if (allowDownshift && overrunFrames_ >= std::max(downshiftFrames, 1u) &&
				(activeMode_ > 0 || neuralEnabled_)) {
				if (activeMode_ > 0)
					--activeMode_;
				else
					neuralEnabled_ = false;
				ResetDwell();
			} else if (allowUpshift && headroomFrames_ > 0 &&
				headroomMs_ >= std::max(upshiftDelayMs, 1.0f) &&
				(!neuralEnabled_ || activeMode_ < requestedMode_)) {
				if (!neuralEnabled_)
					neuralEnabled_ = true;
				else
					++activeMode_;
				ResetDwell();
			}
		}

		[[nodiscard]] std::uint32_t ActiveMode(std::uint32_t fallback) const
		{
			return initialized_ ? activeMode_ : std::min(fallback, 2u);
		}
		[[nodiscard]] bool IsNeuralEnabled() const { return !initialized_ || neuralEnabled_; }
		[[nodiscard]] bool CanDecrease(std::uint32_t fallback) const
		{
			return IsNeuralEnabled() || ActiveMode(fallback) > 0;
		}
		[[nodiscard]] bool CanIncrease(std::uint32_t fallback) const
		{
			return !IsNeuralEnabled() || ActiveMode(fallback) < std::min(fallback, 2u);
		}

	private:
		void ResetDwell()
		{
			dwellFrames_ = overrunFrames_ = headroomFrames_ = 0;
			headroomMs_ = 0.0f;
		}

		bool initialized_ = false;
		std::uint32_t lastFrame_ = UINT32_MAX;
		std::chrono::steady_clock::time_point lastUpdateTime_{};
		std::uint32_t requestedMode_ = 0;
		std::uint32_t activeMode_ = 0;
		bool neuralEnabled_ = true;
		std::uint32_t dwellFrames_ = 0;
		std::uint32_t overrunFrames_ = 0;
		std::uint32_t headroomFrames_ = 0;
		float headroomMs_ = 0.0f;
	};
}
