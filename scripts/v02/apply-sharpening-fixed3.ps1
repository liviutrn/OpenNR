$ErrorActionPreference = 'Stop'

function Replace-Exact {
    param([string]$Path,[string]$Old,[string]$New)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected exactly one source block in $Path, found $count" }
    [IO.File]::WriteAllText($resolved, $text.Replace($Old,$New), [Text.UTF8Encoding]::new($false))
}

# Do not run the old v02 apply-sharpening.ps1 transform. It introduced a second,
# NR-specific sharpening UI and dispatch around Feature18. The intended control is
# the original Upscaling-tab DLSS sharpening, so repair that existing route instead.
$header = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.h'
$foveated = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$post = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender/Postprocess.cpp'

Write-Host 'v02 sharpening: remove latent NR-specific sharpening settings'
$empty = ''
Replace-Exact $header @'
		bool sharpeningEnabled = false;
		float sharpeningStrength = 0.0f;  // 0..5
		uint sharpeningPlacement = 1;     // 0=before NR, 1=after NR
'@ $empty
Replace-Exact $header @'
		bool neuralRenderingSharpeningEnabled = false;
		float neuralRenderingSharpeningStrength = 0.0f;  // 0..5
		uint neuralRenderingSharpeningPlacement = 1;     // 0=before NR, 1=after NR
'@ $empty

$old = @'
	X(ditherStrength) \
	X(sharpeningEnabled) \
	X(sharpeningStrength) \
	X(sharpeningPlacement)
'@
$new = @'
	X(ditherStrength)
'@
Replace-Exact $foveated $old $new

$old = @'
	X(neuralRenderingResultHaloSuppression) \
	X(neuralRenderingSharpeningEnabled) \
	X(neuralRenderingSharpeningStrength) \
	X(neuralRenderingSharpeningPlacement) \
	X(neuralRenderingStabilizeMode) \
'@
$new = @'
	X(neuralRenderingResultHaloSuppression) \
	X(neuralRenderingStabilizeMode) \
'@
Replace-Exact $foveated $old $new

Replace-Exact $foveated @'
	settings.neuralRenderingSharpeningStrength = clampFinite(settings.neuralRenderingSharpeningStrength, 0.0f, 0.0f, 5.0f);
	settings.neuralRenderingSharpeningPlacement = std::min(settings.neuralRenderingSharpeningPlacement, 1u);
'@ $empty
Replace-Exact $foveated @'
	pass2.sharpeningStrength = clampFinite(pass2.sharpeningStrength, 0.0f, 0.0f, 5.0f);
	pass2.sharpeningPlacement = std::min(pass2.sharpeningPlacement, 1u);
'@ $empty

Write-Host 'v02 sharpening: repair the original foveated/PerfMode DLSS RCAS route'
$old = @'
	bool Postprocess::ApplyDlssSharpening(Upscaling& upscaling)
	{
		if (!upscaling.IsDlssSharpeningEnabled()) {
			return true;
		}

		if (!upscaling.sharpenerTexture || !upscaling.sharpenerTexture->uav || !upscaling.sharpenerTexture->resource) {
			logger::error("[FOVEATED] Missing sharpener resources");
			return false;
		}

		auto context = globals::d3d::context;
		auto renderer = globals::game::renderer;
		if (!context || !renderer) {
			logger::error("[FOVEATED] Missing D3D context or renderer for sharpening");
			return false;
		}
		auto& main = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kMAIN];

		if (!main.SRV) {
			logger::error("[FOVEATED] Missing main SRV for sharpening");
			return false;
		}

		// Same exponential mapping Upscaling::ApplySharpening uses: lower
		// setting = stronger sharpen.
		float currentSharpness = (-2.0f * upscaling.settings.sharpnessDLSS) + 2.0f;
		currentSharpness = exp2(-currentSharpness);

		// In-place RCAS on kMAIN through sharpenerTexture.
		ID3D11Resource* mainResource = nullptr;
		main.SRV->GetResource(Util::AsW32(&mainResource));
		if (!mainResource) {
			logger::error("[FOVEATED] Failed to acquire main resource for sharpening");
			return false;
		}

		context->OMSetRenderTargets(0, nullptr, nullptr);
		upscaling.rcas.ApplySharpen(Util::AsReal(main.SRV), upscaling.sharpenerTexture->uav.get(), currentSharpness);
		context->CopyResource(mainResource, upscaling.sharpenerTexture->resource.get());
		mainResource->Release();

		if (globals::game::stateUpdateFlags) {
			globals::game::stateUpdateFlags->set(RE::BSGraphics::ShaderFlags::DIRTY_RENDERTARGET);
		}
		return true;
	}
'@

$new = @'
	bool Postprocess::ApplyDlssSharpening(Upscaling& upscaling)
	{
		if (!upscaling.IsDlssSharpeningEnabled())
			return true;

		auto context = globals::d3d::context;
		auto renderer = globals::game::renderer;
		if (!context || !renderer) {
			logger::error("[FOVEATED] Missing D3D context or renderer for DLSS sharpening");
			return false;
		}

		// Keep the original Upscaling-tab RCAS curve and 0..1 control semantics.
		float currentSharpness = (-2.0f * upscaling.settings.sharpnessDLSS) + 2.0f;
		currentSharpness = exp2(-currentSharpness);
		context->OMSetRenderTargets(0, nullptr, nullptr);

		// PerfMode + foveated DLSS writes the reconstructed display-resolution
		// image to testTexture. The previous foveated sharpening path always read
		// kMAIN, which is only the render-resolution bridge in this mode, so the
		// visible HMD output was not being sharpened. Reuse PerfMode's existing
		// display-resolution scratch: testTexture -> refraTempTex -> RCAS -> testTexture.
		auto& perfMode = upscaling.perfMode;
		if (perfMode.IsHookActive() && perfMode.GetTestTexture()) {
			if (!perfMode.GetTestTextureSRV() || !perfMode.GetTestTextureUAV() ||
				!perfMode.GetRefraTempTex() || !perfMode.GetRefraTempSRV()) {
				logger::error("[FOVEATED] Missing PerfMode display-resolution sharpening resources");
				return false;
			}

			context->CopyResource(perfMode.GetRefraTempTex(), perfMode.GetTestTexture());
			upscaling.rcas.ApplySharpen(perfMode.GetRefraTempSRV(), perfMode.GetTestTextureUAV(), currentSharpness);
			if (globals::game::stateUpdateFlags)
				globals::game::stateUpdateFlags->set(RE::BSGraphics::ShaderFlags::DIRTY_RENDERTARGET);
			return true;
		}

		// Non-PerfMode foveated route: kMAIN is the actual DLSS output. Preserve
		// the original sharpener scratch path and write its RCAS result back in place.
		if (!upscaling.sharpenerTexture || !upscaling.sharpenerTexture->uav ||
			!upscaling.sharpenerTexture->resource) {
			logger::error("[FOVEATED] Missing standard DLSS sharpener resources");
			return false;
		}

		auto& main = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kMAIN];
		if (!main.SRV) {
			logger::error("[FOVEATED] Missing main SRV for DLSS sharpening");
			return false;
		}

		ID3D11Resource* mainResource = nullptr;
		main.SRV->GetResource(Util::AsW32(&mainResource));
		if (!mainResource) {
			logger::error("[FOVEATED] Failed to acquire main resource for DLSS sharpening");
			return false;
		}

		upscaling.rcas.ApplySharpen(Util::AsReal(main.SRV), upscaling.sharpenerTexture->uav.get(), currentSharpness);
		context->CopyResource(mainResource, upscaling.sharpenerTexture->resource.get());
		mainResource->Release();

		if (globals::game::stateUpdateFlags)
			globals::game::stateUpdateFlags->set(RE::BSGraphics::ShaderFlags::DIRTY_RENDERTARGET);
		return true;
	}
'@
Replace-Exact $post $old $new

Write-Host 'v02 sharpening: verify original-only sharpening contract'
$postText = [IO.File]::ReadAllText((Resolve-Path $post)).Replace("`r`n", "`n")
if ($postText -notmatch 'CopyResource\(perfMode\.GetRefraTempTex\(\), perfMode\.GetTestTexture\(\)\)' -or
    $postText -notmatch 'rcas\.ApplySharpen\(perfMode\.GetRefraTempSRV\(\), perfMode\.GetTestTextureUAV\(\), currentSharpness\)') {
    throw 'Original foveated/PerfMode DLSS sharpening path was not repaired'
}

$headerText = [IO.File]::ReadAllText((Resolve-Path $header)).Replace("`r`n", "`n")
$fovText = [IO.File]::ReadAllText((Resolve-Path $foveated)).Replace("`r`n", "`n")
if ($headerText -match 'neuralRenderingSharpening' -or $headerText -match 'sharpeningPlacement' -or
    $fovText -match 'NR Sharpening' -or $fovText -match 'ApplyNeuralRenderingSharpening' -or
    $fovText -match 'neuralRenderingSharpening' -or $fovText -match '"before-NR"' -or $fovText -match '"after-NR"') {
    throw 'Separate NR sharpening settings/stage/UI still remain in generated source'
}

Write-Host 'v02 original Upscaling-tab DLSS sharpening repaired; separate NR sharpening removed.'
