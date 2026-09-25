#pragma once

#include <array>
#include <cstdint>

namespace NeuralRendering
{
	/**
	 * Hysteretic controller for the optional dynamic foveated-crop companion.
	 *
	 * Crop geometry is a resource-boundary change, so this class selects only
	 * coarse size scales relative to the selected crop and lets the renderer mask
	 * the visible handoff.
	 * Adaptive crop is coordinated with adaptive NR. A gaze provider may move the
	 * crop center while this controller changes only its extent.
	 */
	class AdaptiveCropController
	{
	public:
		enum class ResetReason : std::uint8_t
		{
			None,
			Disabled,
			EligibilityLoss,
			GeometryChange,
			InvalidCoverage,
			ConfigurationChange,
			ExplicitReset
		};

		struct Config
		{
			bool enabled = false;
			bool hold = false;
			// Sizes are percentages of the selected crop's width and height.
			// 100 preserves the crop exactly; lower tiers scale it around its center.
			std::uint32_t maximumScalePercent = 100;
			std::uint32_t minimumScalePercent = 60;
			std::uint32_t downshiftFrames = 2;
			std::uint32_t upshiftFrames = 24;
			std::uint32_t minimumDwellFrames = 60;
			std::uint32_t transitionFrames = 8;
		};

		void Reset();
		void Update(std::uint32_t frame, const Config& config, bool eligible,
			std::uint32_t configuredCoverage, bool geometryCompatible,
			bool allowDownshift, bool allowUpshift, bool nrTransitioning,
			bool overBudget, bool headroom);

		[[nodiscard]] std::uint32_t ActiveScalePercent() const;
		[[nodiscard]] std::uint32_t TargetScalePercent() const;
		[[nodiscard]] std::uint32_t MaximumScalePercent() const;
		[[nodiscard]] std::uint32_t MinimumScalePercent() const;
		[[nodiscard]] float HandoffAlpha() const;
		/** @brief Keep crop geometry on the previous tier while the handoff mask moves. */
		[[nodiscard]] std::uint32_t RenderScalePercent() const;
		[[nodiscard]] float VisibleScalePercent() const;
		[[nodiscard]] bool IsTransitioning() const { return transitionFrameCount_ != 0; }
		[[nodiscard]] bool IsEnabled() const { return enabled_; }
		[[nodiscard]] bool IsRuntimeActive() const { return enabled_ && !geometryBlocked_; }
		[[nodiscard]] bool IsGeometryBlocked() const { return geometryBlocked_; }
		[[nodiscard]] ResetReason LastResetReason() const { return lastResetReason_; }
		[[nodiscard]] std::uint64_t Generation() const { return generation_; }
		static const char* ResetReasonName(ResetReason reason);

		static constexpr const std::array<std::uint32_t, 15>& ScaleBuckets()
		{
			return kScaleBuckets;
		}

	private:
		static constexpr std::array<std::uint32_t, 15> kScaleBuckets{
			100, 95, 90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30 };

		static std::uint32_t FindBucketAtOrBelow(std::uint32_t scalePercent);
		static std::uint32_t FindBucketIndexAtOrBelow(std::uint32_t scalePercent);
		static Config NormalizeConfig(const Config& config);

		void ResetDecisionState();
		void StartTransition(std::uint32_t targetIndex, std::uint32_t frameCount);

		Config config_{};
		bool enabled_ = false;
		bool geometryBlocked_ = false;
		std::uint32_t lastFrame_ = UINT32_MAX;
		std::uint32_t activeBucket_ = 0;
		std::uint32_t previousScalePercent_ = 100;
		std::uint32_t targetBucket_ = 0;
		std::uint32_t maximumBucket_ = 0;
		std::uint32_t minimumBucket_ = 14;
		std::uint32_t transitionFrame_ = 0;
		std::uint32_t transitionFrameCount_ = 0;
		std::uint32_t dwellFrames_ = 0;
		std::uint32_t overrunFrames_ = 0;
		std::uint32_t headroomFrames_ = 0;
		ResetReason lastResetReason_ = ResetReason::None;
		std::uint64_t generation_ = 0;
	};
}
