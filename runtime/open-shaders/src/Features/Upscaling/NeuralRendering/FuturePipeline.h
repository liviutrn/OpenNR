#pragma once

#include <cstdint>

namespace NeuralRendering::Future
{
	/**
	 * Compile-time roadmap contracts for work that is intentionally not part of
	 * the current runtime. These constants make the boundaries reviewable without
	 * adding inert settings or accidentally enabling an incomplete path.
	 */
	struct AsyncOwnershipContract
	{
		static constexpr uint32_t kRevision = 1;
		static constexpr bool kRuntimeEnabled = false;
		static constexpr bool kArchitectureAdopted = false;

		// The useful part to carry forward is the ownership discipline: the
		// producer retains resource ownership and consumers receive immutable
		// views. A future async implementation must add an explicit fence/lease
		// before the render thread can release or reuse a resource.
		static constexpr bool kProducerRetainsResourceOwnership = true;
		static constexpr bool kConsumersReceiveImmutableViews = true;
		static constexpr bool kRequiresExplicitFenceOrLease = true;
		static constexpr bool kAllowsCrossThreadResourceMutation = false;
	};

	struct DepthMatchedResidualFillContract
	{
		static constexpr uint32_t kRevision = 1;
		static constexpr bool kRuntimeEnabled = false;
		static constexpr bool kRequiresExactDepth = true;
		static constexpr bool kRequiresExactMotionVectors = true;
		static constexpr bool kRejectsInvalidDepth = true;
		static constexpr bool kRejectsDisocclusions = true;
		static constexpr bool kAllowsOpticalFlow = false;
		static constexpr bool kAllowsLearnedFallback = false;
		static constexpr bool kInitialRouteFullEyeOnly = true;
	};

	struct PeripheralCompressionContract
	{
		static constexpr uint32_t kRevision = 1;
		static constexpr bool kRuntimeEnabled = false;
		static constexpr bool kSeparateVRPerformanceBranch = true;
		static constexpr bool kUsesNonLinearPeripheralBudget = true;
		static constexpr bool kRunsOnEveryFullModelPass = true;
		static constexpr bool kSharesCurrentFoveatedCrop = false;
		static constexpr bool kSharesTeacherCaptureRoute = false;
	};
}

