$ErrorActionPreference = 'Stop'

function Replace-Exact {
    param([string]$Path,[string]$Old,[string]$New)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected exactly one source block in $Path, found $count" }
    [IO.File]::WriteAllText($resolved, $text.Replace($Old,$New), [Text.UTF8Encoding]::new($false))
}

$renderer = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Renderer.cpp'

# Per-eye resetPending deliberately remains true while atlas owns native history,
# but that stale-normal-stereo flag must not reset the atlas handle every frame.
$old = @'
			const bool reset = stereoAtlasResetPending || resetPending[0][tierIndex] || resetPending[1][tierIndex] ||
				(temporalSkippedSinceFull && tuning.temporalReuseResetAfterSkip);
'@
$new = @'
			const bool enteringAtlas = !stereoAtlasActiveLastFrame;
			const bool reset = stereoAtlasResetPending ||
				(enteringAtlas && (resetPending[0][tierIndex] || resetPending[1][tierIndex])) ||
				(temporalSkippedSinceFull && tuning.temporalReuseResetAfterSkip);
'@
Replace-Exact $renderer $old $new

# A failed native atlas evaluation has been submitted through D3D12. Retire its
# handle only after the interop queue is idle; otherwise leave it for the next
# safe reset rather than freeing a possibly in-flight native object.
$old = @'
			if (!EvaluateStereoAtlasPass(tierIndex, 0, modelWidth, modelHeight, guideWidth, guideHeight,
				colorGuard, guideGuard, motionScaleX, motionScaleY, tuning, reset)) {
			Runtime::Instance().ResetFeature(AtlasFeatureSlot(tierIndex, 0));
			stereoAtlasResetPending = true;
			return StereoAtlasResult::FallBack;
			}
'@
$new = @'
			if (!EvaluateStereoAtlasPass(tierIndex, 0, modelWidth, modelHeight, guideWidth, guideHeight,
				colorGuard, guideGuard, motionScaleX, motionScaleY, tuning, reset)) {
				if (interop.WaitForIdle())
					Runtime::Instance().ResetFeature(AtlasFeatureSlot(tierIndex, 0));
				stereoAtlasResetPending = true;
				return StereoAtlasResult::FallBack;
			}
'@
Replace-Exact $renderer $old $new

$old = @'
				if (!EvaluateStereoAtlasPass(tierIndex, 1, pass2Width, pass2Height, pass2GuideWidth, pass2GuideHeight,
					pass2ColorGuard, pass2GuideGuard, motionScaleX, motionScaleY, tuning, reset)) {
					Runtime::Instance().ResetFeature(AtlasFeatureSlot(tierIndex, 1));
					stereoAtlasResetPending = true;
					return StereoAtlasResult::FallBack;
				}
'@
$new = @'
				if (!EvaluateStereoAtlasPass(tierIndex, 1, pass2Width, pass2Height, pass2GuideWidth, pass2GuideHeight,
					pass2ColorGuard, pass2GuideGuard, motionScaleX, motionScaleY, tuning, reset)) {
					if (interop.WaitForIdle())
						Runtime::Instance().ResetFeature(AtlasFeatureSlot(tierIndex, 1));
					stereoAtlasResetPending = true;
					return StereoAtlasResult::FallBack;
				}
'@
Replace-Exact $renderer $old $new

# The normal per-eye handles did not evaluate on an atlas frame. Keep their
# reset flag armed so toggling atlas off or falling back cannot revive stale
# independent-eye temporal histories. Atlas history uses its own flag above.
$old = @'
				resetPending[eyeIndex][tierIndex] = false;
			}
			if (temporalTierSupported) {
'@
$new = @'
				resetPending[eyeIndex][tierIndex] = nativeEvaluationDone;
			}
			if (temporalTierSupported) {
'@
Replace-Exact $renderer $old $new

Write-Host 'v01 atlas temporal/fallback safety applied successfully.'
