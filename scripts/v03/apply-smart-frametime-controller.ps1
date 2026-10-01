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
$adaptiveHeader = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/AdaptiveController.h'
$adaptiveCpp = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/AdaptiveController.cpp'
$integration = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Integration.cpp'

Write-Host 'v03 controller: add explicit adaptive pass state'
$stateOld = @'
	bool adaptiveNextDownshiftIsCrop = true;
	std::uint64_t adaptiveCropDiagnosticGeneration = UINT64_MAX;
'@
$stateNew = @'
	bool adaptiveNextDownshiftIsCrop = true;
	std::uint64_t adaptiveCropDiagnosticGeneration = UINT64_MAX;
	// v03 pass controller. Adaptive mode intentionally caps automatic sequential
	// operation at two passes; 3x remains available when the controller is off.
	std::uint32_t adaptiveActivePasses = 1;
	std::uint32_t adaptiveConfiguredPasses = 1;
	std::uint32_t adaptivePassDwellFrames = 0;
	std::uint32_t adaptivePassPressureFrames = 0;
	std::uint32_t adaptivePassHeadroomFrames = 0;
	bool adaptivePassInitialized = false;
	float adaptiveFastWorkloadMs = 0.0f;
	float adaptiveSlowWorkloadMs = 0.0f;
'@
Replace-ExactOnce $header $stateOld $stateNew

Write-Host 'v03 controller: make the underlying NR tier controller less spike-sensitive'
$adaptiveStateOld = @'
		float lastFrameTimeMs_ = 0.0f;
		float smoothedFrameTimeMs_ = 0.0f;
		bool lastSampleOverBudget_ = false;
'@
$adaptiveStateNew = @'
		float lastFrameTimeMs_ = 0.0f;
		float smoothedFrameTimeMs_ = 0.0f;
		float fastFrameTimeMs_ = 0.0f;
		float slowFrameTimeMs_ = 0.0f;
		bool lastSampleOverBudget_ = false;
'@
Replace-ExactOnce $adaptiveHeader $adaptiveStateOld $adaptiveStateNew

$resetOld = @'
		lastFrameTimeMs_ = 0.0f;
		smoothedFrameTimeMs_ = 0.0f;
		lastSampleOverBudget_ = false;
'@
$resetNew = @'
		lastFrameTimeMs_ = 0.0f;
		smoothedFrameTimeMs_ = 0.0f;
		fastFrameTimeMs_ = 0.0f;
		slowFrameTimeMs_ = 0.0f;
		lastSampleOverBudget_ = false;
'@
Replace-ExactOnce $adaptiveCpp $resetOld $resetNew

$smoothingOld = @'
		if (frameTimeMs > 0.0f) {
			lastFrameTimeMs_ = frameTimeMs;
			smoothedFrameTimeMs_ = smoothedFrameTimeMs_ == 0.0f ? frameTimeMs :
				smoothedFrameTimeMs_ * 0.90f + frameTimeMs * 0.10f;
		}
'@
$smoothingNew = @'
		if (frameTimeMs > 0.0f) {
			lastFrameTimeMs_ = frameTimeMs;
			if (fastFrameTimeMs_ == 0.0f || slowFrameTimeMs_ == 0.0f) {
				fastFrameTimeMs_ = frameTimeMs;
				slowFrameTimeMs_ = frameTimeMs;
			} else {
				// Fast path follows real interior/exterior or combat load changes within
				// a few frames. Slow path clips isolated compositor spikes so recovery
				// cannot immediately undo a degradation decision.
				fastFrameTimeMs_ = fastFrameTimeMs_ * 0.55f + frameTimeMs * 0.45f;
				const float low = std::max(0.1f, slowFrameTimeMs_ * 0.60f);
				const float high = std::max(low, slowFrameTimeMs_ * 1.80f);
				const float clipped = std::clamp(frameTimeMs, low, high);
				slowFrameTimeMs_ = slowFrameTimeMs_ * 0.94f + clipped * 0.06f;
			}
			smoothedFrameTimeMs_ = slowFrameTimeMs_;
		}
'@
Replace-ExactOnce $adaptiveCpp $smoothingOld $smoothingNew

$budgetPattern = '(?s)\t\tconst float guardedDeadline = std::max\(1\.0f, applicationDeadlineMs_ - config\.guardTimeMs\);.*?\n\t\tlastSampleHadHeadroom_ = headroom;'
$budgetReplacement = @'
		const float guardedDeadline = std::max(1.0f, applicationDeadlineMs_ - config.guardTimeMs);
		const bool emergencyOverrun = frameTimeMs > applicationDeadlineMs_ * 1.30f ||
			fastFrameTimeMs_ > applicationDeadlineMs_ * 1.18f;
		const bool overrun = emergencyOverrun ||
			(fastFrameTimeMs_ > guardedDeadline && slowFrameTimeMs_ > applicationDeadlineMs_ * 0.96f) ||
			(frameTimeMs > guardedDeadline && fastFrameTimeMs_ > guardedDeadline);
		const float restorationBudget = std::max(1.0f, std::min(applicationDeadlineMs_ * 0.82f,
			applicationDeadlineMs_ - std::max(config.guardTimeMs * 2.0f, 1.0f)));
		const bool headroom = frameTimeMs < applicationDeadlineMs_ * 0.95f &&
			fastFrameTimeMs_ < restorationBudget && slowFrameTimeMs_ < restorationBudget;
		lastSampleOverBudget_ = overrun;
		lastSampleHadHeadroom_ = headroom;
'@
Replace-RegexOnce $adaptiveCpp $budgetPattern $budgetReplacement

Write-Host 'v03 controller: reset pass timing state with the inherited adaptive state'
$resetPattern = '(?s)void FoveatedRender::ResetAdaptiveState\(\)\n\{.*?\n\}\n(?=\nbool FoveatedRender::IsEyeTrackedFoveationEnabled)'
$resetReplacement = @'
void FoveatedRender::ResetAdaptiveState()
{
	const bool cropWasActive = adaptiveCropController.IsRuntimeActive();
	adaptiveController.Reset();
	adaptiveCropController.Reset();
	adaptiveNextDownshiftIsCrop = true;
	adaptiveCropDiagnosticGeneration = UINT64_MAX;
	adaptiveConfiguredPasses = settings.neuralRenderingMultiPass == 0 ? 1u : 2u;
	adaptiveActivePasses = adaptiveConfiguredPasses;
	adaptivePassDwellFrames = 0;
	adaptivePassPressureFrames = 0;
	adaptivePassHeadroomFrames = 0;
	adaptivePassInitialized = false;
	adaptiveFastWorkloadMs = 0.0f;
	adaptiveSlowWorkloadMs = 0.0f;
	if (cropWasActive)
		FoveatedRenderImpl::Core::ResetAdaptiveCropHandoff();
}
'@
Replace-RegexOnce $foveated $resetPattern $resetReplacement

Write-Host 'v03 controller: replace adaptive policy function while preserving renderer ownership'
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

	const std::uint32_t requestedPasses = settings.neuralRenderingMultiPass == 0 ? 1u : 2u;
	if (!settings.neuralRenderingAdaptiveEnabled || !nrEligible) {
		if (adaptiveController.IsEnabled() || adaptiveCropController.IsEnabled() || adaptivePassInitialized)
			ResetAdaptiveState();
		adaptiveConfiguredPasses = requestedPasses;
		adaptiveActivePasses = requestedPasses;
		return;
	}

	const auto leftUV = subrectController.GetUV();
	const auto rightUV = subrectController.GetRightEyeUV();
	const bool geometryCompatible = std::abs(leftUV.w - rightUV.w) <= 0.0005f &&
		std::abs(leftUV.h - rightUV.h) <= 0.0005f;
	const bool eyeTrackingOwnsCrop = IsEyeTrackedFoveationEnabled();

	const float targetFps = settings.neuralRenderingAdaptiveTargetFps != 0 ?
		static_cast<float>(std::clamp(settings.neuralRenderingAdaptiveTargetFps, 15u, 60u)) :
		static_cast<float>(settings.neuralRenderingAdaptiveRefreshHz) * 0.5f;
	const float deadlineMs = 1000.0f / std::max(targetFps, 1.0f);
	const float guardMs = std::clamp(settings.neuralRenderingAdaptiveGuardTimeMs, 0.0f, 5.0f);
	const float passCostMs = std::clamp(settings.neuralRenderingAdaptiveSecondPassCostMs, 0.5f, 20.0f);
	const float pressureBudgetMs = std::max(1.0f, deadlineMs - guardMs);

	float workloadMs = -1.0f;
	float gpuWorkMs = -1.0f;
	float activeSubmitMs = -1.0f;
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
				gpuWorkMs = gpuMs;
				activeSubmitMs = cpuMs;
				if (std::isfinite(gpuMs) && gpuMs > 0.0f && std::isfinite(cpuMs) && cpuMs >= 0.0f)
					workloadMs = std::max(gpuMs, cpuMs);
			}
		}
	}
	if (streamline.IsVRAMPressure())
		workloadMs = std::max(workloadMs, deadlineMs * 1.35f);

	if (workloadMs > 0.0f) {
		if (adaptiveFastWorkloadMs <= 0.0f || adaptiveSlowWorkloadMs <= 0.0f) {
			adaptiveFastWorkloadMs = workloadMs;
			adaptiveSlowWorkloadMs = workloadMs;
		} else {
			adaptiveFastWorkloadMs = adaptiveFastWorkloadMs * 0.55f + workloadMs * 0.45f;
			const float low = std::max(0.1f, adaptiveSlowWorkloadMs * 0.60f);
			const float high = std::max(low, adaptiveSlowWorkloadMs * 1.80f);
			adaptiveSlowWorkloadMs = adaptiveSlowWorkloadMs * 0.94f + std::clamp(workloadMs, low, high) * 0.06f;
		}
	}

	if (!adaptivePassInitialized) {
		adaptivePassInitialized = true;
		adaptiveConfiguredPasses = requestedPasses;
		adaptiveActivePasses = requestedPasses;
		adaptivePassDwellFrames = 0;
		adaptivePassPressureFrames = 0;
		adaptivePassHeadroomFrames = 0;
	}
	if (requestedPasses != adaptiveConfiguredPasses) {
		adaptiveConfiguredPasses = requestedPasses;
		adaptiveActivePasses = std::min(adaptiveActivePasses, adaptiveConfiguredPasses);
		adaptivePassDwellFrames = 0;
		adaptivePassPressureFrames = 0;
		adaptivePassHeadroomFrames = 0;
	}
	adaptivePassDwellFrames = std::min(adaptivePassDwellFrames + 1u, 100000u);

	const bool timingValid = workloadMs > 0.0f && adaptiveFastWorkloadMs > 0.0f && adaptiveSlowWorkloadMs > 0.0f;
	const bool severePressure = timingValid &&
		(workloadMs > deadlineMs + std::max(2.0f, passCostMs * 0.50f) ||
		 adaptiveFastWorkloadMs > deadlineMs + passCostMs * 0.35f);
	const bool sustainedPressure = timingValid &&
		adaptiveFastWorkloadMs > pressureBudgetMs &&
		(adaptiveSlowWorkloadMs > deadlineMs * 0.96f || workloadMs > deadlineMs * 1.10f);
	const float passRestoreBudgetMs = std::max(1.0f, deadlineMs - std::max(guardMs * 2.0f, 1.0f) - 0.5f);
	const bool passWouldFit = timingValid &&
		adaptiveFastWorkloadMs + passCostMs < passRestoreBudgetMs &&
		adaptiveSlowWorkloadMs + passCostMs < passRestoreBudgetMs;

	if (sustainedPressure || severePressure) {
		adaptivePassPressureFrames = std::min(adaptivePassPressureFrames + 1u, 10000u);
		adaptivePassHeadroomFrames = 0;
	} else if (passWouldFit && adaptiveActivePasses < adaptiveConfiguredPasses) {
		adaptivePassHeadroomFrames = std::min(adaptivePassHeadroomFrames + 1u, 10000u);
		adaptivePassPressureFrames = adaptivePassPressureFrames > 0 ? adaptivePassPressureFrames - 1 : 0;
	} else {
		adaptivePassPressureFrames = adaptivePassPressureFrames > 0 ? adaptivePassPressureFrames - 1 : 0;
		adaptivePassHeadroomFrames = adaptivePassHeadroomFrames > 0 ? adaptivePassHeadroomFrames - 1 : 0;
	}

	const std::uint32_t passDownFrames = std::max(2u, settings.neuralRenderingAdaptiveDownshiftFrames);
	const std::uint32_t passUpFrames = std::max(24u, settings.neuralRenderingAdaptiveUpshiftFrames * 2u);
	const std::uint32_t passDwellFrames = std::max(30u, settings.neuralRenderingAdaptiveMinimumDwellFrames);
	const bool cropAtFloor = !adaptiveCropController.IsRuntimeActive() ||
		adaptiveCropController.ActiveCoverage() <= adaptiveCropController.MinimumCoverage();
	const bool otherQualityAtFloor = adaptiveController.IsAtMinimum() && cropAtFloor;
	bool passChangedThisFrame = false;
	const auto previousPasses = adaptiveActivePasses;
	if (adaptivePassDwellFrames >= passDwellFrames && adaptiveActivePasses > 0 &&
		adaptivePassPressureFrames >= passDownFrames) {
		const float deficitMs = std::max(0.0f, adaptiveFastWorkloadMs - pressureBudgetMs);
		const bool dropExtraPass = adaptiveActivePasses > 1 &&
			(severePressure || deficitMs >= passCostMs * 0.35f || adaptivePassPressureFrames >= passDownFrames * 2u);
		const bool dropLastPass = adaptiveActivePasses == 1 &&
			(severePressure || (otherQualityAtFloor && deficitMs >= passCostMs * 0.40f));
		if (dropExtraPass || dropLastPass) {
			--adaptiveActivePasses;
			adaptivePassDwellFrames = 0;
			adaptivePassPressureFrames = 0;
			adaptivePassHeadroomFrames = 0;
			adaptiveNextDownshiftIsCrop = true;
			passChangedThisFrame = true;
		}
	} else if (adaptivePassDwellFrames >= passDwellFrames &&
		adaptiveActivePasses < adaptiveConfiguredPasses && passWouldFit &&
		adaptivePassHeadroomFrames >= passUpFrames) {
		++adaptiveActivePasses;
		adaptivePassDwellFrames = 0;
		adaptivePassPressureFrames = 0;
		adaptivePassHeadroomFrames = 0;
		passChangedThisFrame = true;
		if (previousPasses == 0)
			NeuralRendering::ResetHistory();
	}
	if (passChangedThisFrame)
		logger::info("[DLSSNR][ADAPTIVE] pass count {} -> {} configured={} passCost={:.2f}ms workFast={:.2f} workSlow={:.2f} budget={:.2f}",
			previousPasses, adaptiveActivePasses, adaptiveConfiguredPasses, passCostMs,
			adaptiveFastWorkloadMs, adaptiveSlowWorkloadMs, pressureBudgetMs);

	const bool cropPolicyAvailable = settings.neuralRenderingAdaptiveCropEnabled && geometryCompatible;
	const bool cropCanDownshift = cropPolicyAvailable &&
		!FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected &&
		!FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected &&
		(adaptiveCropController.IsRuntimeActive() ?
			adaptiveCropController.ActiveCoverage() > adaptiveCropController.MinimumCoverage() :
			settings.neuralRenderingAdaptiveCropMinimumCoverage < 100);
	const bool nrCanDownshift = !adaptiveController.IsAtMinimum();
	const bool holdOtherForPassDecision = passChangedThisFrame ||
		(adaptiveActivePasses > 1 && adaptivePassPressureFrames > 0 && (sustainedPressure || severePressure));
	const bool cropShouldDownshiftFirst = cropCanDownshift && !holdOtherForPassDecision &&
		(adaptiveNextDownshiftIsCrop || !nrCanDownshift);

	const auto activeNRForReadiness = adaptiveController.ActiveResolution();
	const auto higherNR = AdjacentAdaptiveResolution(activeNRForReadiness, true);
	const auto lowerNR = AdjacentAdaptiveResolution(activeNRForReadiness, false);
	const bool nrUpshiftReady = adaptiveController.IsAtMaximum() || nrRenderer.IsAdaptiveTierReady(higherNR);
	const bool nrDownshiftReady = adaptiveController.IsAtMinimum() || nrRenderer.IsAdaptiveTierReady(lowerNR);

	NeuralRendering::AdaptiveController::Config nrConfig;
	nrConfig.enabled = true;
	nrConfig.memoryPressure = streamline.IsVRAMPressure();
	nrConfig.allowDownshift = adaptiveActivePasses > 0 && !holdOtherForPassDecision &&
		!cropShouldDownshiftFirst && !adaptiveCropController.IsTransitioning() && nrDownshiftReady;
	// Restore a removed pass first. Model/crop quality may expand only after the
	// requested pass count is stable and there is sustained real headroom.
	nrConfig.allowUpshift = adaptiveActivePasses == adaptiveConfiguredPasses && !passChangedThisFrame &&
		!adaptiveCropController.IsTransitioning() && !nrRenderer.IsRecoveryLimited() &&
		!streamline.IsVRAMPressure() && nrUpshiftReady;
	nrConfig.refreshHz = settings.neuralRenderingAdaptiveRefreshHz;
	nrConfig.targetFps = settings.neuralRenderingAdaptiveTargetFps;
	nrConfig.minimumResolution = settings.neuralRenderingAdaptiveMinimumResolution;
	nrConfig.downshiftFrames = settings.neuralRenderingAdaptiveDownshiftFrames;
	nrConfig.upshiftFrames = settings.neuralRenderingAdaptiveUpshiftFrames;
	nrConfig.minimumDwellFrames = settings.neuralRenderingAdaptiveMinimumDwellFrames;
	nrConfig.guardTimeMs = settings.neuralRenderingAdaptiveGuardTimeMs;

	const auto previousNR = adaptiveController.ActiveResolution();
	const auto previousNRTarget = adaptiveController.TargetResolution();
	const auto previousMemoryCeiling = adaptiveController.MemoryCeiling();
	adaptiveController.Update(frame, nrConfig, true, workloadMs);
	if (previousMemoryCeiling != adaptiveController.MemoryCeiling())
		logger::info("[DLSSNR][MEMORY] ceiling {}% -> {}% active={}%; higher tiers held until Neural Rendering Reset or restart",
			previousMemoryCeiling, adaptiveController.MemoryCeiling(), adaptiveController.ActiveResolution());
	const auto currentNR = adaptiveController.ActiveResolution();
	if (previousNR != currentNR) {
		logger::info("[DLSSNR] adaptive NR handoff {}% -> {}% alpha={:.2f} work={:.2f}/{:.2f}ms reason={}",
			previousNR, currentNR, adaptiveController.HandoffAlpha(),
			adaptiveController.SmoothedFrameTimeMs(), adaptiveController.ApplicationDeadlineMs(),
			adaptiveController.DecisionReason());
		if (currentNR < previousNR)
			adaptiveNextDownshiftIsCrop = true;
	}

	NeuralRendering::AdaptiveCropController::Config cropConfig;
	cropConfig.enabled = settings.neuralRenderingAdaptiveCropEnabled;
	cropConfig.hold = FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected ||
		FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected || passChangedThisFrame;
	cropConfig.maximumCoverage = 100;
	cropConfig.minimumCoverage = settings.neuralRenderingAdaptiveCropMinimumCoverage;
	cropConfig.downshiftFrames = settings.neuralRenderingAdaptiveCropDownshiftFrames;
	cropConfig.upshiftFrames = settings.neuralRenderingAdaptiveCropUpshiftFrames;
	cropConfig.minimumDwellFrames = settings.neuralRenderingAdaptiveCropMinimumDwellFrames;
	cropConfig.transitionFrames = settings.neuralRenderingAdaptiveCropTransitionFrames;

	const bool cropWasActive = adaptiveCropController.IsRuntimeActive();
	const auto previousCrop = adaptiveCropController.ActiveCoverage();
	const auto previousCropTarget = adaptiveCropController.TargetCoverage();
	const auto previousRenderCrop = adaptiveCropController.RenderCoverage();
	const bool nrAtStableMaximum = adaptiveController.IsAtMaximum() && !adaptiveController.IsTransitioning() &&
		adaptiveActivePasses == adaptiveConfiguredPasses;
	adaptiveCropController.Update(frame, cropConfig, geometryCompatible,
		100, geometryCompatible, false, cropShouldDownshiftFirst,
		adaptiveController.IsTransitioning() || passChangedThisFrame, nrAtStableMaximum,
		adaptiveController.LastSampleOverBudget(), adaptiveController.LastSampleHadHeadroom());
	if (cropWasActive && !adaptiveCropController.IsRuntimeActive())
		FoveatedRenderImpl::Core::ResetAdaptiveCropHandoff();
	const auto currentCrop = adaptiveCropController.ActiveCoverage();
	const auto currentRenderCrop = adaptiveCropController.RenderCoverage();
	if (adaptiveCropController.IsRuntimeActive() && previousCrop != currentCrop) {
		logger::info("[DLSSNR] adaptive crop scale decision {}% -> {}% of selected crop render={} -> {}% alpha={:.2f} frame={}",
			previousCrop, currentCrop, previousRenderCrop, currentRenderCrop,
			adaptiveCropController.HandoffAlpha(), frame);
		if (currentCrop < previousCrop)
			adaptiveNextDownshiftIsCrop = false;
	}
	if (adaptiveCropController.IsRuntimeActive() && previousRenderCrop != currentRenderCrop) {
		FoveatedRenderImpl::Core::InvalidateTemporalState();
		logger::info("[DLSSNR] adaptive crop geometry commit {}% -> {}% of selected crop frame={}",
			previousRenderCrop, currentRenderCrop, frame);
	}
	if (!cropPolicyAvailable)
		adaptiveNextDownshiftIsCrop = true;

	static std::uint32_t lastBudgetLog = UINT32_MAX;
	if (frame % 300 == 0 && frame != lastBudgetLog) {
		lastBudgetLog = frame;
		logger::info("[DLSSNR][BUDGET] frame={} source=steamvr-workload fresh={} work={:.2f} fast={:.2f} slow={:.2f} deadline={:.2f} passes={}/{} passCost={:.2f} pressure={} headroom={} nr={} cropScale={} gaze={} nrTransition={} cropTransition={} gpu={:.2f} submit={:.2f}",
			frame, workloadMs > 0.0f, workloadMs, adaptiveFastWorkloadMs, adaptiveSlowWorkloadMs,
			deadlineMs, adaptiveActivePasses, adaptiveConfiguredPasses, passCostMs,
			adaptiveController.LastSampleOverBudget(), adaptiveController.LastSampleHadHeadroom(),
			currentNR, currentCrop, eyeTrackingOwnsCrop, adaptiveController.IsTransitioning(),
			adaptiveCropController.IsTransitioning(), gpuWorkMs, activeSubmitMs);
	}

	if (adaptiveCropController.LastResetReason() != NeuralRendering::AdaptiveCropController::ResetReason::None &&
		adaptiveCropDiagnosticGeneration != adaptiveCropController.Generation()) {
		adaptiveCropDiagnosticGeneration = adaptiveCropController.Generation();
		logger::info("[DLSSNR][ADAPTIVE] crop generation={} reset={} geometry={} gaze={} scale={}% target={}% prevTarget={}% passes={}/{} nr={} prevNRTarget={}",
			adaptiveCropController.Generation(),
			NeuralRendering::AdaptiveCropController::ResetReasonName(adaptiveCropController.LastResetReason()),
			geometryCompatible, eyeTrackingOwnsCrop, currentCrop, adaptiveCropController.TargetCoverage(),
			previousCropTarget, adaptiveActivePasses, adaptiveConfiguredPasses, currentNR, previousNRTarget);
	}
}
'@
Replace-RegexOnce $foveated $updatePattern $updateReplacement

Write-Host 'v03 controller: adaptive pass count owns sequential stage count'
$multiPassAnchor = 'tuning.adaptiveSecondPassCostMs = settings.neuralRenderingAdaptiveSecondPassCostMs;'
$multiPassInsert = @'
tuning.adaptiveSecondPassCostMs = settings.neuralRenderingAdaptiveSecondPassCostMs;
			if (adaptive)
				tuning.multiPass = foveated.adaptiveActivePasses > 1 ? std::min(foveated.adaptiveActivePasses - 1u, 1u) : 0u;
'@
Replace-ExactOnce $integration $multiPassAnchor $multiPassInsert

Write-Host 'v03 controller: permit true zero-NR state without disturbing DLSS output'
$bypassOld = @'
		foveated.UpdateAdaptiveState(frame, true);

		auto* renderer = globals::game::renderer;
'@
$bypassNew = @'
		foveated.UpdateAdaptiveState(frame, true);
		if (foveated.settings.neuralRenderingAdaptiveEnabled && foveated.adaptiveController.IsEnabled() &&
			foveated.adaptiveActivePasses == 0) {
			// Zero-pass edge case: leave the already completed DLSS image untouched.
			// The controller keeps sampling SteamVR workload and only restores NR
			// after measured headroom can pay the configured pass cost.
			lastAppliedFrame = frame;
			return false;
		}

		auto* renderer = globals::game::renderer;
'@
Replace-ExactOnce $integration $bypassOld $bypassNew

Write-Host 'v03 controller: expose pass-cost model and active pass count in UI'
Replace-ExactOnce $foveated 'ImGui::Checkbox("Enable adaptive NR resolution", &settings.neuralRenderingAdaptiveEnabled);' 'ImGui::Checkbox("Enable adaptive performance controller", &settings.neuralRenderingAdaptiveEnabled);'
Replace-ExactOnce $foveated 'drawWrapped("Adjusts one NR tier after sustained pressure. Handoffs are blended.");' 'drawWrapped("Frametime controller for NR pass count, model tier and crop size. Degrades quickly under sustained pressure, restores slowly, and predicts discrete pass cost before adding a pass.");'
$headroomOld = @'
					ImGui::SliderFloat("Adaptive reserved headroom", &settings.neuralRenderingAdaptiveGuardTimeMs,
						0.0f, 5.0f, "%.1f ms");
'@
$headroomNew = @'
					ImGui::SliderFloat("Adaptive reserved headroom", &settings.neuralRenderingAdaptiveGuardTimeMs,
						0.0f, 5.0f, "%.1f ms");
					ImGui::SliderFloat("Estimated DLSS5 NR pass cost", &settings.neuralRenderingAdaptiveSecondPassCostMs,
						1.0f, 12.0f, "%.1f ms");
					if (auto _tt = Util::HoverTooltipWrapper())
						drawWrapped("Used for 2→1→0 and 0→1→2 decisions. Set this near the measured cost of one Feature18 pass; about 5-6 ms is a typical starting point for this build/test setup.");
'@
Replace-ExactOnce $foveated $headroomOld $headroomNew

$statusPattern = '(?s)\t\t\t\t\tImGui::TextDisabled\("Target %.0f FPS \| NR tier %u%% -> %u%% \| frame %.2f / %.2f ms",.*?adaptiveController\.ApplicationDeadlineMs\(\)\);'
$statusReplacement = @'
					ImGui::TextDisabled("Target %.0f FPS | passes %u/%u | NR %u%% -> %u%% | slow %.2f / %.2f ms",
						adaptiveController.ApplicationTargetFps(), adaptiveActivePasses, adaptiveConfiguredPasses,
						adaptiveController.ActiveResolution(), adaptiveController.TargetResolution(),
						adaptiveController.SmoothedFrameTimeMs(), adaptiveController.ApplicationDeadlineMs());
'@
Replace-RegexOnce $foveated $statusPattern $statusReplacement

Write-Host 'v03 smart-controller verification'
$h = Read-Normalized $header
$f = Read-Normalized $foveated
$ac = Read-Normalized $adaptiveCpp
$i = Read-Normalized $integration
if ($h -notmatch 'adaptiveActivePasses') { throw 'Adaptive pass state missing' }
if ($f -notmatch 'passWouldFit' -or $f -notmatch 'dropLastPass') { throw 'Pass controller policy missing' }
if ($f -notmatch 'Estimated DLSS5 NR pass cost') { throw 'Pass-cost UI missing' }
if ($ac -notmatch 'fastFrameTimeMs_' -or $ac -notmatch 'slowFrameTimeMs_') { throw 'Robust dual-timescale timing filter missing' }
if ($i -notmatch 'adaptiveActivePasses == 0') { throw 'Zero-pass bypass missing' }
if ($i -notmatch 'tuning\.multiPass = foveated\.adaptiveActivePasses') { throw 'Adaptive pass count not wired to renderer tuning' }
if ($i -match 'limited to Full Eye') { throw 'Stale full-eye-only sequential restriction remains in generated integration' }

Write-Host 'v03 pass-aware frametime controller applied successfully.'
