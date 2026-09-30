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

# Eye tracking owns position; adaptive crop now scales the live gaze crop size.
$old = 'drawWrapped("Order: crop → NR → crop. NR restores before crop expands. Eye-tracked foveation disables adaptive crop.");'
$new = 'drawWrapped("Order: crop → NR → crop. With eye tracking, gaze owns the crop center while the adaptive controller scales the live gaze crop size.");'
Replace-Exact $foveated $old $new

$old = 'drawWrapped("Maximum is independent of the static crop preset; it is the tier used when adaptive crop is re-armed.");'
$new = 'drawWrapped("Maximum is the controller reference tier. With eye tracking it represents 100% of your configured gaze crop; lower adaptive tiers scale that live crop around the gaze center.");'
Replace-Exact $foveated $old $new

$old = @'
				if (IsEyeTrackedFoveationEnabled())
					drawWarningWrapped("Adaptive crop is disabled while eye-tracked foveation owns the crop.");
'@
$new = @'
				if (IsEyeTrackedFoveationEnabled())
					drawDisabledWrapped("Eye tracking owns crop position; adaptive crop changes only the live gaze-crop size.");
'@
Replace-Exact $foveated $old $new

# PRE-SR is retired in v01 and ClampSettings normalizes it off. Remove the stale UI.
$old = @'
				bool preUpscale = settings.neuralRenderingPreUpscale != 0;
				if (ImGui::Checkbox(T(TKEY("neural_rendering_pre_upscale"), "Experimental pre-upscale NR"), &preUpscale))
					settings.neuralRenderingPreUpscale = preUpscale ? 1u : 0u;
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped(T(TKEY("neural_rendering_pre_upscale_tooltip"), "Runs NR before DLSS. It may reduce halos but can change color and is incompatible with Ray Reconstruction. VR requires Full Eye + Default mode."));
				if (settings.neuralRenderingPreUpscale)
					drawWarningWrapped(T(TKEY("neural_rendering_pre_upscale_warning"), "Experimental. Disable Ray Reconstruction and use Full Eye + Default mode."));
'@
$new = @'
				drawDisabledWrapped("v01 pipeline order is fixed: game → SR → NR pass 1 → optional NR pass 2. PRE-SR NR is retired.");
'@
Replace-Exact $foveated $old $new

# Replace the old screenshot-only multipass UI with the actual v01 sequential controls.
$old = @'
				static const char* multiPassModes[] = { "Off", "2x sequential NR", "3x sequential NR" };
				int multiPass = static_cast<int>(std::min(settings.neuralRenderingMultiPass, 2u));
				if (ImGui::Combo(T(TKEY("neural_rendering_multi_pass"), "Experimental sequential NR (screenshot/benchmark)"),
					&multiPass, multiPassModes, IM_ARRAYSIZE(multiPassModes)))
					settings.neuralRenderingMultiPass = static_cast<uint>(multiPass);
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped(T(TKEY("neural_rendering_multi_pass_tooltip"), "Runs NR two or three times with separate resources. This roughly doubles or triples work and is intended for screenshots or benchmarks."));
				if (settings.neuralRenderingMultiPass) {
					if (settings.neuralRenderingMultiPass >= 2)
						drawWarningWrapped(T(TKEY("neural_rendering_multi_pass_warning"), "Experimental 3x: very large frame-time and VRAM increase."));
					else
						drawWarningWrapped(T(TKEY("neural_rendering_multi_pass_warning"), "Experimental 2x: major frame-time increase and possible smearing."));
					if (settings.neuralRenderingPreUpscale)
						drawWarningWrapped(T(TKEY("neural_rendering_multi_pass_pre_warning"), "Sequential NR is suppressed while pre-upscale NR is enabled."));
					if (globals::game::isVR && !(subrectController.GetUV().IsFullEye() && subrectController.GetRightEyeUV().IsFullEye()))
						drawWarningWrapped(T(TKEY("neural_rendering_multi_pass_subrect_warning"), "VR sequential NR is limited to Full Eye mode."));
				}
'@
$new = @'
				static const char* multiPassModes[] = { "Off", "2x sequential NR", "3x sequential NR" };
				int multiPass = static_cast<int>(std::min(settings.neuralRenderingMultiPass, 2u));
				if (ImGui::Combo(T(TKEY("neural_rendering_multi_pass"), "Sequential NR"),
					&multiPass, multiPassModes, IM_ARRAYSIZE(multiPassModes))) {
					settings.neuralRenderingMultiPass = static_cast<uint>(multiPass);
					NeuralRendering::RequestHistoryReset();
				}
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped("2x sequential uses independent native Feature18 histories. It works with full eye, fixed crop, adaptive crop and eye-tracked gaze. Pass 2 can be a smaller region relative to the live pass-1 crop.");

				if (settings.neuralRenderingMultiPass) {
					if (settings.neuralRenderingMultiPass >= 2)
						drawWarningWrapped("3x remains a high-cost experimental path. A reduced pass 2 automatically limits the route to 2x.");
					else
						drawDisabledWrapped("2x: pass 1 and pass 2 evaluate every eye every frame; no alternate-eye reuse.");

					ImGui::SeparatorText("Sequential Pass 2");
					static constexpr uint pass2CoverageValues[] = { 100u, 90u, 80u, 70u, 60u, 50u };
					static const char* pass2CoverageLabels[] = { "100%", "90%", "80%", "70%", "60%", "50%" };
					int pass2CoverageIndex = 0;
					for (int index = 0; index < IM_ARRAYSIZE(pass2CoverageValues); ++index)
						if (settings.neuralRenderingPass2.coveragePercent == pass2CoverageValues[index]) {
							pass2CoverageIndex = index;
							break;
						}
					if (ImGui::Combo("Pass 2 coverage (relative to pass 1)", &pass2CoverageIndex,
						pass2CoverageLabels, IM_ARRAYSIZE(pass2CoverageLabels))) {
						settings.neuralRenderingPass2.coveragePercent = pass2CoverageValues[pass2CoverageIndex];
						NeuralRendering::RequestHistoryReset();
					}
					if (auto _tt = Util::HoverTooltipWrapper())
						drawWrapped("Relative to the live pass-1 crop. Example: pass 1 at 50% gaze crop and pass 2 at 70% gives about 35% of the full eye.");

					static const char* pass2Presets[] = { "Default", "Balanced", "Fabric Detail", "Natural", "Custom" };
					static constexpr uint pass2PresetValues[] = { 0u, 1u, 2u, 3u, 5u };
					int pass2PresetIndex = 0;
					for (int index = 0; index < IM_ARRAYSIZE(pass2PresetValues); ++index)
						if (settings.neuralRenderingPass2.preset == pass2PresetValues[index]) {
							pass2PresetIndex = index;
							break;
						}
					if (ImGui::Combo("Pass 2 model preset", &pass2PresetIndex, pass2Presets, IM_ARRAYSIZE(pass2Presets))) {
						auto& p2 = settings.neuralRenderingPass2;
						p2.preset = pass2PresetValues[pass2PresetIndex];
						switch (p2.preset) {
						case 0: p2.intensity = 1.70f; p2.localTone = 1.00f; p2.localStructure = 1.70f; p2.skinStructure = -1.0f; p2.style = 0; p2.autoMask = true; break;
						case 1: p2.intensity = 1.00f; p2.localTone = 1.00f; p2.localStructure = 1.00f; p2.skinStructure = 1.00f; break;
						case 2: p2.intensity = 1.35f; p2.localTone = 0.90f; p2.localStructure = 1.60f; p2.skinStructure = 1.15f; break;
						case 3: p2.intensity = 0.80f; p2.localTone = 0.75f; p2.localStructure = 0.90f; p2.skinStructure = 0.90f; break;
						default: break;
						}
					}
					bool pass2Custom = false;
					int pass2Style = static_cast<int>(std::min(settings.neuralRenderingPass2.style, 2u));
					pass2Custom |= ImGui::Combo("Pass 2 visual style", &pass2Style, styleLabels, IM_ARRAYSIZE(styleLabels));
					settings.neuralRenderingPass2.style = static_cast<uint>(pass2Style);
					pass2Custom |= ImGui::SliderFloat("Pass 2 intensity", &settings.neuralRenderingPass2.intensity, 0.0f, 2.0f, "%.2f");
					pass2Custom |= ImGui::SliderFloat("Pass 2 local tone", &settings.neuralRenderingPass2.localTone, 0.0f, 2.0f, "%.2f");
					pass2Custom |= ImGui::SliderFloat("Pass 2 local structure", &settings.neuralRenderingPass2.localStructure, 0.0f, 2.0f, "%.2f");
					pass2Custom |= ImGui::SliderFloat("Pass 2 skin structure", &settings.neuralRenderingPass2.skinStructure, -1.0f, 2.0f, "%.2f");
					pass2Custom |= ImGui::Checkbox("Pass 2 Automatic Mask", &settings.neuralRenderingPass2.autoMask);
					pass2Custom |= ImGui::Checkbox("Pass 2 UI Correction", &settings.neuralRenderingPass2.uiCorrection);
					if (pass2Custom)
						settings.neuralRenderingPass2.preset = 5;

					static const char* pass2BlendModes[] = { "Hard Copy", "Feather", "Dither" };
					int pass2Blend = static_cast<int>(std::min(settings.neuralRenderingPass2.blendMode, 2u));
					if (ImGui::Combo("Pass 2 edge blend", &pass2Blend, pass2BlendModes, IM_ARRAYSIZE(pass2BlendModes)))
						settings.neuralRenderingPass2.blendMode = static_cast<uint>(pass2Blend);
					static const char* pass2MaskModes[] = { "Rectangle", "Oval" };
					int pass2Mask = static_cast<int>(std::min(settings.neuralRenderingPass2.maskMode, 1u));
					if (ImGui::Combo("Pass 2 edge shape", &pass2Mask, pass2MaskModes, IM_ARRAYSIZE(pass2MaskModes)))
						settings.neuralRenderingPass2.maskMode = static_cast<uint>(pass2Mask);
					if (settings.neuralRenderingPass2.blendMode != 0) {
						ImGui::SliderFloat("Pass 2 feather width", &settings.neuralRenderingPass2.featherWidth, 2.0f, 128.0f, "%.0f px");
						ImGui::SliderFloat("Pass 2 falloff", &settings.neuralRenderingPass2.falloffCurve, 0.5f, 2.0f, "%.2f");
						if (settings.neuralRenderingPass2.blendMode == 2)
							ImGui::SliderFloat("Pass 2 dither strength", &settings.neuralRenderingPass2.ditherStrength, 0.0f, 2.0f, "%.2f");
					}
				}

				ImGui::SeparatorText("Stereo Atlas");
				bool atlas = settings.neuralRenderingStereoAtlas;
				if (ImGui::Checkbox("Stereo atlas (experimental)", &atlas)) {
					settings.neuralRenderingStereoAtlas = atlas;
					NeuralRendering::RequestHistoryReset();
				}
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped("Packs LEFT | replicated-edge guard | RIGHT and runs one native Feature18 evaluation per sequential pass. Normal independent-eye stereo remains the fallback/A-B path.");
				if (settings.neuralRenderingStereoAtlas) {
					int atlasGuard = static_cast<int>(settings.neuralRenderingStereoAtlasGuardPixels);
					if (ImGui::SliderInt("Atlas guard width", &atlasGuard, 8, 256, "%d px")) {
						settings.neuralRenderingStereoAtlasGuardPixels = static_cast<uint>(atlasGuard);
						NeuralRendering::RequestHistoryReset();
					}
					drawDisabledWrapped("Default 50 px. Guard halves replicate the adjacent eye edge and are discarded when atlas output is split.");
					if (settings.neuralRenderingMultiPass >= 2)
						drawWarningWrapped("Stereo atlas currently supports single-pass and 2x sequential. 3x falls back to independent-eye stereo.");
					if (settings.neuralRenderingTemporalReuseCadence != 0)
						drawWarningWrapped("Temporal residual-reuse modes fall back to independent-eye stereo while atlas is enabled.");
				}
'@
Replace-Exact $foveated $old $new

Write-Host 'v01 UI controls applied successfully.'
