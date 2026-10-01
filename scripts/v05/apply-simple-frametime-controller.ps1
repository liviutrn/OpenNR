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
$cropHeader = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/AdaptiveCropController.h'
$cropCpp = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/AdaptiveCropController.cpp'

Write-Host 'v05: add explicit simple-controller settings'
$settingsAnchor = "`t`tfloat neuralRenderingAdaptiveGuardTimeMs = 1.0f;"
$settingsReplacement = @'
		float neuralRenderingAdaptiveGuardTimeMs = 1.0f;
		// v05 KISS controller. All four thresholds are direct SteamVR application
		// GPU frametime values and are user-configurable in the 10-30 ms range.
		float neuralRenderingAdaptivePassIncreaseBelowMs = 14.0f;
		float neuralRenderingAdaptiveCropIncreaseBelowMs = 16.0f;
		float neuralRenderingAdaptiveCropDecreaseAboveMs = 18.0f;
		float neuralRenderingAdaptivePassDecreaseAboveMs = 20.0f;
		float neuralRenderingAdaptiveSmoothingMs = 250.0f;
		float neuralRenderingAdaptiveDecreaseHoldMs = 350.0f;
		float neuralRenderingAdaptiveIncreaseHoldMs = 1200.0f;
		float neuralRenderingAdaptiveCooldownMs = 1000.0f;
'@
Replace-ExactOnce $header $settingsAnchor $settingsReplacement

$macroPattern = '(?m)^(?<indent>[ \t]*)X\(neuralRenderingAdaptiveGuardTimeMs\) \\$'
$macroReplacement = @'
${indent}X(neuralRenderingAdaptiveGuardTimeMs) \
${indent}X(neuralRenderingAdaptivePassIncreaseBelowMs) \
${indent}X(neuralRenderingAdaptiveCropIncreaseBelowMs) \
${indent}X(neuralRenderingAdaptiveCropDecreaseAboveMs) \
${indent}X(neuralRenderingAdaptivePassDecreaseAboveMs) \
${indent}X(neuralRenderingAdaptiveSmoothingMs) \
${indent}X(neuralRenderingAdaptiveDecreaseHoldMs) \
${indent}X(neuralRenderingAdaptiveIncreaseHoldMs) \
${indent}X(neuralRenderingAdaptiveCooldownMs) \
'@
Replace-RegexOnce $foveated $macroPattern $macroReplacement

Write-Host 'v05: simplify runtime state'
$statePattern = '(?ms)^(?<indent>[ \t]*)float adaptiveFastWorkloadMs = 0\.0f;\n[ \t]*float adaptiveSlowWorkloadMs = 0\.0f;.*?^[ \t]*bool adaptiveGpuLimited = true;\n'
$stateReplacement = @'
${indent}// v05 simple frametime controller state. The controller changes only pass
${indent}// count and crop scale; model resolution remains exactly user-selected.
${indent}std::uint32_t adaptiveCropTargetCoverage = 100;
${indent}float adaptiveFilteredFrameTimeMs = 0.0f;
${indent}float adaptiveLastFrameTimeMs = 0.0f;
${indent}float adaptiveDecreaseHoldMs = 0.0f;
${indent}float adaptiveIncreaseHoldMs = 0.0f;
${indent}float adaptiveCooldownRemainingMs = 0.0f;
${indent}std::uint32_t adaptivePendingAction = 0;
${indent}std::uint32_t adaptiveLastAction = 0;
${indent}std::uint32_t adaptiveLastActionFrom = 0;
${indent}std::uint32_t adaptiveLastActionTo = 0;
${indent}float adaptiveLastActionFrameTimeMs = 0.0f;
'@
Replace-RegexOnce $header $statePattern $stateReplacement

Write-Host 'v05: constrain adaptive crop to the approved relative tiers 100/80/60'
$bucketAccessorPattern = 'static constexpr const std::array<std::uint32_t, 6>& CoverageBuckets\(\)'
Replace-RegexOnce $cropHeader $bucketAccessorPattern 'static constexpr const std::array<std::uint32_t, 3>& CoverageBuckets()'
$bucketPattern = 'static constexpr std::array<std::uint32_t, 6> kCoverageBuckets\{\s*100, 90, 80, 70, 60, 50 \};'
$bucketReplacement = @'
static constexpr std::array<std::uint32_t, 3> kCoverageBuckets{
			100, 80, 60 };
'@
Replace-RegexOnce $cropHeader $bucketPattern $bucketReplacement

$normalizePattern = 'normalized\.maximumCoverage = FindBucketAtOrBelow\(std::clamp\(normalized\.maximumCoverage, 50u, 100u\)\);\s*\n\s*normalized\.minimumCoverage = FindBucketAtOrBelow\(std::clamp\(normalized\.minimumCoverage, 50u, 100u\)\);'
$normalizeReplacement = @'
normalized.maximumCoverage = FindBucketAtOrBelow(std::clamp(normalized.maximumCoverage, 60u, 100u));
		normalized.minimumCoverage = FindBucketAtOrBelow(std::clamp(normalized.minimumCoverage, 60u, 100u));
'@
Replace-RegexOnce $cropCpp $normalizePattern $normalizeReplacement
Replace-ExactOnce $cropCpp 'normalized.upshiftFrames = std::clamp(normalized.upshiftFrames, 8u, 240u);' 'normalized.upshiftFrames = std::clamp(normalized.upshiftFrames, 1u, 240u);'
Replace-ExactOnce $cropCpp 'normalized.minimumDwellFrames = std::clamp(normalized.minimumDwellFrames, 8u, 600u);' 'normalized.minimumDwellFrames = std::clamp(normalized.minimumDwellFrames, 1u, 600u);'

Write-Host 'v05: clamp persisted controller values without silently reordering user thresholds'
$clampAnchor = "`tsettings.neuralRenderingAdaptiveGuardTimeMs = std::clamp(settings.neuralRenderingAdaptiveGuardTimeMs, 0.0f, 5.0f);"
$clampReplacement = @'
	settings.neuralRenderingAdaptiveGuardTimeMs = std::clamp(settings.neuralRenderingAdaptiveGuardTimeMs, 0.0f, 5.0f);
	settings.neuralRenderingAdaptivePassIncreaseBelowMs = clampFinite(settings.neuralRenderingAdaptivePassIncreaseBelowMs, 14.0f, 10.0f, 30.0f);
	settings.neuralRenderingAdaptiveCropIncreaseBelowMs = clampFinite(settings.neuralRenderingAdaptiveCropIncreaseBelowMs, 16.0f, 10.0f, 30.0f);
	settings.neuralRenderingAdaptiveCropDecreaseAboveMs = clampFinite(settings.neuralRenderingAdaptiveCropDecreaseAboveMs, 18.0f, 10.0f, 30.0f);
	settings.neuralRenderingAdaptivePassDecreaseAboveMs = clampFinite(settings.neuralRenderingAdaptivePassDecreaseAboveMs, 20.0f, 10.0f, 30.0f);
	settings.neuralRenderingAdaptiveSmoothingMs = clampFinite(settings.neuralRenderingAdaptiveSmoothingMs, 250.0f, 0.0f, 1000.0f);
	settings.neuralRenderingAdaptiveDecreaseHoldMs = clampFinite(settings.neuralRenderingAdaptiveDecreaseHoldMs, 350.0f, 0.0f, 2500.0f);
	settings.neuralRenderingAdaptiveIncreaseHoldMs = clampFinite(settings.neuralRenderingAdaptiveIncreaseHoldMs, 1200.0f, 0.0f, 5000.0f);
	settings.neuralRenderingAdaptiveCooldownMs = clampFinite(settings.neuralRenderingAdaptiveCooldownMs, 1000.0f, 0.0f, 5000.0f);
'@
Replace-ExactOnce $foveated $clampAnchor $clampReplacement

Write-Host 'v05: reset only the state owned by the simple controller'
$resetPattern = '(?ms)^void FoveatedRender::ResetAdaptiveState\(\)\n\{.*?^\}\n'
$resetReplacement = @'
void FoveatedRender::ResetAdaptiveState()
{
	const std::uint32_t manualPasses = std::clamp(settings.neuralRenderingMultiPass + 1u, 1u, 3u);
	const bool restoringPasses = adaptivePassInitialized && adaptiveActivePasses < manualPasses;
	const bool cropWasActive = adaptiveCropController.IsRuntimeActive();
	adaptiveController.Reset();
	adaptiveCropController.Reset();
	adaptiveNextDownshiftIsCrop = true;
	adaptiveCropDiagnosticGeneration = UINT64_MAX;
	adaptiveConfiguredPasses = manualPasses;
	adaptiveActivePasses = manualPasses;
	adaptivePassDwellFrames = 0;
	adaptivePassPressureFrames = 0;
	adaptivePassHeadroomFrames = 0;
	adaptivePassInitialized = false;
	adaptiveCropTargetCoverage = 100;
	adaptiveFilteredFrameTimeMs = 0.0f;
	adaptiveLastFrameTimeMs = 0.0f;
	adaptiveDecreaseHoldMs = 0.0f;
	adaptiveIncreaseHoldMs = 0.0f;
	adaptiveCooldownRemainingMs = 0.0f;
	adaptivePendingAction = 0;
	adaptiveLastAction = 0;
	adaptiveLastActionFrom = 0;
	adaptiveLastActionTo = 0;
	adaptiveLastActionFrameTimeMs = 0.0f;
	if (cropWasActive)
		FoveatedRenderImpl::Core::ResetAdaptiveCropHandoff();
	if (restoringPasses)
		NeuralRendering::ResetHistory();
}
'@
Replace-RegexOnce $foveated $resetPattern $resetReplacement

Write-Host 'v05: replace v04 policy with crop-first manual-threshold controller'
$updatePattern = '(?ms)^void FoveatedRender::UpdateAdaptiveState\(std::uint32_t frame, bool routeEligible\)\n\{.*?^\}\n'
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
	// Adaptive mode is intentionally 0/1/2 passes. Manual 3x remains available
	// when the controller is disabled. This also matches the stereo-atlas stage cap.
	const std::uint32_t requestedPasses = std::min(manualPasses, 2u);

	if (!settings.neuralRenderingAdaptiveEnabled || !nrEligible) {
		if (adaptivePassInitialized || adaptiveCropController.IsRuntimeActive())
			ResetAdaptiveState();
		adaptiveConfiguredPasses = manualPasses;
		adaptiveActivePasses = manualPasses;
		return;
	}

	const auto leftUV = subrectController.GetUV();
	const auto rightUV = subrectController.GetRightEyeUV();
	const bool geometryCompatible = leftUV.w > 0.01f && leftUV.h > 0.01f &&
		rightUV.w > 0.01f && rightUV.h > 0.01f &&
		std::abs(leftUV.w - rightUV.w) <= 0.0005f &&
		std::abs(leftUV.h - rightUV.h) <= 0.0005f;
	const bool eyeTrackingOwnsOrigin = IsEyeTrackedFoveationEnabled();
	const bool cropPolicyAvailable = geometryCompatible;

	if (!adaptivePassInitialized) {
		adaptivePassInitialized = true;
		adaptiveConfiguredPasses = requestedPasses;
		adaptiveActivePasses = requestedPasses;
		adaptiveCropTargetCoverage = 100;
		adaptiveFilteredFrameTimeMs = 0.0f;
		adaptiveLastFrameTimeMs = 0.0f;
		adaptiveDecreaseHoldMs = 0.0f;
		adaptiveIncreaseHoldMs = 0.0f;
		adaptiveCooldownRemainingMs = 0.0f;
		adaptivePendingAction = 0;
	}
	if (requestedPasses != adaptiveConfiguredPasses) {
		const auto oldConfigured = adaptiveConfiguredPasses;
		adaptiveConfiguredPasses = requestedPasses;
		adaptiveActivePasses = std::min(adaptiveActivePasses, adaptiveConfiguredPasses);
		adaptiveDecreaseHoldMs = 0.0f;
		adaptiveIncreaseHoldMs = 0.0f;
		adaptiveCooldownRemainingMs = 0.0f;
		logger::info("[DLSSNR][ADAPTIVE-v05] configured pass ceiling {} -> {} active={}",
			oldConfigured, adaptiveConfiguredPasses, adaptiveActivePasses);
	}

	if (!cropPolicyAvailable)
		adaptiveCropTargetCoverage = 100;
	else if (adaptiveCropTargetCoverage >= 90)
		adaptiveCropTargetCoverage = 100;
	else if (adaptiveCropTargetCoverage >= 70)
		adaptiveCropTargetCoverage = 80;
	else
		adaptiveCropTargetCoverage = 60;

	float gpuFrameTimeMs = -1.0f;
	float sampleDeltaMs = 11.1f;
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
				if (std::isfinite(gpuMs) && gpuMs > 0.0f) {
					gpuFrameTimeMs = gpuMs;
					freshTiming = true;
				}
				if (std::isfinite(timing.m_flClientFrameIntervalMs) && timing.m_flClientFrameIntervalMs > 0.0f)
					sampleDeltaMs = std::clamp(timing.m_flClientFrameIntervalMs, 1.0f, 100.0f);
			}
		}
	}

	bool qualityChanged = false;
	if (freshTiming) {
		adaptiveLastFrameTimeMs = gpuFrameTimeMs;
		// A single loading hitch must not dominate the EMA for seconds. The 60 ms
		// filter cap is still far above the highest configurable 30 ms threshold,
		// so sustained severe load continues to downshift normally.
		const float filterSampleMs = std::min(gpuFrameTimeMs, 60.0f);
		const float smoothingMs = std::clamp(settings.neuralRenderingAdaptiveSmoothingMs, 0.0f, 1000.0f);
		if (adaptiveFilteredFrameTimeMs <= 0.0f || smoothingMs <= 1.0f) {
			adaptiveFilteredFrameTimeMs = filterSampleMs;
		} else {
			const float alpha = std::clamp(1.0f - std::exp(-sampleDeltaMs / smoothingMs), 0.001f, 1.0f);
			adaptiveFilteredFrameTimeMs += (filterSampleMs - adaptiveFilteredFrameTimeMs) * alpha;
		}

		if (adaptiveCooldownRemainingMs > 0.0f) {
			adaptiveCooldownRemainingMs = std::max(0.0f, adaptiveCooldownRemainingMs - sampleDeltaMs);
			adaptiveDecreaseHoldMs = 0.0f;
			adaptiveIncreaseHoldMs = 0.0f;
			adaptivePendingAction = 0;
		} else {
			const bool cropTransitioning = adaptiveCropController.IsTransitioning();
			const std::uint32_t renderCrop = adaptiveCropController.IsRuntimeActive() ?
				adaptiveCropController.RenderCoverage() : 100u;
			const bool cropCanShrink = cropPolicyAvailable && !cropTransitioning &&
				adaptiveCropTargetCoverage > 60;
			const bool cropCanGrow = cropPolicyAvailable && !cropTransitioning &&
				adaptiveCropTargetCoverage < 100;
			const bool cropAtFloor = !cropPolicyAvailable ||
				(!cropTransitioning && adaptiveCropTargetCoverage <= 60 && renderCrop <= 60);
			const bool cropAtCeiling = !cropPolicyAvailable ||
				(!cropTransitioning && adaptiveCropTargetCoverage >= 100 && renderCrop >= 100);

			// Action codes: 1=crop down, 2=crop up, 3=pass down, 4=pass up.
			// Crop always has priority. Passes are touched only after crop has reached
			// its relevant end of the 100/80/60 ladder (or crop is unavailable).
			adaptivePendingAction = 0;
			if (cropCanShrink && adaptiveFilteredFrameTimeMs > settings.neuralRenderingAdaptiveCropDecreaseAboveMs)
				adaptivePendingAction = 1;
			else if (cropAtFloor && adaptiveActivePasses > 0 &&
				adaptiveFilteredFrameTimeMs > settings.neuralRenderingAdaptivePassDecreaseAboveMs)
				adaptivePendingAction = 3;
			else if (cropCanGrow && adaptiveFilteredFrameTimeMs < settings.neuralRenderingAdaptiveCropIncreaseBelowMs)
				adaptivePendingAction = 2;
			else if (cropAtCeiling && adaptiveActivePasses < adaptiveConfiguredPasses &&
				adaptiveFilteredFrameTimeMs < settings.neuralRenderingAdaptivePassIncreaseBelowMs)
				adaptivePendingAction = 4;

			const bool decreasing = adaptivePendingAction == 1 || adaptivePendingAction == 3;
			const bool increasing = adaptivePendingAction == 2 || adaptivePendingAction == 4;
			if (decreasing) {
				adaptiveDecreaseHoldMs += sampleDeltaMs;
				adaptiveIncreaseHoldMs = 0.0f;
			} else if (increasing) {
				adaptiveIncreaseHoldMs += sampleDeltaMs;
				adaptiveDecreaseHoldMs = 0.0f;
			} else {
				adaptiveDecreaseHoldMs = 0.0f;
				adaptiveIncreaseHoldMs = 0.0f;
			}

			const bool actionReady = decreasing ?
				adaptiveDecreaseHoldMs >= settings.neuralRenderingAdaptiveDecreaseHoldMs :
				(increasing && adaptiveIncreaseHoldMs >= settings.neuralRenderingAdaptiveIncreaseHoldMs);
			if (adaptivePendingAction != 0 && actionReady) {
				adaptiveLastAction = adaptivePendingAction;
				adaptiveLastActionFrameTimeMs = adaptiveFilteredFrameTimeMs;
				switch (adaptivePendingAction) {
				case 1:
					adaptiveLastActionFrom = adaptiveCropTargetCoverage;
					adaptiveCropTargetCoverage = adaptiveCropTargetCoverage > 80 ? 80u : 60u;
					adaptiveLastActionTo = adaptiveCropTargetCoverage;
					qualityChanged = true;
					break;
				case 2:
					adaptiveLastActionFrom = adaptiveCropTargetCoverage;
					adaptiveCropTargetCoverage = adaptiveCropTargetCoverage < 80 ? 80u : 100u;
					adaptiveLastActionTo = adaptiveCropTargetCoverage;
					qualityChanged = true;
					break;
				case 3:
					adaptiveLastActionFrom = adaptiveActivePasses;
					--adaptiveActivePasses;
					adaptiveLastActionTo = adaptiveActivePasses;
					qualityChanged = true;
					break;
				case 4:
					adaptiveLastActionFrom = adaptiveActivePasses;
					++adaptiveActivePasses;
					adaptiveLastActionTo = adaptiveActivePasses;
					// A restored stage must not resume a dormant temporal history.
					NeuralRendering::ResetHistory();
					qualityChanged = true;
					break;
				default:
					break;
				}
				if (qualityChanged) {
					adaptiveCooldownRemainingMs = settings.neuralRenderingAdaptiveCooldownMs;
					adaptiveDecreaseHoldMs = 0.0f;
					adaptiveIncreaseHoldMs = 0.0f;
					adaptivePendingAction = 0;
				}
			}
		}
	}

	NeuralRendering::AdaptiveCropController::Config cropConfig;
	cropConfig.enabled = cropPolicyAvailable;
	cropConfig.hold = false;
	cropConfig.maximumCoverage = 100;
	cropConfig.minimumCoverage = 60;
	// v05 owns smoothing, hysteresis, holds and cooldown. The crop controller is
	// only a stereo-safe actuator/handoff mechanism, so its own decision delays
	// are one frame and cannot create a hidden second policy.
	cropConfig.downshiftFrames = 1;
	cropConfig.upshiftFrames = 1;
	cropConfig.minimumDwellFrames = 1;
	cropConfig.transitionFrames = settings.neuralRenderingAdaptiveCropTransitionFrames;
	const bool cropWasActive = adaptiveCropController.IsRuntimeActive();
	const std::uint32_t previousRenderCrop = cropWasActive ? adaptiveCropController.RenderCoverage() : 100u;
	const std::uint32_t currentCrop = cropWasActive ? adaptiveCropController.ActiveCoverage() : 100u;
	const bool driveCropDown = cropPolicyAvailable && currentCrop > adaptiveCropTargetCoverage;
	const bool driveCropUp = cropPolicyAvailable && currentCrop < adaptiveCropTargetCoverage;
	// Eye/gaze tracking keeps ownership of crop origin. Adaptive v05 changes only
	// scale relative to that live user-selected crop, exactly as v03 established.
	adaptiveCropController.Update(frame, cropConfig, cropPolicyAvailable,
		100, geometryCompatible, false, driveCropDown, false, true,
		driveCropDown, driveCropUp);
	if (cropWasActive && !adaptiveCropController.IsRuntimeActive())
		FoveatedRenderImpl::Core::ResetAdaptiveCropHandoff();
	const std::uint32_t committedRenderCrop = adaptiveCropController.IsRuntimeActive() ?
		adaptiveCropController.RenderCoverage() : 100u;
	if (adaptiveCropController.IsRuntimeActive() && previousRenderCrop != committedRenderCrop) {
		// Invalidate once when a 100/80/60 geometry handoff commits. Gaze motion at
		// a stable tier does not hit this path, so the v03 gaze-history fix remains.
		FoveatedRenderImpl::Core::InvalidateTemporalState();
		logger::info("[DLSSNR][ADAPTIVE-v05] crop geometry commit {}% -> {}% of selected crop frame={}",
			previousRenderCrop, committedRenderCrop, frame);
	}

	if (qualityChanged) {
		const char* action = adaptiveLastAction == 1 ? "crop-down" :
			adaptiveLastAction == 2 ? "crop-up" :
			adaptiveLastAction == 3 ? "pass-down" : "pass-up";
		logger::info("[DLSSNR][ADAPTIVE-v05] action={} {} -> {} raw={:.2f}ms filtered={:.2f}ms passes={}/{} cropTarget={} atlas={} gaze={}",
			action, adaptiveLastActionFrom, adaptiveLastActionTo,
			adaptiveLastFrameTimeMs, adaptiveFilteredFrameTimeMs,
			adaptiveActivePasses, adaptiveConfiguredPasses, adaptiveCropTargetCoverage,
			settings.neuralRenderingStereoAtlas, eyeTrackingOwnsOrigin);
	}

	static std::uint32_t lastBudgetLog = UINT32_MAX;
	if (frame % 300 == 0 && frame != lastBudgetLog) {
		lastBudgetLog = frame;
		logger::info("[DLSSNR][BUDGET-v05] frame={} fresh={} raw={:.2f} filtered={:.2f} passes={}/{} cropRender={} cropTarget={} decHold={:.0f} incHold={:.0f} cooldown={:.0f} atlas={} gaze={}",
			frame, freshTiming, adaptiveLastFrameTimeMs, adaptiveFilteredFrameTimeMs,
			adaptiveActivePasses, adaptiveConfiguredPasses,
			adaptiveCropController.IsRuntimeActive() ? adaptiveCropController.RenderCoverage() : 100u,
			adaptiveCropTargetCoverage, adaptiveDecreaseHoldMs, adaptiveIncreaseHoldMs,
			adaptiveCooldownRemainingMs, settings.neuralRenderingStereoAtlas, eyeTrackingOwnsOrigin);
	}
}
'@
Replace-RegexOnce $foveated $updatePattern $updateReplacement

Write-Host 'v05: replace old adaptive UI with direct manual thresholds and authoritative live state'
$uiPattern = '(?s)\t\t\tif \(NeuralRendering::kFullResolutionNeuralRenderingOnly\) \{.*?\n\s*ImGui::SeparatorText\("Resolve and Pipeline"\);'
$uiReplacement = @'
			if (!NeuralRendering::kFullResolutionNeuralRenderingOnly && ImGui::CollapsingHeader("Adaptive Performance")) {
				ImGui::SeparatorText("Simple Frametime Controller");
				ImGui::Checkbox("Enable adaptive performance controller", &settings.neuralRenderingAdaptiveEnabled);
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped("Direct SteamVR GPU-frametime thresholds only. Crop has priority: 100% -> 80% -> 60% of your selected crop before pass count is reduced. Recovery also restores crop first, then passes.");
				if (settings.neuralRenderingAdaptiveEnabled) {
					ImGui::SliderFloat("Pass +1 below", &settings.neuralRenderingAdaptivePassIncreaseBelowMs, 10.0f, 30.0f, "%.1f ms");
					ImGui::SliderFloat("Crop +1 tier below", &settings.neuralRenderingAdaptiveCropIncreaseBelowMs, 10.0f, 30.0f, "%.1f ms");
					ImGui::SliderFloat("Crop -1 tier above", &settings.neuralRenderingAdaptiveCropDecreaseAboveMs, 10.0f, 30.0f, "%.1f ms");
					ImGui::SliderFloat("Pass -1 above", &settings.neuralRenderingAdaptivePassDecreaseAboveMs, 10.0f, 30.0f, "%.1f ms");
					const bool orderedThresholds = settings.neuralRenderingAdaptivePassIncreaseBelowMs < settings.neuralRenderingAdaptiveCropIncreaseBelowMs &&
						settings.neuralRenderingAdaptiveCropIncreaseBelowMs < settings.neuralRenderingAdaptiveCropDecreaseAboveMs &&
						settings.neuralRenderingAdaptiveCropDecreaseAboveMs < settings.neuralRenderingAdaptivePassDecreaseAboveMs;
					if (!orderedThresholds)
						drawWarningWrapped("Thresholds overlap. Recommended hysteresis order: Pass + < Crop + < Crop - < Pass -. Values are kept exactly as configured; the controller does not silently rewrite them.");
					ImGui::SliderFloat("Frametime smoothing", &settings.neuralRenderingAdaptiveSmoothingMs, 0.0f, 1000.0f, "%.0f ms");
					ImGui::SliderFloat("Decrease hold", &settings.neuralRenderingAdaptiveDecreaseHoldMs, 0.0f, 2500.0f, "%.0f ms");
					ImGui::SliderFloat("Increase hold", &settings.neuralRenderingAdaptiveIncreaseHoldMs, 0.0f, 5000.0f, "%.0f ms");
					ImGui::SliderFloat("Cooldown after change", &settings.neuralRenderingAdaptiveCooldownMs, 0.0f, 5000.0f, "%.0f ms");

					const auto selectedCrop = subrectController.GetUV();
					const float selectedCropPercent = std::clamp(std::min(selectedCrop.w, selectedCrop.h) * 100.0f, 0.0f, 100.0f);
					const std::uint32_t renderCropScale = adaptiveCropController.IsRuntimeActive() ? adaptiveCropController.RenderCoverage() : 100u;
					const float effectiveCropPercent = selectedCropPercent * static_cast<float>(renderCropScale) / 100.0f;
					ImGui::TextDisabled("Frametime: raw %.2f ms | filtered %.2f ms",
						adaptiveLastFrameTimeMs, adaptiveFilteredFrameTimeMs);
					ImGui::TextDisabled("NR passes: %u / %u", adaptiveActivePasses, adaptiveConfiguredPasses);
					ImGui::TextDisabled("Crop: %u%% render | %u%% target of selected crop | selected %.1f%% | effective %.1f%%",
						renderCropScale, adaptiveCropTargetCoverage, selectedCropPercent, effectiveCropPercent);
					const char* controllerState = adaptiveFilteredFrameTimeMs <= 0.0f ? "Waiting for SteamVR timing" :
						adaptiveCooldownRemainingMs > 0.0f ? "Cooldown" :
						adaptiveDecreaseHoldMs > 0.0f ? "Decrease hold" :
						adaptiveIncreaseHoldMs > 0.0f ? "Increase hold" : "Holding";
					ImGui::TextDisabled("State: %s | decrease %.0f/%.0f ms | increase %.0f/%.0f ms | cooldown %.0f ms",
						controllerState, adaptiveDecreaseHoldMs, settings.neuralRenderingAdaptiveDecreaseHoldMs,
						adaptiveIncreaseHoldMs, settings.neuralRenderingAdaptiveIncreaseHoldMs,
						adaptiveCooldownRemainingMs);
					if (adaptiveLastAction != 0) {
						if (adaptiveLastAction <= 2)
							ImGui::TextDisabled("Last action: crop %u%% -> %u%% at %.2f ms",
								adaptiveLastActionFrom, adaptiveLastActionTo, adaptiveLastActionFrameTimeMs);
						else
							ImGui::TextDisabled("Last action: passes %u -> %u at %.2f ms",
								adaptiveLastActionFrom, adaptiveLastActionTo, adaptiveLastActionFrameTimeMs);
					}
					drawDisabledWrapped("Crop tiers are always 100%, 80%, and 60% of your selected crop. Example: Center 60% becomes 60% -> 48% -> 36%.");
				}
			}

				ImGui::SeparatorText("Resolve and Pipeline");
'@
Replace-RegexOnce $foveated $uiPattern $uiReplacement

# The old adaptive NR object is no longer the source of truth. Keep dependent UI
# logic keyed to the v05 controller state so unrelated temporal options do not
# accidentally behave as if adaptive control were disabled.
Replace-ExactOnce $foveated 'const bool adaptiveNR = settings.neuralRenderingAdaptiveEnabled && adaptiveController.IsEnabled();' 'const bool adaptiveNR = settings.neuralRenderingAdaptiveEnabled && adaptivePassInitialized;'

Write-Host 'v05 generated-source verification'
$h = Read-Normalized $header
$f = Read-Normalized $foveated
$ch = Read-Normalized $cropHeader
$cc = Read-Normalized $cropCpp
if ($h -notmatch 'neuralRenderingAdaptivePassIncreaseBelowMs = 14\.0f') { throw 'v05 threshold settings missing' }
if ($h -notmatch 'adaptiveFilteredFrameTimeMs') { throw 'v05 live frametime state missing' }
if ($f -notmatch '\[DLSSNR\]\[ADAPTIVE-v05\]') { throw 'v05 controller body missing' }
if ($f -notmatch '\[DLSSNR\]\[BUDGET-v05\]') { throw 'v05 diagnostics missing' }
if ($f -match '\[DLSSNR\]\[ADAPTIVE-v04\]' -or $f -match '\[DLSSNR\]\[BUDGET-v04\]') { throw 'v04 decision controller survived v05 replacement' }
if ($f -match 'passCostMs' -or $f -match 'adaptiveFastWorkloadMs' -or $f -match 'adaptiveSlowWorkloadMs') { throw 'Predictive/dual-filter controller state survived v05' }
if ($f -match 'Estimated DLSS5 NR pass cost' -or $f -match 'Use custom FPS target' -or $f -match 'Headset refresh target') { throw 'Old automatic controller UI survived v05' }
if ($f -notmatch 'Pass \+1 below.*10\.0f, 30\.0f' -or $f -notmatch 'Pass -1 above.*10\.0f, 30\.0f') { throw '10-30 ms threshold UI range missing' }
if ($f -notmatch 'adaptiveCropTargetCoverage > 60' -or $f -notmatch 'adaptiveCropTargetCoverage < 100') { throw 'Crop-first tier gates missing' }
if ($f -notmatch '(?s)cropAtFloor.*adaptiveActivePasses > 0' -or $f -notmatch '(?s)cropAtCeiling.*adaptiveActivePasses < adaptiveConfiguredPasses') { throw 'Pass actions are not gated behind crop endpoints' }
if ($ch -notmatch 'std::array<std::uint32_t, 3> kCoverageBuckets' -or $ch -notmatch '100, 80, 60') { throw 'Approved 100/80/60 crop ladder missing' }
if ($ch -match '100, 90, 80, 70, 60, 50') { throw 'Old six-tier crop ladder survived' }
if ($cc -notmatch 'upshiftFrames, 1u, 240u' -or $cc -notmatch 'minimumDwellFrames, 1u, 600u') { throw 'Crop actuator still has hidden multi-frame decision delays' }
if ($f -notmatch 'base\.w \* scale' -or $f -notmatch 'base\.h \* scale') { throw 'Relative-to-user-crop scaling regressed' }
if ($f -notmatch 'adaptivePassInitialized') { throw 'v05 controller state not exposed to dependent UI' }
if ($f -notmatch 'restoringPasses' -or $f -notmatch 'NeuralRendering::ResetHistory\(\)') { throw 'Pass restoration history reset missing' }

Write-Host 'v05 simple crop-first frametime controller applied successfully.'
