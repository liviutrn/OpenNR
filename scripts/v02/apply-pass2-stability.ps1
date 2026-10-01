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
$composite = 'runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/SequentialCompositeCS.hlsl'

Write-Host 'v02 reduced P2: keep the native Feature18 creation envelope full-size'
# v01 resized the P2 native handle itself. Keep native creation dimensions stable
# and let only the valid evaluation subrect change with P2 coverage.
$pattern = '\t\t\tconst bool lowResolutionMotion = [^\n]+;\n\t\t\tfor \(std::uint32_t pass = 0; pass < passCount; \+\+pass\) \{.*?\n\t\t\t\}'
$replacement = @'
			const std::uint32_t pass2Coverage = passCount > 1 ? std::clamp(secondPassCoverage, 50u, 100u) : 100u;
			for (std::uint32_t pass = 0; pass < passCount; ++pass) {
				const bool croppedPass2 = pass == 1 && pass2Coverage < 100;
				const std::uint32_t expectedInputWidth = pass == 0 ? featureInputWidth : resourceModelWidth;
				const std::uint32_t expectedInputHeight = pass == 0 ? featureInputHeight : resourceModelHeight;
				const std::uint32_t expectedOutputWidth = resourceModelWidth;
				const std::uint32_t expectedOutputHeight = resourceModelHeight;
				const std::uint32_t evalColorWidth = croppedPass2 ? ScaleDimension(resourceModelWidth, pass2Coverage) : expectedInputWidth;
				const std::uint32_t evalColorHeight = croppedPass2 ? ScaleDimension(resourceModelHeight, pass2Coverage) : expectedInputHeight;
				const std::uint32_t evalGuideWidth = croppedPass2 ? ScaleDimension(sharedGuideWidth, pass2Coverage) : sharedGuideWidth;
				const std::uint32_t evalGuideHeight = croppedPass2 ? ScaleDimension(sharedGuideHeight, pass2Coverage) : sharedGuideHeight;
				const bool lowResolutionMotion = evalGuideWidth <= evalColorWidth && evalGuideHeight <= evalColorHeight;
				const auto slot = FeatureSlot(eyeIndex, tierIndex, pass);
				if (!Runtime::Instance().NeedsRecreation(slot, expectedInputWidth, expectedInputHeight,
					expectedOutputWidth, expectedOutputHeight, lowResolutionMotion))
					continue;
				if (!waited && !interop.WaitForIdle())
					return false;
				waited = true;
				Runtime::Instance().ResetFeature(slot);
				resetPending[eyeIndex][tierIndex] = true;
			}
'@
Replace-RegexOnce $renderer $pattern $replacement

Write-Host 'v02 reduced P2: use a full-size scratch without rebuilding the tier'
# Match these declarations independently. Other v01/v02 transforms may insert
# adjacent declarations, but the three P2 descriptor statements themselves are
# the contract that must change.
Replace-RegexOnce $renderer '[ \t]*const auto pass2ResourceWidth = ScaleDimension\(resourceModelWidth, pass2Coverage\);[ \t]*\n' ''
Replace-RegexOnce $renderer '[ \t]*const auto pass2ResourceHeight = ScaleDimension\(resourceModelHeight, pass2Coverage\);[ \t]*\n' ''
Replace-RegexOnce $renderer '[ \t]*const auto pass2OutputDesc = MakeSharedDesc\(eye\.color\.desc,\s*pass2ResourceWidth,\s*pass2ResourceHeight,\s*sharedFlags\);[ \t]*\n' "`t`t`tconst auto pass2OutputDesc = outputDesc;`n"

Write-Host 'v02 reduced P2: remove compact scratch from tier identity'
$pattern = '[ \t]*\(!croppedSecondPass \|\| Matches\(tier\.secondPassOutput, pass2OutputDesc\)\) &&[ \t]*\n'
Replace-RegexOnce $renderer $pattern ''

Write-Host 'v02 reduced P2: allocate the full-size scratch lazily'
$pattern = '[ \t]*if \(resourcesMatch\)[ \t]*\n[ \t]*return true;'
$replacement = @'
			if (resourcesMatch) {
				// At 100% P2 the normal full-size final output is used directly. If the
				// user later selects <100%, allocate only a full-size P2 scratch; do not
				// rebuild the tier or retire otherwise-compatible Feature18 histories.
				if (croppedSecondPass && !Matches(tier.secondPassOutput, pass2OutputDesc)) {
					if (tier.secondPassOutput.resource11 && !interop.WaitForIdle())
						return false;
					tier.secondPassOutput = {};
					if (!interop.CreateSharedTexture(pass2OutputDesc, tier.secondPassOutput,
						("NeuralRendering::SecondPassOutput" + std::to_string(eyeIndex) + "_" + std::to_string(modelResolution)).c_str()))
						return false;
				}
				return true;
			}
'@
Replace-RegexOnce $renderer $pattern $replacement

Write-Host 'v02 reduced P2: evaluate centered subrect into the full-size scratch'
$pattern = '[ \t]*guide\.outputWidth = colorW;[ \t]*\n[ \t]*guide\.outputHeight = colorH;'
$replacement = @'
					guide.outputBaseX = (outputWidth - colorW) / 2;
					guide.outputBaseY = (outputHeight - colorH) / 2;
					guide.outputWidth = colorW;
					guide.outputHeight = colorH;
'@
Replace-RegexOnce $renderer $pattern $replacement
$pattern = '[ \t]*guide\.creationInputWidth = ScaleDimension\(creationOutputWidth, pass2Coverage\);[ \t]*\n[ \t]*guide\.creationInputHeight = ScaleDimension\(creationOutputHeight, pass2Coverage\);[ \t]*\n[ \t]*guide\.creationOutputWidth = guide\.creationInputWidth;[ \t]*\n[ \t]*guide\.creationOutputHeight = guide\.creationInputHeight;'
$replacement = @'
					// Only the valid rectangle changes. Feature18 remains created against
					// the same full-size P1/P2 envelope at every coverage setting.
					guide.creationInputWidth = creationOutputWidth;
					guide.creationInputHeight = creationOutputHeight;
					guide.creationOutputWidth = creationOutputWidth;
					guide.creationOutputHeight = creationOutputHeight;
'@
Replace-RegexOnce $renderer $pattern $replacement

Write-Host 'v02 reduced P2: composite from the centered full-size scratch region'
Replace-Exact $composite `
    'const float4 pass2 = Pass2Tex.Load(int3(local, 0));' `
    'const float4 pass2 = Pass2Tex.Load(int3(dstPos, 0));'

Write-Host 'v02 reduced P2 atlas: keep the native atlas P2 handle full-size'
# The v01 atlas already packs a reduced P2 as a compact LEFT|guard|RIGHT rectangle
# into the top-left of the existing full-size atlas resource. Preserve that compact
# valid rectangle for performance, but create the native P2 handle against the full
# atlas envelope so changing P2 coverage cannot invalidate/recreate Feature18.
$pattern = '[ \t]*guide\.creationInputWidth = atlasColorWidth;[ \t]*\n[ \t]*guide\.creationInputHeight = eyeColorHeight;[ \t]*\n[ \t]*guide\.creationOutputWidth = atlasColorWidth;[ \t]*\n[ \t]*guide\.creationOutputHeight = eyeColorHeight;'
$replacement = @'
			const auto atlasCreationColorWidth = stereoAtlas.colorEyeWidth * 2 + stereoAtlas.colorGuard;
			const auto atlasCreationColorHeight = stereoAtlas.colorEyeHeight;
			guide.creationInputWidth = atlasCreationColorWidth;
			guide.creationInputHeight = atlasCreationColorHeight;
			guide.creationOutputWidth = atlasCreationColorWidth;
			guide.creationOutputHeight = atlasCreationColorHeight;
'@
Replace-RegexOnce $renderer $pattern $replacement

Write-Host 'v02 reduced P2 atlas: split compact atlas output into centered per-eye scratch regions'
$old = @'
		void SplitStereoAtlasOutput(ID3D11DeviceContext* context, ID3D11Resource* leftTarget, ID3D11Resource* rightTarget,
			std::uint32_t eyeWidth, std::uint32_t eyeHeight, std::uint32_t guardWidth)
		{
			const D3D11_BOX leftBox{ 0, 0, 0, eyeWidth, eyeHeight, 1 };
			const D3D11_BOX rightBox{ eyeWidth + guardWidth, 0, 0, eyeWidth * 2 + guardWidth, eyeHeight, 1 };
			context->CopySubresourceRegion(leftTarget, 0, 0, 0, 0, stereoAtlas.output.resource11.Get(), 0, &leftBox);
			context->CopySubresourceRegion(rightTarget, 0, 0, 0, 0, stereoAtlas.output.resource11.Get(), 0, &rightBox);
		}
'@
$new = @'
		void SplitStereoAtlasOutput(ID3D11DeviceContext* context, ID3D11Resource* leftTarget, ID3D11Resource* rightTarget,
			std::uint32_t eyeWidth, std::uint32_t eyeHeight, std::uint32_t guardWidth,
			std::uint32_t destinationOffsetX = 0, std::uint32_t destinationOffsetY = 0)
		{
			const D3D11_BOX leftBox{ 0, 0, 0, eyeWidth, eyeHeight, 1 };
			const D3D11_BOX rightBox{ eyeWidth + guardWidth, 0, 0, eyeWidth * 2 + guardWidth, eyeHeight, 1 };
			context->CopySubresourceRegion(leftTarget, 0, destinationOffsetX, destinationOffsetY, 0,
				stereoAtlas.output.resource11.Get(), 0, &leftBox);
			context->CopySubresourceRegion(rightTarget, 0, destinationOffsetX, destinationOffsetY, 0,
				stereoAtlas.output.resource11.Get(), 0, &rightBox);
		}
'@
Replace-Exact $renderer $old $new

$old = @'
					SplitStereoAtlasOutput(context, leftTier.secondPassOutput.resource11.Get(), rightTier.secondPassOutput.resource11.Get(),
						pass2Width, pass2Height, pass2ColorGuard);
'@
$new = @'
					SplitStereoAtlasOutput(context, leftTier.secondPassOutput.resource11.Get(), rightTier.secondPassOutput.resource11.Get(),
						pass2Width, pass2Height, pass2ColorGuard,
						(modelWidth - pass2Width) / 2, (modelHeight - pass2Height) / 2);
'@
Replace-Exact $renderer $old $new

Write-Host 'v02 reduced P2: verify stable-envelope invariants'
$text = [IO.File]::ReadAllText((Resolve-Path $renderer)).Replace("`r`n", "`n")
$shaderText = [IO.File]::ReadAllText((Resolve-Path $composite)).Replace("`r`n", "`n")
if ($text -notmatch 'expectedInputWidth = pass == 0 \? featureInputWidth : resourceModelWidth') {
    throw 'P2 recreation contract is not using the stable full-size input envelope'
}
if ($text -match 'expectedInputWidth = compactPass2 \? ScaleDimension') {
    throw 'Stale compact native-handle recreation logic remains'
}
if ($text -notmatch 'const auto pass2OutputDesc = outputDesc;') {
    throw 'P2 scratch is not full-size'
}
if ($text -notmatch 'guide\.outputBaseX = \(outputWidth - colorW\) / 2;' -or
    $text -notmatch 'guide\.creationInputWidth = creationOutputWidth;') {
    throw 'P2 centered eval subrect is not backed by the full creation envelope'
}
if ($shaderText -notmatch 'Pass2Tex\.Load\(int3\(dstPos, 0\)\)') {
    throw 'Sequential composite does not sample the centered full-size P2 scratch'
}
if ($text -notmatch 'atlasCreationColorWidth = stereoAtlas\.colorEyeWidth \* 2 \+ stereoAtlas\.colorGuard' -or
    $text -notmatch 'guide\.creationInputWidth = atlasCreationColorWidth;') {
    throw 'Atlas P2 is not using the stable full-size native creation envelope'
}
if ($text -notmatch 'destinationOffsetX = 0, std::uint32_t destinationOffsetY = 0' -or
    $text -notmatch '\(modelWidth - pass2Width\) / 2, \(modelHeight - pass2Height\) / 2') {
    throw 'Reduced atlas P2 output is not split into centered per-eye scratch regions'
}
if ($text -match 'passCount <= 2 && !compactPass2 && !tuning\.adaptiveResolution') {
    throw 'Reduced P2 is still disabled for stereo atlas'
}
if ($text -notmatch 'const bool compatible = passCount >= 1 && passCount <= 2 && !tuning\.adaptiveResolution') {
    throw 'Stereo atlas compatibility gate was unexpectedly changed'
}

Write-Host 'v02 reduced pass-2 stable-envelope repair, including stereo atlas, applied successfully.'