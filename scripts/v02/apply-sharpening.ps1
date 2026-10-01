$ErrorActionPreference = 'Stop'

function Replace-Exact {
    param([string]$Path,[string]$Old,[string]$New)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected exactly one source block in $Path, found $count" }
    [IO.File]::WriteAllText($resolved, $text.Replace($Old,$New), [Text.UTF8Encoding]::new($false))
}

$foveated = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$postHeader = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender/Postprocess.h'
$postCpp = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender/Postprocess.cpp'

# v01 serialized the NR-sharpening controls but intentionally did not execute them.
# v02 makes the global NR control real and caps the user-facing strength at 3.0.
Replace-Exact $foveated `
    'settings.neuralRenderingSharpeningStrength = clampFinite(settings.neuralRenderingSharpeningStrength, 0.0f, 0.0f, 5.0f);' `
    'settings.neuralRenderingSharpeningStrength = clampFinite(settings.neuralRenderingSharpeningStrength, 0.0f, 0.0f, 3.0f);'
Replace-Exact $foveated `
    'pass2.sharpeningStrength = clampFinite(pass2.sharpeningStrength, 0.0f, 0.0f, 5.0f);' `
    'pass2.sharpeningStrength = clampFinite(pass2.sharpeningStrength, 0.0f, 0.0f, 3.0f);'

# Reuse the already-proven RCAS resource path instead of inventing a second sharpening
# implementation. The v02 slider is 0..3; it maps monotonically to RCAS's safe 0..1
# lobe multiplier so the denominator in the existing RCAS resolve cannot be driven into
# the unstable >1 regime by a user-facing value above 1.
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

$old = @'
		return true;
	}
}
'@
$new = @'
		return true;
	}

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

		// The RCAS shader multiplies its bounded negative lobe by this value. Keep
		// that coefficient <= 1.0; the 0..3 UI scale is intentionally ergonomic,
		// not a literal multiplier of the RCAS lobe.
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
}
'@
Replace-Exact $postCpp $old $new

# The VR UI-composite hook is the clean boundary around Feature18: kMAIN already contains
# the post-DLSS image before ApplyFoveatedLdr(), and contains the completed NR result after.
# This makes the requested placement literal rather than approximate.
$old = @'
#include "FoveatedRender/Core.h"
#include "NativeOpenVRGaze.h"
'@
$new = @'
#include "FoveatedRender/Core.h"
#include "FoveatedRender/Postprocess.h"
#include "NativeOpenVRGaze.h"
'@
Replace-Exact $foveated $old $new

$old = @'
void FoveatedRender::UICompositeRenderHook::thunk(void* imageSpaceShader, RE::BSTriShape* shape, RE::ImageSpaceEffectParam* param)
{
	NeuralRendering::ApplyFoveatedLdr();
	func(imageSpaceShader, shape, param);
}
'@
$new = @'
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
'@
Replace-Exact $foveated $old $new

# Expose only the now-executing global NR sharpening controls. P2's historical plumbing
# remains serialized for compatibility but is intentionally not presented as a working
# separate stage in v02.
$old = @'
				ImGui::SeparatorText("Stereo Atlas");
'@
$new = @'
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
Replace-Exact $foveated $old $new

# Build-time wiring assertions: these intentionally fail CI if a later source change leaves
# the setting serialized but disconnects either placement from the actual RCAS dispatch.
$foveatedText = [IO.File]::ReadAllText((Resolve-Path $foveated)).Replace("`r`n", "`n")
$postText = [IO.File]::ReadAllText((Resolve-Path $postCpp)).Replace("`r`n", "`n")
if ($foveatedText -notmatch 'ApplyNeuralRenderingSharpening\([\s\S]*before-NR' -or
    $foveatedText -notmatch 'ApplyNeuralRenderingSharpening\([\s\S]*after-NR') {
    throw 'NR sharpening placement is not wired on both sides of ApplyFoveatedLdr'
}
if ($postText -notmatch 'rcas\.ApplySharpen' -or $postText -notmatch 'strength / 3\.0f') {
    throw 'NR sharpening is not wired to RCAS with the v02 safe normalization'
}
if ($foveatedText -match 'neuralRenderingSharpeningStrength, 0\.0f, 0\.0f, 5\.0f') {
    throw 'Stale 5.0 global sharpening clamp remains'
}

Write-Host 'v02 verified before/after NR sharpening applied successfully.'
