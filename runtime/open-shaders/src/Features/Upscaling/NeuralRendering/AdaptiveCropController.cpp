#include "AdaptiveCropController.h"

#include <algorithm>

namespace NeuralRendering
{
	const char* AdaptiveCropController::ResetReasonName(ResetReason reason)
	{
		switch (reason) {
		case ResetReason::Disabled:
			return "disabled";
		case ResetReason::EligibilityLoss:
			return "eligibility-loss";
		case ResetReason::EyeTrackingOwnership:
			return "eye-tracking-ownership";
		case ResetReason::GeometryChange:
			return "geometry-change";
		case ResetReason::InvalidCoverage:
			return "invalid-coverage";
		case ResetReason::ConfigurationChange:
			return "configuration-change";
		case ResetReason::ExplicitReset:
			return "explicit-reset";
		case ResetReason::None:
		default:
			return "none";
		}
	}

	std::uint32_t AdaptiveCropController::FindBucketAtOrBelow(std::uint32_t coverage)
	{
		for (const auto bucket : kCoverageBuckets)
			if (bucket <= coverage)
				return bucket;
		return kCoverageBuckets.back();
	}

	std::uint32_t AdaptiveCropController::FindBucketIndexAtOrBelow(std::uint32_t coverage)
	{
		const auto bucket = FindBucketAtOrBelow(coverage);
		for (std::uint32_t index = 0; index < kCoverageBuckets.size(); ++index)
			if (kCoverageBuckets[index] == bucket)
				return index;
		return static_cast<std::uint32_t>(kCoverageBuckets.size() - 1);
	}

	AdaptiveCropController::Config AdaptiveCropController::NormalizeConfig(const Config& config)
	{
		Config normalized = config;
		normalized.maximumCoverage = FindBucketAtOrBelow(std::clamp(normalized.maximumCoverage, 60u, 85u));
		normalized.minimumCoverage = FindBucketAtOrBelow(std::max(normalized.minimumCoverage, 60u));
		if (normalized.maximumCoverage < normalized.minimumCoverage)
			normalized.maximumCoverage = normalized.minimumCoverage;
		normalized.downshiftFrames = std::clamp(normalized.downshiftFrames, 1u, 16u);
		normalized.upshiftFrames = std::clamp(normalized.upshiftFrames, 8u, 240u);
		normalized.minimumDwellFrames = std::clamp(normalized.minimumDwellFrames, 8u, 600u);
		normalized.transitionFrames = std::clamp(normalized.transitionFrames, 2u, 24u);
		return normalized;
	}

	void AdaptiveCropController::ResetDecisionState()
	{
		enabled_ = false;
		activeBucket_ = 0;
		targetBucket_ = 0;
		maximumBucket_ = 0;
		minimumBucket_ = static_cast<std::uint32_t>(kCoverageBuckets.size() - 1);
		transitionFrame_ = 0;
		transitionFrameCount_ = 0;
		dwellFrames_ = 0;
		overrunFrames_ = 0;
		headroomFrames_ = 0;
	}

	void AdaptiveCropController::Reset()
	{
		config_ = {};
		eyeTrackingBlocked_ = false;
		geometryBlocked_ = false;
		lastFrame_ = UINT32_MAX;
		lastResetReason_ = ResetReason::ExplicitReset;
		++generation_;
		ResetDecisionState();
	}

	void AdaptiveCropController::StartTransition(std::uint32_t targetIndex, std::uint32_t frameCount)
	{
		if (targetIndex == activeBucket_)
			return;
		previousCoverage_ = ActiveCoverage();
		activeBucket_ = targetIndex;
		targetBucket_ = targetIndex;
		transitionFrame_ = 0;
		transitionFrameCount_ = std::max(frameCount, 1u);
		dwellFrames_ = 0;
		overrunFrames_ = 0;
		headroomFrames_ = 0;
	}

	void AdaptiveCropController::Update(std::uint32_t frame, const Config& requestedConfig, bool eligible,
		std::uint32_t configuredCoverage, bool geometryCompatible, bool eyeTrackingEnabled,
		bool allowDownshift, bool nrTransitioning, bool nrAtMaximum, bool overBudget, bool headroom)
	{
		if (lastFrame_ == frame)
			return;
		lastFrame_ = frame;

		const Config config = NormalizeConfig(requestedConfig);
		// The static crop preset supplies the stereo geometry and the eligibility
		// floor. It is not the adaptive upper bound: otherwise a user who compares
		// against a 60% preset can never re-arm the 85-to-60 adaptive ladder.
		const std::uint32_t maximumBucket = FindBucketIndexAtOrBelow(config.maximumCoverage);
		const std::uint32_t requestedFloorCoverage = std::min(config.minimumCoverage, config.maximumCoverage);
		const std::uint32_t minimumBucket = std::max(maximumBucket, FindBucketIndexAtOrBelow(requestedFloorCoverage));
		const bool configurationChanged = config.enabled != config_.enabled ||
			config.maximumCoverage != config_.maximumCoverage ||
			config.minimumCoverage != config_.minimumCoverage ||
			config.downshiftFrames != config_.downshiftFrames ||
			config.upshiftFrames != config_.upshiftFrames ||
			config.minimumDwellFrames != config_.minimumDwellFrames ||
			config.transitionFrames != config_.transitionFrames || maximumBucket != maximumBucket_;
		config_ = config;
		maximumBucket_ = maximumBucket;
		minimumBucket_ = minimumBucket;

		const bool wasEnabled = enabled_;
		const bool wasEyeTrackingBlocked = eyeTrackingBlocked_;
		const bool wasGeometryBlocked = geometryBlocked_;
		eyeTrackingBlocked_ = eyeTrackingEnabled;
		geometryBlocked_ = !geometryCompatible || configuredCoverage < kCoverageBuckets.back();
		const bool shouldRun = eligible && config.enabled && !eyeTrackingBlocked_ && !geometryBlocked_;
		if (!shouldRun) {
			ResetReason reason = ResetReason::EligibilityLoss;
			if (!config.enabled)
				reason = ResetReason::Disabled;
			else if (eyeTrackingBlocked_)
				reason = ResetReason::EyeTrackingOwnership;
			else if (configuredCoverage < kCoverageBuckets.back())
				reason = ResetReason::InvalidCoverage;
			else if (!geometryCompatible)
				reason = ResetReason::GeometryChange;
			if (wasEnabled || reason != lastResetReason_ || wasEyeTrackingBlocked != eyeTrackingBlocked_ || wasGeometryBlocked != geometryBlocked_)
				++generation_;
			lastResetReason_ = reason;
			ResetDecisionState();
			return;
		}

		enabled_ = true;
		if (configurationChanged) {
			// Settings edits are soft changes. Retain the current legal tier so a
			// slider/combo edit cannot look like a quality restore to the maximum.
			// Only the first enable, or a tier made illegal by the new bounds, is
			// anchored to the nearest legal tier.
			const bool activeWasLegal = wasEnabled && activeBucket_ >= maximumBucket && activeBucket_ <= minimumBucket;
			if (!activeWasLegal)
				activeBucket_ = std::clamp(activeBucket_, maximumBucket, minimumBucket);
			targetBucket_ = activeBucket_;
			transitionFrame_ = 0;
			transitionFrameCount_ = 0;
			dwellFrames_ = 0;
			overrunFrames_ = 0;
			headroomFrames_ = 0;
			lastResetReason_ = ResetReason::ConfigurationChange;
			++generation_;
		}

		// The adaptive maximum is an explicit setting. The static crop preset is
		// intentionally not used as an implicit upper bound.
		activeBucket_ = std::clamp(activeBucket_, maximumBucket_, minimumBucket_);
		targetBucket_ = std::clamp(targetBucket_, maximumBucket_, minimumBucket_);

		if (transitionFrameCount_ != 0) {
			if (transitionFrame_ + 1 >= transitionFrameCount_) {
				transitionFrame_ = 0;
				transitionFrameCount_ = 0;
			} else {
				++transitionFrame_;
			}
		}

		++dwellFrames_;
		if (nrTransitioning || config.hold) {
			overrunFrames_ = 0;
			headroomFrames_ = 0;
			return;
		}
		if (overBudget) {
			++overrunFrames_;
			headroomFrames_ = 0;
		} else if (headroom) {
			overrunFrames_ = 0;
			if (nrAtMaximum)
				++headroomFrames_;
			else
				headroomFrames_ = 0;
		} else {
			overrunFrames_ = 0;
			headroomFrames_ = 0;
		}

		if (dwellFrames_ >= config.minimumDwellFrames && transitionFrameCount_ == 0 &&
			!nrTransitioning && allowDownshift &&
				overrunFrames_ >= config.downshiftFrames && activeBucket_ < minimumBucket_)
			StartTransition(activeBucket_ + 1, config.transitionFrames);
		else if (dwellFrames_ >= config.minimumDwellFrames && transitionFrameCount_ == 0 &&
			!nrTransitioning && nrAtMaximum &&
				headroomFrames_ >= config.upshiftFrames && activeBucket_ > maximumBucket_)
			StartTransition(activeBucket_ - 1, config.transitionFrames);
	}

	std::uint32_t AdaptiveCropController::ActiveCoverage() const
	{
		return kCoverageBuckets[std::min(activeBucket_, static_cast<std::uint32_t>(kCoverageBuckets.size() - 1))];
	}

	std::uint32_t AdaptiveCropController::TargetCoverage() const
	{
		return kCoverageBuckets[std::min(targetBucket_, static_cast<std::uint32_t>(kCoverageBuckets.size() - 1))];
	}

	std::uint32_t AdaptiveCropController::MaximumCoverage() const
	{
		return kCoverageBuckets[std::min(maximumBucket_, static_cast<std::uint32_t>(kCoverageBuckets.size() - 1))];
	}

	std::uint32_t AdaptiveCropController::MinimumCoverage() const
	{
		return kCoverageBuckets[std::min(minimumBucket_, static_cast<std::uint32_t>(kCoverageBuckets.size() - 1))];
	}

	float AdaptiveCropController::HandoffAlpha() const
	{
		if (transitionFrameCount_ == 0)
			return 1.0f;
		return std::clamp(static_cast<float>(transitionFrame_ + 1) /
			static_cast<float>(transitionFrameCount_), 0.05f, 1.0f);
	}

	std::uint32_t AdaptiveCropController::RenderCoverage() const
	{
		// Keep the source and destination geometry on the tier that was already
		// rendered for the entire handoff.  The visible mask may move gradually,
		// but changing UVs before both eyes have crossed the same boundary can
		// present the two eyes with different crop generations.  The old max()
		// rule was safe for a downshift because the previous tier was larger, but
		// made an upshift switch immediately to the new larger crop and produced
		// the observed transient double vision.
		return IsTransitioning() ? previousCoverage_ : ActiveCoverage();
	}

	float AdaptiveCropController::VisibleCoverage() const
	{
		if (!IsTransitioning())
			return static_cast<float>(ActiveCoverage());
		const float t = HandoffAlpha();
		const float smooth = t * t * (3.0f - 2.0f * t);
		return previousCoverage_ + (static_cast<float>(ActiveCoverage()) - previousCoverage_) * smooth;
	}
}
