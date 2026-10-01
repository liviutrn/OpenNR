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

function Insert-After-Unique {
    param([string]$Path,[string]$Needle,[string]$Insertion)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Needle))).Count
    if ($count -ne 1) { throw "Expected exactly one insertion anchor in $Path, found $count: $Needle" }
    [IO.File]::WriteAllText($resolved, $text.Replace($Needle, $Needle + $Insertion), [Text.UTF8Encoding]::new($false))
}

$foveated = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$postHeader = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender/Postprocess.h'
$postCpp = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender/Postprocess.cpp'

Write-Host 'v02 sharpening: clamp settings to 0..3'
Replace-Exact $foveated `
    'settings.neuralRenderingSharpeningStrength = clampFinite(settings.neuralRenderingSharpeningStrength, 0.0f, 0.0f, 5.0f);' `
    'settings.neuralRenderingSharpeningStrength = clampFinite(settings.neuralRenderingSharpeningStrength, 0.0f, 0.0f, 3.0f);'
Replace-Exact $foveated `
    'pass2.sharpeningStrength = clampFinite(pass2.sharpeningStrength, 0.0f, 0.0f, 5.0f);' `
    'pass2.sharpeningStrength = clampFinite(pass2.sharpeningStrength, 0.0f, 0.0f, 3.0f);'

Write-Host 'v02 sharpening: declare and implement NR RCAS stage'
$old = @'
		static bool ApplyDlssSharpening(Upscaling& upscaling);
'@
$new = @'
		static bool ApplyDlssSharpening(Upscaling& upscaling);
		// NR-specific sharpening. strength is the v02 user scale (0..3) and is
		// normalized to the existing RCAS kernel's safe 0..1 coefficient.
		static bool ApplyNeuralRenderingSharpening(Upscaling& upscaling, float strength, const char* placement);
'@
Replace-Exact $postHeader $old $new

# std::clamp is used by the new path; do not rely on incidental transitive includes.
Insert-After-Unique $postCpp '#include "../FoveatedRender.h"' "`n`n#include <algorithm>"

# Insert the method immediately before the namespace's final closing brace. This is
# intentionally independent of ApplyDlssSharpening's precise tail formatting.
$postResolved = Resolve-Path $postCpp
$postText = [IO.File]::ReadAllText($postResolved).Replace("`r`n", "`n").TrimEnd()
$namespaceClose = $postText.LastIndexOf("`n}")
if ($namespaceClose -lt 0) { throw 'Could not locate Postprocess namespace closing brace' }
$method = @'

	bool Postprocess::ApplyNeuralRenderingSharpening(Upscaling& upscaling, float strength, const char* placement)
	{
		strength = std::clamp(std::isfinite(strength) ? strength : 0.0f, 0.0f, 3.0f);
		if (strength <= 0.0f)
			return true;

		if (!upscaling.sharpenerTexture || !upscaling.sharpenerTexture->uav || !upscaling.sharpenerTexture->resource) {
			logger::error("[DLSSNR][SHARPEN] missing RCAS scratch resources placement={}", placement ? placement : "unknown");
			return false;
		}

		auto context = globals::d3d::context;
		auto renderer = globals::game::renderer;
		if (!context || !renderer) {
			logger::error("[DLSSNR][SHARPEN] missing D3D context/renderer placement={}", placement ? placement : "unknown");
			return false;
		}

		auto& main = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kMAIN];
		if (!main.SRV) {
			logger::error("[DLSSNR][SHARPEN] missing kMAIN SRV placement={}", placement ? placement : "unknown");
			return false;
		}

		ID3D11Resource* mainResource = nullptr;
		main.SRV->GetResource(Util::AsW32(&mainResource));
		if (!mainResource) {
			logger::error("[DLSSNR][SHARPEN] failed to acquire kMAIN resource placement={}", placement ? placement : "unknown");
			return false;
		}

		// The RCAS HLSL multiplies a bounded negative lobe by this value. Keep the
		// actual kernel coefficient <= 1.0 even though the ergonomic UI scale is 0..3.
		const float rcasStrength = std::clamp(strength / 3.0f, 0.0f, 1.0f);
		context->OMSetRenderTargets(0, nullptr, nullptr);
		upscaling.rcas.ApplySharpen(Util::AsReal(main.SRV), upscaling.sharpenerTexture->uav.get(), rcasStrength);
		context->CopyResource(mainResource, upscaling.sharpenerTexture->resource.get());
		mainResource->Release();

		if (globals::game::stateUpdateFlags)
			globals::game::stateUpdateFlags->set(RE::BSGraphics::ShaderFlags::DIRTY_RENDERTARGET);

		if (globals::state && globals::state->frameCount % 300 == 0) {
			logger::info("[DLSSNR][SHARPEN] placement={} userStrength={:.2f} rcasStrength={:.3f} dispatch=ok",
				placement ? placement : "unknown", strength, rcasStrength);
		}
		return true;
	}
'@
$postText = $postText.Substring(0, $namespaceClose) + $method + $postText.Substring($namespaceClose) + "`n"
[IO.File]::WriteAllText($postResolved, $postText, [Text.UTF8Encoding]::new($false))

Write-Host 'v02 sharpening: wire literal before/after Feature18 boundary'
# Add Postprocess include by a single stable line, not by adjacency to another include.
Insert-After-Unique $foveated '#include "FoveatedRender/Core.h"' "`n#include \"FoveatedRender/Postprocess.h\""

# Replace the hook body using the following function signature as the right boundary.
$pattern = 'void FoveatedRender::UICompositeRenderHook::thunk\([^\n]*\)\s*\{.*?\n\}\n\nvoid FoveatedRender::ClearShaderCache\(\)'
$replacement = @'
void FoveatedRender::UICompositeRenderHook::thunk(void* imageSpaceShader, RE::BSTriShape* shape, RE::ImageSpaceEffectParam* param)
{
	auto& upscaling = globals::features::upscaling;
	auto& foveated = upscaling.foveatedRender;
	const auto& nr = foveated.settings;
	const bool sharpen = foveated.IsActive() && nr.neuralRenderingEnabled &&
		nr.neuralRenderingSharpeningEnabled && nr.neuralRenderingSharpeningStrength > 0.0f;

	if (sharpen && nr.neuralRenderingSharpeningPlacement == 0)
		FoveatedRenderImpl::Postprocess::ApplyNeuralRenderingSharpening(
			upscaling, nr.neuralRenderingSharpeningStrength, "before-NR");

	NeuralRendering::ApplyFoveatedLdr();

	if (sharpen && nr.neuralRenderingSharpeningPlacement == 1)
		FoveatedRenderImpl::Postprocess::ApplyNeuralRenderingSharpening(
			upscaling, nr.neuralRenderingSharpeningStrength, "after-NR");

	func(imageSpaceShader, shape, param);
}

void FoveatedRender::ClearShaderCache()
'@
Replace-RegexOnce $foveated $pattern $replacement

Write-Host 'v02 sharpening: add user controls'
# Insert before the unique Stereo Atlas separator, independent of indentation.
$fovResolved = Resolve-Path $foveated
$fovText = [IO.File]::ReadAllText($fovResolved).Replace("`r`n", "`n")
$marker = 'ImGui::SeparatorText("Stereo Atlas");'
$markerCount = ([regex]::Matches($fovText, [regex]::Escape($marker))).Count
if ($markerCount -ne 1) { throw "Expected one Stereo Atlas UI marker, found $markerCount" }
$ui = @'
ImGui::SeparatorText("NR Sharpening");
				bool nrSharpenChanged = false;
				nrSharpenChanged |= ImGui::Checkbox("Enable NR sharpening", &settings.neuralRenderingSharpeningEnabled);
				static const char* nrSharpenPlacement[] = { "Before NR", "After NR" };
				int nrSharpenPlacementIndex = static_cast<int>(std::min(settings.neuralRenderingSharpeningPlacement, 1u));
				if (ImGui::Combo("Sharpening placement", &nrSharpenPlacementIndex,
					nrSharpenPlacement, IM_ARRAYSIZE(nrSharpenPlacement))) {
					settings.neuralRenderingSharpeningPlacement = static_cast<uint>(nrSharpenPlacementIndex);
					nrSharpenChanged = true;
				}
				nrSharpenChanged |= ImGui::SliderFloat("NR sharpening strength", &settings.neuralRenderingSharpeningStrength,
					0.0f, 3.0f, "%.2f");
				if (nrSharpenChanged) {
					ClampSettings();
					if (settings.neuralRenderingSharpeningPlacement == 0)
						NeuralRendering::RequestHistoryReset();
				}
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped("Runs the existing RCAS compute path at an explicit Feature18 boundary. 0..3 is normalized to RCAS's safe kernel range; 3.0 is maximum. Before NR sharpens the DLSS image Feature18 sees; After NR sharpens the completed NR result.");
				if (settings.neuralRenderingSharpeningEnabled &&
					globals::features::upscaling.settings.sharpnessEnabledDLSS &&
					globals::features::upscaling.settings.sharpnessDLSS > 0.0f)
					drawWarningWrapped("Shared DLSS sharpening is also enabled, so two sharpening stages may be active.");

				ImGui::SeparatorText("Stereo Atlas");
'@
$fovText = $fovText.Replace($marker, $ui)
[IO.File]::WriteAllText($fovResolved, $fovText, [Text.UTF8Encoding]::new($false))

Write-Host 'v02 sharpening: verify executable wiring'
$foveatedText = [IO.File]::ReadAllText((Resolve-Path $foveated)).Replace("`r`n", "`n")
$postText = [IO.File]::ReadAllText((Resolve-Path $postCpp)).Replace("`r`n", "`n")
$beforeIndex = $foveatedText.IndexOf('"before-NR"')
$nrIndex = $foveatedText.IndexOf('NeuralRendering::ApplyFoveatedLdr();')
$afterIndex = $foveatedText.IndexOf('"after-NR"')
if ($beforeIndex -lt 0 -or $nrIndex -lt 0 -or $afterIndex -lt 0 -or !($beforeIndex -lt $nrIndex -and $nrIndex -lt $afterIndex)) {
    throw 'NR sharpening calls are not ordered literally before/after ApplyFoveatedLdr'
}
if ($postText -notmatch 'rcas\.ApplySharpen' -or $postText -notmatch 'strength / 3\.0f') {
    throw 'NR sharpening is not wired to RCAS with the v02 safe normalization'
}
if ($foveatedText -match 'neuralRenderingSharpeningStrength, 0\.0f, 0\.0f, 5\.0f') {
    throw 'Stale 5.0 global sharpening clamp remains'
}

Write-Host 'v02 verified before/after NR sharpening applied successfully.'
