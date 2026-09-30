$ErrorActionPreference = 'Stop'

$source = 'scripts/v01/apply-stereo-atlas.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")

# The original atlas transform used a generic BeginD3D12 block that exists in
# single-eye, staggered, and normal stereo routes. Rewrite only that transform
# block to select the occurrence immediately followed by ExecuteAdaptivePrewarm,
# which uniquely identifies ApplyStereo's normal native-evaluation section.
$blockRx = [regex]::new('(?s)# Try atlas after all per-eye inputs are prepared.*?Replace-Exact \$renderer \$old \$new\n')
if ($blockRx.Matches($text).Count -ne 1) { throw 'Expected one atlas insertion transform block' }

$replacement = @'
# Try atlas after all per-eye inputs are prepared and capture has consumed them,
# but before the normal independent-eye D3D12 evaluate block. The command-list
# anchor is unique because ApplyStereo immediately prewarms adjacent tiers.
$rendererPath = Resolve-Path $renderer
$rendererText = [IO.File]::ReadAllText($rendererPath).Replace("`r`n", "`n")
$stereoRx = [regex]::new('(?s)(\t\t\tID3D12GraphicsCommandList\* commandList = nullptr;\n\t\t\tif \(!interop\.BeginD3D12\(&commandList\)\) \{.*?\n\t\t\t\}\n)(\t\t\tExecuteAdaptivePrewarm\(commandList, adaptivePrewarm, stableGuideWidth, stableGuideHeight,\n\t\t\t\tstableColorWidth, stableColorHeight\);)')
$matches = $stereoRx.Matches($rendererText)
if ($matches.Count -ne 1) { throw "Expected one stereo BeginD3D12/prewarm block, found $($matches.Count)" }
$prefix = @'
			bool nativeEvaluationDone = false;
			const auto atlasResult = ApplyStereoAtlasNative(device, context, inputs, tierIndex,
				colorWidth, colorHeight, guideWidth, guideHeight, modelWidth, modelHeight,
				modelResolution, passCount, tuning);
			if (atlasResult == StereoAtlasResult::Failed) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("stereo atlas", E_FAIL);
			}
			nativeEvaluationDone = atlasResult == StereoAtlasResult::Applied;

			if (!nativeEvaluationDone) {
'@
$originalBegin = $matches[0].Groups[1].Value
$originalPrewarm = $matches[0].Groups[2].Value
$rendererText = $stereoRx.Replace($rendererText, $prefix + $originalBegin + $originalPrewarm, 1)
[IO.File]::WriteAllText($rendererPath, $rendererText, [Text.UTF8Encoding]::new($false))
'@

$text = $blockRx.Replace($text, $replacement + "`n", 1)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Corrected stereo atlas transform failed with exit code $LASTEXITCODE" }
