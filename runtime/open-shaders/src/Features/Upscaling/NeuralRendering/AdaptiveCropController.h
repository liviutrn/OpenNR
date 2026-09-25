#pragma once

#include <array>
#include <cstdint>

namespace NeuralRendering
{
	/**
	 * Hysteretic controller for the optional dynamic foveated-crop companion.
	 *
	 * Crop geometry is a resource-boundary change, so this class selects only
	 * coarse coverage tiers and lets the renderer mask the visible handoff.
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
			// Upper adaptive tier, capped at the selected crop's coverage.
			std::uint32_t maximumCoverage = 85;
			std::uint32_t minimumCoverage = 30;
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

		[[nodiscard]] std::uint32_t ActiveCoverage() const;
		[[nodiscard]] std::uint32_t TargetCoverage() const;
		[[nodiscard]] std::uint32_t MaximumCoverage() const;
		[[nodiscard]] std::uint32_t MinimumCoverage() const;
		[[nodiscard]] float HandoffAlpha() const;
		/** @brief Keep crop geometry on the previous tier while the handoff mask moves. */
		[[nodiscard]] std::uint32_t RenderCoverage() const;
		[[nodiscard]] float VisibleCoverage() const;
		[[nodiscard]] bool IsTransitioning() const { return transitionFrameCount_ != 0; }
		[[nodiscard]] bool IsEnabled() const { return enabled_; }
		[[nodiscard]] bool IsRuntimeActive() const { return enabled_ && !geometryBlocked_; }
		[[nodiscard]] bool IsGeometryBlocked() const { return geometryBlocked_; }
		[[nodiscard]] ResetReason LastResetReason() const { return lastResetReason_; }
		[[nodiscard]] std::uint64_t Generation() const { return generation_; }
		static const char* ResetReasonName(ResetReason reason);

		static constexpr const std::array<std::uint32_t, 12>& CoverageBuckets()
		{
			return kCoverageBuckets;
		}

	private:
		// Five-percent tiers extend through the common 30–50% gaze crops.
		static constexpr std::array<std::uint32_t, 12> kCoverageBuckets{
			85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30 };

		static std::uint32_t FindBucketAtOrBelow(std::uint32_t coverage);
		static std::uint32_t FindBucketIndexAtOrBelow(std::uint32_t coverage);
		static Config NormalizeConfig(const Config& config);

		void ResetDecisionState();
		void StartTransition(std::uint32_t targetIndex, std::uint32_t frameCount);

		Config config_{};
		bool enabled_ = false;
		bool geometryBlocked_ = false;
		std::uint32_t lastFrame_ = UINT32_MAX;
		std::uint32_t activeBucket_ = 0;
		std::uint32_t previousCoverage_ = 85;
		std::uint32_t targetBucket_ = 0;
		std::uint32_t maximumBucket_ = 0;
		std::uint32_t minimumBucket_ = 11;
		std::uint32_t transitionFrame_ = 0;
		std::uint32_t transitionFrameCount_ = 0;
		std::uint32_t dwellFrames_ = 0;
		std::uint32_t overrunFrames_ = 0;
		std::uint32_t headroomFrames_ = 0;
		ResetReason lastResetReason_ = ResetReason::None;
		std::uint64_t generation_ = 0;
	};
}
