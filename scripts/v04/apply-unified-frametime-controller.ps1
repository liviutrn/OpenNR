$ErrorActionPreference = 'Stop'

function Read-Normalized([string]$Path) {
    return [IO.File]::ReadAllText((Resolve-Path $Path)).Replace("`r`n", "`n")
}
function Write-Normalized([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText((Resolve-Path $Path), $Text, [Text.UTF8Encoding]::new($false))
}
function Replace-ExactOnce([string]$Path, [string]$Old, [string]$New) {
    $text = Read-Normalized $Path
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected one exact block in $Path, found $count" }
    Write-Normalized $Path ($text.Replace($Old, $New))
}
function Replace-RegexOnce([string]$Path, [string]$Pattern, [string]$Replacement) {
    $text = Read-Normalized $Path
    $rx = [regex]::new($Pattern, [Text.RegularExpressions.RegexOptions]::Singleline)
    $matches = $rx.Matches($text)
    if ($matches.Count -ne 1) { throw "Expected one regex block in $Path for '$Pattern', found $($matches.Count)" }
    Write-Normalized $Path ($rx.Replace($text, $Replacement, 1))
}

$header = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.h'
$foveated = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$integration = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Integration.cpp'

Write-Host 'v04 unified controller: add single-policy state'
$stateOld = @'
	float adaptiveFastWorkloadMs = 0.0f;
	float adaptiveSlowWorkloadMs = 0.0f;
'@
$stateNew = @'
	float adaptiveFastWorkloadMs = 0.0f;
	float adaptiveSlowWorkloadMs = 0.0f;
	// v04: one controller owns pass count and relative crop target. The old
	// model-resolution controller remains present for ABI/source compatibility
	// but is deliberately not a decision maker while adaptive v04 is active.
	std::uint32_t adaptiveCropTargetCoverage = 100;
	float adaptiveOverBudgetMs = 0.0f;
	float adaptiveHeadroomMs = 0.0f;
	float adaptiveCooldownMs = 0.0f;
	float adaptiveLastGpuMs = 0.0f;
	float adaptiveLastCpuMs = 0.0f;
	std::uint32_t adaptiveOutlierStreak = 0;
	bool adaptiveGpuLimited = true;
'@
Replace-ExactOnce $header $stateOld $stateNew

Write-Host 'v04 unified controller: reset one coherent state machine'
$resetPattern = '(?s)void FoveatedRender::ResetAdaptiveState\(\)\n\{.*?\n\}\n(?=\nbool FoveatedRender::IsEyeTrackedFoveationEnabled)'
$resetReplacement = @'
void FoveatedRender::ResetAdaptiveState()
{
	const bool cropWasActive = adaptiveCropController.IsRuntimeActive();
	adaptiveController.Reset();
	adaptiveCropController.Reset();
	adaptiveNextDownshiftIsCrop = true;
	adaptiveCropDiagnosticGeneration = UINT64_MAX;
	const std::uint32_t manualPasses = std::clamp(settings.neuralRenderingMultiPass + 1u, 1u, 3u);
	adaptiveConfiguredPasses = manualPasses;
	adaptiveActivePasses = manualPasses;
	adaptivePassDwellFrames = 0;
	adaptivePassPressureFrames = 0;
	adaptivePassHeadroomFrames = 0;
	adaptivePassInitialized = false;
	adaptiveFastWorkloadMs = 0.0f;
	adaptiveSlowWorkloadMs = 0.0f;
	adaptiveCropTargetCoverage = 100;
	adaptiveOverBudgetMs = 0.0f;
	adaptiveHeadroomMs = 0.0f;
	adaptiveCooldownMs = 0.0f;
	adaptiveLastGpuMs = 0.0f;
	adaptiveLastCpuMs = 0.0f;
	adaptiveOutlierStreak = 0;
	adaptiveGpuLimited = true;
	if (cropWasActive)
		FoveatedRenderImpl::Core::ResetAdaptiveCropHandoff();
}
'@
Replace-RegexOnce $foveated $resetPattern $resetReplacement

Write-Host 'v04 unified controller: replace v03 competing controllers with one budget ladder'
$updatePattern = '(?s)void FoveatedRender::UpdateAdaptiveState\(std::uint32_t frame, bool routeEligible\)\n\{.*?\n\}\n(?=\nUtil::Subrect::UVRegion FoveatedRender::GetEffectiveLeftUV)'
$updateReplacement = @'
void FoveatedRender::UpdateAdaptiveState(std::uint32_t frame, bool routeEligible)
{
	const auto& nrRenderer = NeuralRendering::Renderer::Instance();
	const auto& streamline = globals::features::upscaling.streamline;
	const bool recentDLSSFailure = streamline.lastDLSSFailureFrame != UINT32_MAX &&
		frame >= streamline.lastDLSSFailureFrame && frame - streamline.lastDLSSFailureFrame <= 1;
	const bool runtimeHealthy = !nrRenderer.IsFailureLatched() && !recentDLSSFailure;
	const auto method = globals::features::upscaling.GetUpscaleMethod();
	const bool nrEligible = routeEligible && IsActive() &&
		method == Upscaling::UpscaleMethod::kDLSS && GetDlssMode() == DlssMode::kDefault &&
		settings.neuralRenderingEnabled && !globals::features::upscaling.IsFrameGenerationActive() &&
		!globals::features::openNRCapture.settings.enableCapture &&
		settings.neuralRenderingPreUpscale == 0 && runtimeHealthy;

	const std::uint32_t manualPasses = std::clamp(settings.neuralRenderingMultiPass + 1u, 1u, 3u);
	// Atlas owns one Feature18 evaluation for both eyes per stage and currently
	// supports one or two stages. When adaptive is active, keep the atlas route
	// instead of silently falling back to independent-eye evaluation.
	const std::uint32_t requestedPasses = settings.neuralRenderingStereoAtlas ?
		std::min(manualPasses, 2u) : manualPasses;

	if (!settings.neuralRenderingAdaptiveEnabled || !nrEligible) {
		if (adaptiveController.IsEnabled() || adaptiveCropController.IsEnabled() || adaptivePassInitialized)
			ResetAdaptiveState();
		adaptiveConfiguredPasses = manualPasses;
		adaptiveActivePasses = manualPasses;
		return;
	}

	const auto leftUV = subrectController.GetUV();
	const auto rightUV = subrectController.GetRightEyeUV();
	const bool geometryCompatible = std::abs(leftUV.w - rightUV.w) <= 0.0005f &&
		std::abs(leftUV.h - rightUV.h) <= 0.0005f;
	const bool eyeTrackingOwnsOrigin = IsEyeTrackedFoveationEnabled();

	const float targetFps = settings.neuralRenderingAdaptiveTargetFps != 0 ?
		static_cast<float>(std::clamp(settings.neuralRenderingAdaptiveTargetFps, 15u, 60u)) :
		static_cast<float>(settings.neuralRenderingAdaptiveRefreshHz) * 0.5f;
	const float deadlineMs = 1000.0f / std::max(targetFps, 1.0f);
	const float guardMs = std::clamp(settings.neuralRenderingAdaptiveGuardTimeMs, 0.0f, 5.0f);
	const float budgetMs = std::max(1.0f, deadlineMs - guardMs);
	const float passCostMs = std::clamp(settings.neuralRenderingAdaptiveSecondPassCostMs, 0.5f, 20.0f);
	const float restoreMarginMs = std::max(1.0f, guardMs + 0.5f);
	const float restoreBudgetMs = std::max(1.0f, budgetMs - restoreMarginMs);
	const float downDelayMs = std::clamp(
		static_cast<float>(std::max(settings.neuralRenderingAdaptiveDownshiftFrames, 1u)) * deadlineMs,
		50.0f, 500.0f);
	const float upDelayMs = std::clamp(
		static_cast<float>(std::max(settings.neuralRenderingAdaptiveUpshiftFrames, 4u)) * deadlineMs,
		500.0f, 4000.0f);
	const float dwellMs = std::clamp(
		static_cast<float>(std::max(settings.neuralRenderingAdaptiveMinimumDwellFrames, 4u)) * deadlineMs,
		150.0f, 1000.0f);

	if (!adaptivePassInitialized) {
		adaptivePassInitialized = true;
		adaptiveConfiguredPasses = requestedPasses;
		adaptiveActivePasses = requestedPasses;
		adaptiveCropTargetCoverage = 100;
		adaptiveFastWorkloadMs = 0.0f;
		adaptiveSlowWorkloadMs = 0.0f;
		adaptiveOverBudgetMs = 0.0f;
		adaptiveHeadroomMs = 0.0f;
		adaptiveCooldownMs = 0.0f;
		adaptiveOutlierStreak = 0;
	}
	if (requestedPasses != adaptiveConfiguredPasses) {
		const auto oldConfigured = adaptiveConfiguredPasses;
		adaptiveConfiguredPasses = requestedPasses;
		adaptiveActivePasses = std::min(adaptiveActivePasses, adaptiveConfiguredPasses);
		adaptiveOverBudgetMs = 0.0f;
		adaptiveHeadroomMs = 0.0f;
		adaptiveCooldownMs = std::max(adaptiveCooldownMs, std::min(dwellMs, 500.0f));
		logger::info("[DLSSNR][ADAPTIVE-v04] configured passes {} -> {} active={}",
			oldConfigured, adaptiveConfiguredPasses, adaptiveActivePasses);
	}

	const bool cropPolicyAvailable = settings.neuralRenderingAdaptiveCropEnabled && geometryCompatible;
	const std::uint32_t minimumCrop = std::clamp(settings.neuralRenderingAdaptiveCropMinimumCoverage, 50u, 100u);
	if (!cropPolicyAvailable)
		adaptiveCropTargetCoverage = 100;
	else
		adaptiveCropTargetCoverage = std::clamp(adaptiveCropTargetCoverage, minimumCrop, 100u);

	float gpuWorkMs = -1.0f;
	float cpuWorkMs = -1.0f;
	float sampleDeltaMs = deadlineMs;
	bool freshTiming = false;
	static std::uint32_t timingFrame = UINT32_MAX;
	static std::uint32_t sampledEngineFrame = UINT32_MAX;
	if (globals::game::isVR && frame != sampledEngineFrame) {
		sampledEngineFrame = frame;
		if (auto* compositor = RE::BSOpenVR::GetIVRCompositor()) {
			vr::Compositor_FrameTiming timing{};
			timing.m_nSize = sizeof(timing);
			if (compositor->GetFrameTiming(&timing) && timing.m_nFrameIndex != timingFrame) {
				timingFrame = timing.m_nFrameIndex;
				const float gpuMs = timing.m_flPreSubmitGpuMs + timing.m_flPostSubmitGpuMs;
				const float cpuMs = timing.m_flNewFrameReadyMs - timing.m_flNewPosesReadyMs;
				if (std::isfinite(gpuMs) && gpuMs > 0.0f) {
					gpuWorkMs = gpuMs;
					freshTiming = true;
				}
				if (std::isfinite(cpuMs) && cpuMs >= 0.0f)
					cpuWorkMs = cpuMs;
				if (std::isfinite(timing.m_flClientFrameIntervalMs) && timing.m_flClientFrameIntervalMs > 0.0f)
					sampleDeltaMs = std::clamp(timing.m_flClientFrameIntervalMs, 5.0f, 50.0f);
			}
		}
	}

	bool acceptedTiming = false;
	bool severePressure = false;
	bool overBudget = false;
	bool hasHeadroom = false;
	if (freshTiming) {
		adaptiveLastGpuMs = gpuWorkMs;
		adaptiveLastCpuMs = cpuWorkMs;
		const float outlierLimitMs = std::max(100.0f, deadlineMs * 4.0f);
		const bool grossOutlier = gpuWorkMs > outlierLimitMs;
		if (grossOutlier) {
			adaptiveOutlierStreak = std::min(adaptiveOutlierStreak + 1u, 1000u);
			// Ignore one loading/driver spike. A persistent second sample is treated
			// as a real scene transition and allowed to drive a fast downshift.
			acceptedTiming = adaptiveOutlierStreak >= 2;
			gpuWorkMs = std::min(gpuWorkMs, outlierLimitMs);
		} else {
			adaptiveOutlierStreak = 0;
			acceptedTiming = true;
		}
		if (streamline.IsVRAMPressure()) {
			acceptedTiming = true;
			gpuWorkMs = std::max(gpuWorkMs, budgetMs + std::max(2.0f, passCostMs * 0.75f));
		}
	}

	if (acceptedTiming) {
		if (adaptiveFastWorkloadMs <= 0.0f || adaptiveSlowWorkloadMs <= 0.0f) {
			adaptiveFastWorkloadMs = gpuWorkMs;
			adaptiveSlowWorkloadMs = gpuWorkMs;
		} else {
			// Fast EMA catches combat/exterior transitions; slow EMA prevents a
			// single transient from immediately restoring quality after a downshift.
			adaptiveFastWorkloadMs += (gpuWorkMs - adaptiveFastWorkloadMs) * 0.35f;
			const float low = std::max(0.1f, adaptiveSlowWorkloadMs * 0.55f);
			const float high = std::max(low, adaptiveSlowWorkloadMs * 1.80f);
			const float clipped = std::clamp(gpuWorkMs, low, high);
			adaptiveSlowWorkloadMs += (clipped - adaptiveSlowWorkloadMs) * 0.08f;
		}

		adaptiveGpuLimited = cpuWorkMs <= 0.0f || gpuWorkMs + 0.75f >= cpuWorkMs ||
			gpuWorkMs > budgetMs * 0.95f || streamline.IsVRAMPressure();
		severePressure = streamline.IsVRAMPressure() ||
			gpuWorkMs > deadlineMs + std::max(2.0f, passCostMs * 0.75f) ||
			adaptiveFastWorkloadMs > deadlineMs + std::max(1.0f, passCostMs * 0.50f);
		overBudget = adaptiveGpuLimited &&
			(adaptiveFastWorkloadMs > budgetMs ||
			 (adaptiveSlowWorkloadMs > budgetMs * 0.98f && gpuWorkMs > budgetMs));
		hasHeadroom = adaptiveFastWorkloadMs < restoreBudgetMs &&
			adaptiveSlowWorkloadMs < restoreBudgetMs;

		adaptiveCooldownMs = std::max(0.0f, adaptiveCooldownMs - sampleDeltaMs);
		if (overBudget) {
			adaptiveOverBudgetMs += sampleDeltaMs;
			adaptiveHeadroomMs = 0.0f;
		} else if (hasHeadroom) {
			adaptiveHeadroomMs += sampleDeltaMs;
			adaptiveOverBudgetMs = std::max(0.0f, adaptiveOverBudgetMs - sampleDeltaMs * 0.50f);
		} else {
			adaptiveOverBudgetMs = std::max(0.0f, adaptiveOverBudgetMs - sampleDeltaMs * 0.25f);
			adaptiveHeadroomMs = 0.0f;
		}
	}

	auto nextLowerCrop = [minimumCrop](std::uint32_t current) {
		for (const auto bucket : NeuralRendering::AdaptiveCropController::CoverageBuckets())
			if (bucket < current && bucket >= minimumCrop)
				return bucket;
		return current;
	};
	auto nextHigherCrop = [](std::uint32_t current) {
		const auto& buckets = NeuralRendering::AdaptiveCropController::CoverageBuckets();
		for (auto it = buckets.rbegin(); it != buckets.rend(); ++it)
			if (*it > current)
				return *it;
		return current;
	};

	bool qualityChanged = false;
	const auto previousPasses = adaptiveActivePasses;
	const auto previousCropTarget = adaptiveCropTargetCoverage;
	if (acceptedTiming && adaptiveCooldownMs <= 0.0f) {
		const float controlWorkMs = std::max(adaptiveFastWorkloadMs, adaptiveSlowWorkloadMs);
		const float deficitMs = std::max(0.0f, controlWorkMs - budgetMs);
		const float emergencyDelayMs = std::min(downDelayMs, std::max(2.0f * deadlineMs, 60.0f));
		const bool downshiftReady = adaptiveOverBudgetMs >= downDelayMs ||
			(severePressure && adaptiveOverBudgetMs >= emergencyDelayMs);
		if (downshiftReady) {
			const bool cropCanShrink = cropPolicyAvailable && adaptiveCropTargetCoverage > minimumCrop;
			const bool extraPassCanDrop = adaptiveActivePasses > 1;
			const bool largeDeficit = deficitMs >= std::max(1.0f, passCostMs * 0.35f);
			const bool sustained = adaptiveOverBudgetMs >= downDelayMs * 2.0f;

			if (extraPassCanDrop && (largeDeficit || severePressure || sustained)) {
				--adaptiveActivePasses;
				qualityChanged = true;
			} else if (cropCanShrink) {
				adaptiveCropTargetCoverage = nextLowerCrop(adaptiveCropTargetCoverage);
				qualityChanged = adaptiveCropTargetCoverage != previousCropTarget;
			} else if (extraPassCanDrop) {
				--adaptiveActivePasses;
				qualityChanged = true;
			} else if (adaptiveActivePasses == 1) {
				// Zero-NR is an emergency floor, not a normal oscillation tier. Reach it
				// only after crop is exhausted and pressure is both severe or sustained.
				const bool lastPassEmergency = severePressure ||
					adaptiveOverBudgetMs >= std::max(800.0f, downDelayMs * 4.0f) ||
					deficitMs >= passCostMs * 0.75f;
				if (lastPassEmergency) {
					adaptiveActivePasses = 0;
					qualityChanged = true;
				}
			}
			if (qualityChanged) {
				adaptiveOverBudgetMs = 0.0f;
				adaptiveHeadroomMs = 0.0f;
				adaptiveCooldownMs = dwellMs;
			}
		} else if (adaptiveHeadroomMs >= upDelayMs) {
			// Restore expensive passes only when measured headroom can pay their
			// configured cost. Otherwise spend smaller headroom on crop recovery.
			const bool passCanRestore = adaptiveActivePasses < adaptiveConfiguredPasses &&
				adaptiveSlowWorkloadMs + passCostMs < restoreBudgetMs &&
				adaptiveFastWorkloadMs + passCostMs < restoreBudgetMs;
			if (passCanRestore) {
				const bool wasZero = adaptiveActivePasses == 0;
				++adaptiveActivePasses;
				if (wasZero)
					NeuralRendering::ResetHistory();
				qualityChanged = true;
			} else if (cropPolicyAvailable && adaptiveCropTargetCoverage < 100 && hasHeadroom) {
				adaptiveCropTargetCoverage = nextHigherCrop(adaptiveCropTargetCoverage);
				qualityChanged = adaptiveCropTargetCoverage != previousCropTarget;
			}
			if (qualityChanged) {
				adaptiveOverBudgetMs = 0.0f;
				adaptiveHeadroomMs = 0.0f;
				adaptiveCooldownMs = std::max(dwellMs, 500.0f);
			}
		}
	}

	NeuralRendering::AdaptiveCropController::Config cropConfig;
	cropConfig.enabled = settings.neuralRenderingAdaptiveCropEnabled;
	cropConfig.hold = false;
	cropConfig.maximumCoverage = 100;
	cropConfig.minimumCoverage = minimumCrop;
	// v04 owns timing/hysteresis. The existing crop controller is retained only
	// as a safe stereo handoff actuator between adjacent relative crop buckets.
	cropConfig.downshiftFrames = 1;
	cropConfig.upshiftFrames = 8;
	cropConfig.minimumDwellFrames = 8;
	cropConfig.transitionFrames = settings.neuralRenderingAdaptiveCropTransitionFrames;
	const auto currentCrop = adaptiveCropController.IsRuntimeActive() ?
		adaptiveCropController.ActiveCoverage() : 100u;
	const bool driveCropDown = cropPolicyAvailable && currentCrop > adaptiveCropTargetCoverage;
	const bool driveCropUp = cropPolicyAvailable && currentCrop < adaptiveCropTargetCoverage;
	adaptiveCropController.Update(frame, cropConfig, cropPolicyAvailable,
		100, geometryCompatible, false, driveCropDown, false, true,
		driveCropDown, driveCropUp);

	if (qualityChanged) {
		logger::info("[DLSSNR][ADAPTIVE-v04] quality passes {} -> {} cropTarget {} -> {} gpu={:.2f} fast={:.2f} slow={:.2f} budget={:.2f} passCost={:.2f} atlas={} gaze={}",
			previousPasses, adaptiveActivePasses, previousCropTarget, adaptiveCropTargetCoverage,
			adaptiveLastGpuMs, adaptiveFastWorkloadMs, adaptiveSlowWorkloadMs, budgetMs,
			passCostMs, settings.neuralRenderingStereoAtlas, eyeTrackingOwnsOrigin);
	}

	static std::uint32_t lastBudgetLog = UINT32_MAX;
	if (frame % 300 == 0 && frame != lastBudgetLog) {
		lastBudgetLog = frame;
		logger::info("[DLSSNR][BUDGET-v04] frame={} fresh={} gpu={:.2f} cpu={:.2f} fast={:.2f} slow={:.2f} budget={:.2f} restore={:.2f} passes={}/{} crop={}/{} gpuLimited={} overMs={:.0f} headroomMs={:.0f} cooldownMs={:.0f} atlas={} gaze={}",
			frame, acceptedTiming, adaptiveLastGpuMs, adaptiveLastCpuMs,
			adaptiveFastWorkloadMs, adaptiveSlowWorkloadMs, budgetMs, restoreBudgetMs,
			adaptiveActivePasses, adaptiveConfiguredPasses,
			adaptiveCropController.IsRuntimeActive() ? adaptiveCropController.ActiveCoverage() : 100u,
			adaptiveCropTargetCoverage, adaptiveGpuLimited,
			adaptiveOverBudgetMs, adaptiveHeadroomMs, adaptiveCooldownMs,
			settings.neuralRenderingStereoAtlas, eyeTrackingOwnsOrigin);
	}
}
'@
Replace-RegexOnce $foveated $updatePattern $updateReplacement

Write-Host 'v04 integration: make unified adaptive state authoritative and atlas-safe'
$adaptiveOld = @'
			const bool adaptive = adaptiveEligible && settings.neuralRenderingAdaptiveEnabled &&
				foveated.adaptiveController.IsEnabled();
'@
$adaptiveNew = @'
			const bool adaptive = adaptiveEligible && settings.neuralRenderingAdaptiveEnabled &&
				foveated.adaptivePassInitialized;
'@
Replace-ExactOnce $integration $adaptiveOld $adaptiveNew

$prewarmOld = @'
			const auto& controller = foveated.adaptiveController;
			const int prewarmDirection = !adaptive || foveated.IsAdaptiveCropTransitioning() ? 0 :
				controller.LastSampleOverBudget() && !controller.IsAtMinimum() ? -1 :
				controller.LastSampleHadHeadroom() && !controller.IsAtMaximum() ? 1 : 0;
'@
$prewarmNew = @'
			const auto& controller = foveated.adaptiveController;
			// v04 keeps model resolution fixed while adaptive is active. This avoids
			// atlas fallback/resource recreation and leaves pass/crop as the only knobs.
			const int prewarmDirection = 0;
'@
Replace-ExactOnce $integration $prewarmOld $prewarmNew

$multiOld = 'tuning.multiPass = foveated.adaptiveActivePasses > 1 ? std::min(foveated.adaptiveActivePasses - 1u, 1u) : 0u;'
$multiNew = 'tuning.multiPass = foveated.adaptiveActivePasses > 0 ? std::min(foveated.adaptiveActivePasses - 1u, 2u) : 0u;'
Replace-ExactOnce $integration $multiOld $multiNew

$bypassOld = 'foveated.settings.neuralRenderingAdaptiveEnabled && foveated.adaptiveController.IsEnabled() &&'
$bypassNew = 'foveated.settings.neuralRenderingAdaptiveEnabled && foveated.adaptivePassInitialized &&'
Replace-ExactOnce $integration $bypassOld $bypassNew

$modelLockAnchor = @'
			if constexpr (kFullResolutionNeuralRenderingOnly) {
'@
$modelLockInsert = @'
			if (adaptive) {
				// Pass/crop adaptation must not set adaptiveResolution: the stereo-atlas
				// native route intentionally rejects that flag and would otherwise fall
				// back to two independent eye evaluations. Keep the user-selected model
				// resolution stable and let the unified controller change only work that
				// is safe to vary frame-to-frame.
				tuning.modelResolutionPercent = settings.neuralRenderingModelResolution;
				tuning.adaptiveResolution = false;
				tuning.adaptiveHandoff = !adaptiveCrop;
				tuning.adaptiveHandoffAlpha = 1.0f;
				tuning.adaptivePrewarmDirection = 0;
				tuning.adaptiveMemoryCeiling = 100;
			}
			if constexpr (kFullResolutionNeuralRenderingOnly) {
'@
Replace-ExactOnce $integration $modelLockAnchor $modelLockInsert

Write-Host 'v04 unified controller verification'
$h = Read-Normalized $header
$f = Read-Normalized $foveated
$i = Read-Normalized $integration
if ($h -notmatch 'adaptiveCropTargetCoverage') { throw 'Unified crop target state missing' }
if ($f -notmatch '\[DLSSNR\]\[ADAPTIVE-v04\]') { throw 'Unified v04 controller body missing' }
if ($f -match 'adaptiveController\.Update\(') { throw 'Old model-resolution controller still drives v04 adaptive decisions' }
if ($i -notmatch 'foveated\.adaptivePassInitialized') { throw 'Integration is not keyed to unified adaptive state' }
if ($i -notmatch 'tuning\.adaptiveResolution = false') { throw 'Atlas-safe adaptiveResolution override missing' }
if ($i -notmatch 'adaptiveActivePasses > 0 \? std::min\(foveated\.adaptiveActivePasses - 1u, 2u\)') { throw 'Adaptive pass count is not wired for 1/2/3 pass states' }
if ($i -notmatch 'adaptiveActivePasses == 0') { throw 'Zero-pass bypass missing' }

Write-Host 'v04 unified pass/crop frametime controller applied successfully.'
