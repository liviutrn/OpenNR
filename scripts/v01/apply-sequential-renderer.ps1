$ErrorActionPreference = 'Stop'

function Replace-Exact {
    param([string]$Path,[string]$Old,[string]$New)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected exactly one source block in $Path, found $count" }
    [IO.File]::WriteAllText($resolved, $text.Replace($Old,$New), [Text.UTF8Encoding]::new($false))
}

function Replace-RegexOnce {
    param([string]$Path,[string]$Pattern,[string]$Replacement)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $rx = [regex]::new($Pattern, [Text.RegularExpressions.RegexOptions]::Singleline)
    $matches = $rx.Matches($text)
    if ($matches.Count -ne 1) { throw "Expected exactly one regex source block in $Path, found $($matches.Count)" }
    [IO.File]::WriteAllText($resolved, $rx.Replace($text,$Replacement,1), [Text.UTF8Encoding]::new($false))
}

$renderer = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Renderer.cpp'

# A reduced pass 2 is a two-stage contract. Preserve legacy 3x only when pass 2
# covers 100%; otherwise stop at pass 2 rather than feeding pass 3 an incomplete image.
$old = @'
		std::uint32_t GetPassCount(const Tuning& tuning)
		{
			return tuning.multiPass == 0 ? 1 : std::min(tuning.multiPass + 1, kCascadePassCount);
		}
'@
$new = @'
		std::uint32_t GetPassCount(const Tuning& tuning)
		{
			if (tuning.multiPass == 0)
				return 1;
			const auto requested = std::min(tuning.multiPass + 1, kCascadePassCount);
			return tuning.secondPass.coveragePercent < 100 ? std::min(requested, 2u) : requested;
		}

		Tuning TuningForCascadePass(const Tuning& tuning, std::uint32_t passIndex)
		{
			if (passIndex != 1)
				return tuning;
			Tuning out = tuning;
			const auto& pass = tuning.secondPass;
			out.intensity = pass.intensity;
			out.localToneStrength = pass.localToneStrength;
			out.localStructureStrength = pass.localStructureStrength;
			out.skinStructureStrength = pass.skinStructureStrength;
			out.style = pass.style;
			out.useAutoMask = pass.useAutoMask;
			out.uiCorrection = pass.uiCorrection;
			// The current v01 stage keeps both sequential evaluations on the same
			// model-resolution tier. Independent pass-2 model resolution is wired in
			// settings but is applied in the later per-pass resolve stage.
			out.multiPass = 0;
			out.temporalReuseCadence = 0;
			out.temporalReuseStaggerEyes = false;
			return out;
		}
'@
Replace-Exact $renderer $old $new

# Add a compact pass-2 target. It is sized to the relative pass-2 region, not the
# full pass-1 crop, so 50% linear coverage allocates ~25% of pass-1 pixels.
$old = @'
		struct TierResources
		{
			SharedTexture modelInput;
			std::array<SharedTexture, kCascadePassCount - 1> cascadeIntermediates;
			SharedTexture output;
'@
$new = @'
		struct TierResources
		{
			SharedTexture modelInput;
			std::array<SharedTexture, kCascadePassCount - 1> cascadeIntermediates;
			SharedTexture secondPassOutput;
			SharedTexture output;
'@
Replace-Exact $renderer $old $new

# Extend tier-resource creation with the relative pass-2 coverage.
$old = @'
		bool EnsureTierResources(ID3D11Device* device, std::uint32_t eyeIndex, EyeResources& eye,
			std::uint32_t tierIndex, std::uint32_t modelWidth, std::uint32_t modelHeight,
			std::uint32_t passCount, std::uint32_t modelResolution,
			std::uint32_t resourceColorWidth, std::uint32_t resourceColorHeight)
'@
$new = @'
		bool EnsureTierResources(ID3D11Device* device, std::uint32_t eyeIndex, EyeResources& eye,
			std::uint32_t tierIndex, std::uint32_t modelWidth, std::uint32_t modelHeight,
			std::uint32_t passCount, std::uint32_t modelResolution, std::uint32_t secondPassCoverage,
			std::uint32_t resourceColorWidth, std::uint32_t resourceColorHeight)
'@
Replace-Exact $renderer $old $new

$old = @'
			const bool reducedResolution = modelResolution != 100;
			const bool multiPass = passCount > 1;
			const UINT sharedFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
			const auto resourceModelWidth = ScaleDimension(resourceColorWidth, modelResolution);
			const auto resourceModelHeight = ScaleDimension(resourceColorHeight, modelResolution);
			const auto modelInputDesc = MakeSharedDesc(eye.color.desc, resourceModelWidth, resourceModelHeight, sharedFlags);
			const auto outputDesc = MakeSharedDesc(eye.color.desc, resourceModelWidth, resourceModelHeight, sharedFlags);
			const auto resolvedDesc = MakeSharedDesc(eye.color.desc, resourceColorWidth, resourceColorHeight, sharedFlags);
'@
$new = @'
			const bool reducedResolution = modelResolution != 100;
			const bool multiPass = passCount > 1;
			const std::uint32_t pass2Coverage = multiPass ? std::clamp(secondPassCoverage, 50u, 100u) : 100u;
			const bool croppedSecondPass = multiPass && pass2Coverage < 100;
			const UINT sharedFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
			const auto resourceModelWidth = ScaleDimension(resourceColorWidth, modelResolution);
			const auto resourceModelHeight = ScaleDimension(resourceColorHeight, modelResolution);
			const auto pass2ResourceWidth = ScaleDimension(resourceModelWidth, pass2Coverage);
			const auto pass2ResourceHeight = ScaleDimension(resourceModelHeight, pass2Coverage);
			const auto modelInputDesc = MakeSharedDesc(eye.color.desc, resourceModelWidth, resourceModelHeight, sharedFlags);
			const auto outputDesc = MakeSharedDesc(eye.color.desc, resourceModelWidth, resourceModelHeight, sharedFlags);
			const auto pass2OutputDesc = MakeSharedDesc(eye.color.desc, pass2ResourceWidth, pass2ResourceHeight, sharedFlags);
			const auto resolvedDesc = MakeSharedDesc(eye.color.desc, resourceColorWidth, resourceColorHeight, sharedFlags);
'@
Replace-Exact $renderer $old $new

$old = @'
			const bool resourcesMatch = tier.modelResolution == modelResolution && tier.passCount == passCount &&
				tier.reducedResolution == reducedResolution &&
				(!reducedResolution || Matches(tier.modelInput, modelInputDesc)) &&
				Matches(tier.output, outputDesc) && intermediatesMatch &&
				(!reducedResolution || (MatchesResolved(tier.resolved, resolvedDesc) && tier.resolvedSRV && tier.resolvedUAV));
'@
$new = @'
			const bool resourcesMatch = tier.modelResolution == modelResolution && tier.passCount == passCount &&
				tier.reducedResolution == reducedResolution &&
				(!reducedResolution || Matches(tier.modelInput, modelInputDesc)) &&
				Matches(tier.output, outputDesc) && intermediatesMatch &&
				(!croppedSecondPass || Matches(tier.secondPassOutput, pass2OutputDesc)) &&
				(!reducedResolution || (MatchesResolved(tier.resolved, resolvedDesc) && tier.resolvedSRV && tier.resolvedUAV));
'@
Replace-Exact $renderer $old $new

$old = @'
			if (tier.output.resource11 || tier.modelInput.resource11 || tier.resolved) {
'@
$new = @'
			if (tier.output.resource11 || tier.secondPassOutput.resource11 || tier.modelInput.resource11 || tier.resolved) {
'@
Replace-Exact $renderer $old $new

$old = @'
			if ((reducedResolution && !interop.CreateSharedTexture(modelInputDesc, tier.modelInput,
				("NeuralRendering::ModelInput" + tierSuffix).c_str())) ||
				(multiPass && !interop.CreateSharedTexture(outputDesc, tier.cascadeIntermediates[0],
				("NeuralRendering::CascadeIntermediate0" + tierSuffix).c_str())) ||
				(passCount > 2 && !interop.CreateSharedTexture(outputDesc, tier.cascadeIntermediates[1],
				("NeuralRendering::CascadeIntermediate1" + tierSuffix).c_str())) ||
				!interop.CreateSharedTexture(outputDesc, tier.output, ("NeuralRendering::Output" + tierSuffix).c_str()))
'@
$new = @'
			if ((reducedResolution && !interop.CreateSharedTexture(modelInputDesc, tier.modelInput,
				("NeuralRendering::ModelInput" + tierSuffix).c_str())) ||
				(multiPass && !interop.CreateSharedTexture(outputDesc, tier.cascadeIntermediates[0],
				("NeuralRendering::CascadeIntermediate0" + tierSuffix).c_str())) ||
				(passCount > 2 && !interop.CreateSharedTexture(outputDesc, tier.cascadeIntermediates[1],
				("NeuralRendering::CascadeIntermediate1" + tierSuffix).c_str())) ||
				(croppedSecondPass && !interop.CreateSharedTexture(pass2OutputDesc, tier.secondPassOutput,
				("NeuralRendering::SecondPassOutput" + tierSuffix).c_str())) ||
				!interop.CreateSharedTexture(outputDesc, tier.output, ("NeuralRendering::Output" + tierSuffix).c_str()))
'@
Replace-Exact $renderer $old $new

# EnsureResources carries pass-2 coverage to resource allocation.
$old = @'
		bool EnsureResources(ID3D11Device* device, std::uint32_t eyeIndex, ID3D11Resource* color, ID3D11Resource* depth,
			ID3D11Resource* motionVectors, std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t modelWidth, std::uint32_t modelHeight, std::uint32_t passCount,
			std::uint32_t modelResolution, bool prewarmAdaptive,
'@
$new = @'
		bool EnsureResources(ID3D11Device* device, std::uint32_t eyeIndex, ID3D11Resource* color, ID3D11Resource* depth,
			ID3D11Resource* motionVectors, std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t modelWidth, std::uint32_t modelHeight, std::uint32_t passCount,
			std::uint32_t modelResolution, std::uint32_t secondPassCoverage, bool prewarmAdaptive,
'@
Replace-Exact $renderer $old $new

$old = @'
			if (!EnsureTierResources(device, eyeIndex, eye, tierIndex, modelWidth, modelHeight, passCount, modelResolution,
				sharedColorWidth, sharedColorHeight))
'@
$new = @'
			if (!EnsureTierResources(device, eyeIndex, eye, tierIndex, modelWidth, modelHeight, passCount, modelResolution,
				secondPassCoverage, sharedColorWidth, sharedColorHeight))
'@
Replace-Exact $renderer $old $new

# Prewarm is single-pass, so pass-2 coverage is irrelevant.
$old = @'
						if (!EnsureTierResources(device, eyeIndex, eyes[eyeIndex], candidate,
							candidateModelWidth, candidateModelHeight, passCount, candidateResolution,
							stableColorWidth, stableColorHeight)) {
'@
$new = @'
						if (!EnsureTierResources(device, eyeIndex, eyes[eyeIndex], candidate,
							candidateModelWidth, candidateModelHeight, passCount, candidateResolution, 100u,
							stableColorWidth, stableColorHeight)) {
'@
Replace-Exact $renderer $old $new

# Both normal entry points pass the configured relative coverage.
$text = [IO.File]::ReadAllText((Resolve-Path $renderer)).Replace("`r`n", "`n")
$needle = "passCount, modelResolution,`n`t`t`t`ttuning.adaptiveResolution,"
$count = ([regex]::Matches($text, [regex]::Escape($needle))).Count
if ($count -ne 2) { throw "Expected two EnsureResources call anchors, found $count" }
$text = $text.Replace($needle, "passCount, modelResolution, passCount > 1 ? tuning.secondPass.coveragePercent : 100u,`n`t`t`t`ttuning.adaptiveResolution,")
[IO.File]::WriteAllText((Resolve-Path $renderer), $text, [Text.UTF8Encoding]::new($false))

# Replace the cascade with a centered relative pass-2 subrect. The compact pass-2
# output is merged later; pass 1 and its history remain unchanged.
$pattern = '\t\tbool ExecuteCascade\(ID3D12GraphicsCommandList\* commandList.*?\n\t\t\}\n\n\t\tstruct ModelResolutionConstants'
$replacement = @'
		bool ExecuteCascade(ID3D12GraphicsCommandList* commandList, std::uint32_t eyeIndex, std::uint32_t tierIndex,
			ID3D12Resource* initialInput, ID3D12Resource* depth, ID3D12Resource* motionVectors,
			const std::array<ID3D12Resource*, kCascadePassCount - 1>& intermediates,
			ID3D12Resource* secondPassOutput, ID3D12Resource* finalOutput,
			std::uint32_t firstInputWidth, std::uint32_t firstInputHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t outputWidth, std::uint32_t outputHeight,
			std::uint32_t creationFirstInputWidth, std::uint32_t creationFirstInputHeight,
			std::uint32_t creationOutputWidth, std::uint32_t creationOutputHeight,
			float motionVectorScaleX, float motionVectorScaleY,
			const Tuning& tuning, std::uint32_t passCount, bool reset)
		{
			if (!commandList || !initialInput || !depth || !motionVectors || !finalOutput ||
				passCount == 0 || passCount > kCascadePassCount)
				return false;
			for (std::uint32_t intermediateIndex = 0; intermediateIndex + 1 < passCount; ++intermediateIndex) {
				if (!intermediates[intermediateIndex])
					return false;
			}
			const std::uint32_t pass2Coverage = passCount > 1 ? std::clamp(tuning.secondPass.coveragePercent, 50u, 100u) : 100u;
			const bool croppedSecondPass = passCount > 1 && pass2Coverage < 100;
			if (croppedSecondPass && !secondPassOutput)
				return false;

			for (std::uint32_t passIndex = 0; passIndex < passCount; ++passIndex) {
				ID3D12Resource* input = passIndex == 0 ? initialInput : intermediates[passIndex - 1];
				ID3D12Resource* output = (passIndex == 1 && croppedSecondPass) ? secondPassOutput :
					((passIndex + 1 == passCount) ? finalOutput : intermediates[passIndex]);
				if (!input || !output || input == output)
					return false;

				CS_GPU_PASS_SELECT3(passIndex,
					"NeuralRendering::EvaluatePass0", "NeuralRendering::EvaluatePass1", "NeuralRendering::EvaluatePass2");
				TransitionEvaluationResources(commandList, input, depth, motionVectors, output, true);
				Feature18GuideContract guide{};
				guide.colorWidth = passIndex == 0 ? firstInputWidth : outputWidth;
				guide.colorHeight = passIndex == 0 ? firstInputHeight : outputHeight;
				guide.depthWidth = guideWidth;
				guide.depthHeight = guideHeight;
				guide.motionWidth = guideWidth;
				guide.motionHeight = guideHeight;
				guide.outputWidth = outputWidth;
				guide.outputHeight = outputHeight;
				guide.creationInputWidth = passIndex == 0 ? creationFirstInputWidth : creationOutputWidth;
				guide.creationInputHeight = passIndex == 0 ? creationFirstInputHeight : creationOutputHeight;
				guide.creationOutputWidth = creationOutputWidth;
				guide.creationOutputHeight = creationOutputHeight;
				if (passIndex == 1 && croppedSecondPass) {
					const auto colorW = ScaleDimension(outputWidth, pass2Coverage);
					const auto colorH = ScaleDimension(outputHeight, pass2Coverage);
					const auto guideW = ScaleDimension(guideWidth, pass2Coverage);
					const auto guideH = ScaleDimension(guideHeight, pass2Coverage);
					guide.colorBaseX = (outputWidth - colorW) / 2;
					guide.colorBaseY = (outputHeight - colorH) / 2;
					guide.colorWidth = colorW;
					guide.colorHeight = colorH;
					guide.depthBaseX = (guideWidth - guideW) / 2;
					guide.depthBaseY = (guideHeight - guideH) / 2;
					guide.depthWidth = guideW;
					guide.depthHeight = guideH;
					guide.motionBaseX = guide.depthBaseX;
					guide.motionBaseY = guide.depthBaseY;
					guide.motionWidth = guideW;
					guide.motionHeight = guideH;
					guide.outputWidth = colorW;
					guide.outputHeight = colorH;
					guide.creationInputWidth = ScaleDimension(creationOutputWidth, pass2Coverage);
					guide.creationInputHeight = ScaleDimension(creationOutputHeight, pass2Coverage);
					guide.creationOutputWidth = guide.creationInputWidth;
					guide.creationOutputHeight = guide.creationInputHeight;
				}
				guide.motionVectorScaleX = motionVectorScaleX;
				guide.motionVectorScaleY = motionVectorScaleY;
				guide.motionVectorsLowResolution =
					guide.motionWidth <= guide.colorWidth && guide.motionHeight <= guide.colorHeight;
				const Tuning passTuning = TuningForCascadePass(tuning, passIndex);
				const bool succeeded = Runtime::Instance().Execute(commandList, FeatureSlot(eyeIndex, tierIndex, passIndex),
					input, depth, motionVectors, output, guide, passTuning, reset);
				TransitionEvaluationResources(commandList, input, depth, motionVectors, output, false);
				if (!succeeded) {
					logger::warn("[DLSSNR] cascade pass failed eye={} pass={} of {} coverage={}%", eyeIndex, passIndex + 1, passCount,
						passIndex == 1 ? pass2Coverage : 100u);
					return false;
				}
			}
			return true;
		}

		struct ModelResolutionConstants
'@
Replace-RegexOnce $renderer $pattern $replacement

# Every cascade call now provides the optional compact pass-2 target.
$text = [IO.File]::ReadAllText((Resolve-Path $renderer)).Replace("`r`n", "`n")
$needle = "tier.cascadeIntermediates[0].resource12.Get(), tier.cascadeIntermediates[1].resource12.Get() },`n`t`t`t`ttier.output.resource12.Get(),"
$count = ([regex]::Matches($text, [regex]::Escape($needle))).Count
if ($count -lt 2) { throw "Expected at least two cascade call anchors, found $count" }
$text = $text.Replace($needle, "tier.cascadeIntermediates[0].resource12.Get(), tier.cascadeIntermediates[1].resource12.Get() },`n`t`t`t`ttier.secondPassOutput.resource12.Get(), tier.output.resource12.Get(),")
[IO.File]::WriteAllText((Resolve-Path $renderer), $text, [Text.UTF8Encoding]::new($false))

# Merge compact pass-2 output over pass 1 immediately after returning to D3D11.
# This keeps all existing result-shaping/writeback code on a full-size merged image.
$merge = @'
			if (passCount == 2 && tuning.secondPass.coveragePercent < 100) {
				const auto pass2Coverage = std::clamp(tuning.secondPass.coveragePercent, 50u, 100u);
				const auto pass2Width = ScaleDimension(modelWidth, pass2Coverage);
				const auto pass2Height = ScaleDimension(modelHeight, pass2Coverage);
				if (!tier.secondPassOutput.resource11 || !tier.cascadeIntermediates[0].resource11)
					return LatchFailure("second-pass merge resources", E_FAIL);
				context->CopyResource(tier.output.resource11.Get(), tier.cascadeIntermediates[0].resource11.Get());
				const D3D11_BOX pass2Box{ 0, 0, 0, pass2Width, pass2Height, 1 };
				context->CopySubresourceRegion(tier.output.resource11.Get(), 0,
					(modelWidth - pass2Width) / 2, (modelHeight - pass2Height) / 2, 0,
					tier.secondPassOutput.resource11.Get(), 0, &pass2Box);
			}
'@

# Single-eye path: insert after successful EndD3D12 and Feature check, before resolve.
$old = @'
			if (!succeeded) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("Feature 18", static_cast<HRESULT>(Runtime::Instance().NgxResult()));
			}

			if (tier.reducedResolution && !DispatchModelResolve(device, context, eye, tier, colorWidth, colorHeight, resolveSettings,
'@
$new = @'
			if (!succeeded) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("Feature 18", static_cast<HRESULT>(Runtime::Instance().NgxResult()));
			}

'@ + $merge + @'

			if (tier.reducedResolution && !DispatchModelResolve(device, context, eye, tier, colorWidth, colorHeight, resolveSettings,
'@
Replace-Exact $renderer $old $new

# Stereo path: merge each eye before model resolve / shaping.
$old = @'
			D3D11_BOX outputBox{ 0, 0, 0, colorWidth, colorHeight, 1 };
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				const auto& input = inputs[eyeIndex];
				auto& eye = eyes[eyeIndex];
				auto& tier = eye.tiers[tierIndex];
				if (tier.reducedResolution && !DispatchModelResolve(device, context, eye, tier, colorWidth, colorHeight, resolveSettings,
'@
$new = @'
			D3D11_BOX outputBox{ 0, 0, 0, colorWidth, colorHeight, 1 };
			for (std::uint32_t eyeIndex = 0; eyeIndex < inputs.size(); ++eyeIndex) {
				const auto& input = inputs[eyeIndex];
				auto& eye = eyes[eyeIndex];
				auto& tier = eye.tiers[tierIndex];
				if (passCount == 2 && tuning.secondPass.coveragePercent < 100) {
					const auto pass2Coverage = std::clamp(tuning.secondPass.coveragePercent, 50u, 100u);
					const auto pass2Width = ScaleDimension(modelWidth, pass2Coverage);
					const auto pass2Height = ScaleDimension(modelHeight, pass2Coverage);
					if (!tier.secondPassOutput.resource11 || !tier.cascadeIntermediates[0].resource11)
						return LatchFailure("second-pass stereo merge resources", E_FAIL);
					context->CopyResource(tier.output.resource11.Get(), tier.cascadeIntermediates[0].resource11.Get());
					const D3D11_BOX pass2Box{ 0, 0, 0, pass2Width, pass2Height, 1 };
					context->CopySubresourceRegion(tier.output.resource11.Get(), 0,
						(modelWidth - pass2Width) / 2, (modelHeight - pass2Height) / 2, 0,
						tier.secondPassOutput.resource11.Get(), 0, &pass2Box);
				}
				if (tier.reducedResolution && !DispatchModelResolve(device, context, eye, tier, colorWidth, colorHeight, resolveSettings,
'@
Replace-Exact $renderer $old $new

Write-Host 'v01 sequential relative pass-2 renderer applied successfully.'
