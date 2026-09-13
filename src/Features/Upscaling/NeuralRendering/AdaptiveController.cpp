#include "AdaptiveController.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace NeuralRendering
{
	std::uint32_t AdaptiveController::NormalizeRefresh(std::uint32_t refreshHz)
	{
		for (const auto target : kRefreshTargets)
			if (refreshHz == target)
				return target;
		return 80;
	}

	std::uint32_t AdaptiveController::FindNearestBucket(std::uint32_t resolution)
	{
		std::uint32_t nearest = kResolutionBuckets.front();
		std::uint32_t distance = std::numeric_limits<std::uint32_t>::max();
		for (const auto bucket : kResolutionBuckets) {
			const auto candidateDistance = bucket > resolution ? bucket - resolution : resolution - bucket;
			if (candidateDistance < distance) {
				nearest = bucket;
				distance = candidateDistance;
			}
		}
		return nearest;
	}

	std::uint32_t AdaptiveController::FindBucketIndex(std::uint32_t resolution)
	{
		const auto bucket = FindNearestBucket(resolution);
		for (std::uint32_t index = 0; index < kResolutionBuckets.size(); ++index)
			if (kResolutionBuckets[index] == bucket)
				return index;
		return 0;
	}

	AdaptiveController::Config AdaptiveController::NormalizeConfig(const Config& config)
	{
		Config normalized = config;
		normalized.refreshHz = NormalizeRefresh(normalized.refreshHz);
		normalized.minimumResolution = FindNearestBucket(normalized.minimumResolution);
		normalized.downshiftFrames = std::clamp(normalized.downshiftFrames, 1u, 16u);
		normalized.upshiftFrames = std::clamp(normalized.upshiftFrames, 4u, 64u);
		normalized.minimumDwellFrames = std::clamp(normalized.minimumDwellFrames, 4u, 240u);
		normalized.guardTimeMs = std::clamp(normalized.guardTimeMs, 0.0f, 5.0f);
		return normalized;
	}

	void AdaptiveController::ResetDecisionState()
	{
		enabled_ = false;
		activeBucket_ = 0;
		targetBucket_ = 0;
		minimumBucket_ = 5;
		transitionFrame_ = 0;
		transitionFrameCount_ = 0;
		dwellFrames_ = 0;
		overrunFrames_ = 0;
		headroomFrames_ = 0;
		applicationDeadlineMs_ = 25.0f;
		lastFrameTimeMs_ = 0.0f;
		smoothedFrameTimeMs_ = 0.0f;
		lastSampleOverBudget_ = false;
		lastSampleHadHeadroom_ = false;
	}

	void AdaptiveController::Reset()
	{
		config_ = {};
		hasTimestamp_ = false;
		lastFrame_ = UINT32_MAX;
		lastTimestamp_ = {};
		ResetDecisionState();
	}

	void AdaptiveController::StartTransition(std::uint32_t targetBucket, std::uint32_t frameCount)
	{
		if (targetBucket == activeBucket_)
			return;
		activeBucket_ = targetBucket;
		targetBucket_ = targetBucket;
		transitionFrame_ = 0;
		transitionFrameCount_ = std::max(frameCount, 1u);
		dwellFrames_ = 0;
		overrunFrames_ = 0;
		headroomFrames_ = 0;
	}

	void AdaptiveController::Update(std::uint32_t frame, const Config& requestedConfig, bool eligible)
	{
		const auto now = std::chrono::steady_clock::now();
		if (lastFrame_ == frame)
			return;
		lastFrame_ = frame;

		float frameTimeMs = 0.0f;
		if (hasTimestamp_) {
			frameTimeMs = std::chrono::duration<float, std::milli>(now - lastTimestamp_).count();
			if (!std::isfinite(frameTimeMs) || frameTimeMs <= 0.0f)
				frameTimeMs = 0.0f;
			frameTimeMs = std::clamp(frameTimeMs, 0.0f, 250.0f);
		}
		lastTimestamp_ = now;
		hasTimestamp_ = true;

		const Config config = NormalizeConfig(requestedConfig);
		const bool configurationChanged = config.enabled != config_.enabled ||
			config.refreshHz != config_.refreshHz || config.minimumResolution != config_.minimumResolution ||
			config.downshiftFrames != config_.downshiftFrames || config.upshiftFrames != config_.upshiftFrames ||
			config.minimumDwellFrames != config_.minimumDwellFrames ||
			std::abs(config.guardTimeMs - config_.guardTimeMs) > 0.001f;
		config_ = config;

		const bool shouldRun = config.enabled && eligible;
		if (!shouldRun) {
			ResetDecisionState();
			// Do not carry an ineligible/capture/menu interval into the next
			// adaptive sample as if it were a real application frame.
			hasTimestamp_ = false;
			lastFrame_ = UINT32_MAX;
			return;
		}

		enabled_ = true;
		applicationDeadlineMs_ = 2000.0f / static_cast<float>(config.refreshHz);
		minimumBucket_ = FindBucketIndex(config.minimumResolution);
		if (activeBucket_ > minimumBucket_)
			activeBucket_ = minimumBucket_;
		if (targetBucket_ > minimumBucket_)
			targetBucket_ = minimumBucket_;
		if (configurationChanged) {
			transitionFrame_ = 0;
			transitionFrameCount_ = 0;
			dwellFrames_ = 0;
			overrunFrames_ = 0;
			headroomFrames_ = 0;
		}

		if (frameTimeMs > 0.0f) {
			lastFrameTimeMs_ = frameTimeMs;
			smoothedFrameTimeMs_ = smoothedFrameTimeMs_ == 0.0f ? frameTimeMs :
				smoothedFrameTimeMs_ * 0.90f + frameTimeMs * 0.10f;
		}

		if (transitionFrameCount_ != 0) {
			if (transitionFrame_ + 1 >= transitionFrameCount_) {
				transitionFrame_ = 0;
				transitionFrameCount_ = 0;
			} else {
				++transitionFrame_;
			}
		}

		++dwellFrames_;
		if (frameTimeMs == 0.0f) {
			lastSampleOverBudget_ = false;
			lastSampleHadHeadroom_ = false;
			return;
		}

		const float guardedDeadline = std::max(1.0f, applicationDeadlineMs_ - config.guardTimeMs);
		const bool emergencyOverrun = frameTimeMs > applicationDeadlineMs_ * 1.25f;
		const bool overrun = emergencyOverrun || frameTimeMs > guardedDeadline ||
			(smoothedFrameTimeMs_ > guardedDeadline && frameTimeMs > applicationDeadlineMs_ * 0.95f);
		const bool headroom = frameTimeMs < applicationDeadlineMs_ - config.guardTimeMs * 2.0f;
		lastSampleOverBudget_ = overrun;
		lastSampleHadHeadroom_ = headroom;
		if (overrun) {
			++overrunFrames_;
			headroomFrames_ = 0;
		} else if (headroom) {
			overrunFrames_ = 0;
			++headroomFrames_;
		} else {
			overrunFrames_ = 0;
			headroomFrames_ = 0;
		}

		if (dwellFrames_ >= config.minimumDwellFrames &&
			(overrunFrames_ >= 2 || emergencyOverrun) && activeBucket_ < minimumBucket_) {
			StartTransition(activeBucket_ + 1, config.downshiftFrames);
			return;
		}

		if (dwellFrames_ >= config.minimumDwellFrames && headroomFrames_ >= config.upshiftFrames && activeBucket_ > 0) {
			StartTransition(activeBucket_ - 1, config.upshiftFrames);
		}
	}

	std::uint32_t AdaptiveController::ActiveResolution() const
	{
		return kResolutionBuckets[std::min(activeBucket_, static_cast<std::uint32_t>(kResolutionBuckets.size() - 1))];
	}

	std::uint32_t AdaptiveController::TargetResolution() const
	{
		return kResolutionBuckets[std::min(targetBucket_, static_cast<std::uint32_t>(kResolutionBuckets.size() - 1))];
	}

	float AdaptiveController::HandoffAlpha() const
	{
		if (transitionFrameCount_ == 0)
			return 1.0f;
		return std::clamp(static_cast<float>(transitionFrame_ + 1) /
			static_cast<float>(transitionFrameCount_), 0.05f, 1.0f);
	}
}
