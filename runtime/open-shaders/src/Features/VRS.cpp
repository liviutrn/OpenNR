#include "VRS.h"

#include "Globals.h"
#include "Hooks.h"
#include "State.h"
#include "Upscaling.h"
#include "Upscaling/NativeOpenVRGaze.h"
#include "Utils/UI.h"

#include <algorithm>
#include <cmath>

#include "RE/S/ShaderAccumulator.h"

// Terrain Blending compatibility: VRS is suspended around TB's deferred terrain passes.
// Note: VRS reduces pixel shader overhead at high resolutions but does not affect compute shader cost; further adaptation needed.

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
	VRS::Settings,
	vrEnableVRS,
	vrVRSSrsPreset,
	vrVRSLutPreset,
	vrVRSRingGrowthRate,
	vrEnableDirectionalRates,
	vrEnableBoundaryDither,
	vrEnableDiagnostics);

void VRS::PostPostLoad()
{
	if (!globals::game::isVR) {
		logger::info("[VRS] Not VR runtime, skipping hook installation");
		return;
	}

	const bool isGOG = !GetModuleHandle(L"steam_api64.dll");

	// Hook the same UpdateJitter call site as Upscaling.
	// write_thunk_call chains: VRS (last writer) → Upscaling → original.
	// VRS must be installed AFTER Upscaling (both in PostPostLoad via
	// ForEachLoadedFeature order) so VRS::thunk wraps and preserves
	// the Upscaling thunk in its func pointer.
	const std::uintptr_t steamJitterOffset = REL::Module::IsAtLeast(REL::Version(1, 7, 99, 0)) ? 0x133 : 0xE2;
	stl::write_thunk_call<Main_UpdateJitter>(REL::RelocationID(75460, 77245).address() + REL::Relocate<std::uintptr_t>(0xE5, isGOG ? 0x133 : steamJitterOffset, 0x104));

	// Hook BSShaderAccumulator::FinishAccumulatingDispatch (vtable 0x2A)
	// to disable VRS before the UI pass (renderMode 24), which runs at
	// display resolution and must not be affected by foveated cull.
	stl::write_vfunc<0x2A, Main_FinishAccumulatingDispatch>(
		RE::VTABLE_BSShaderAccumulator[0]);

	hardwareAvailable_ = true;
	logger::info("[VRS] Installed hooks (frame scoped)");
}

void VRS::Main_UpdateJitter::thunk(RE::BSGraphics::State* a_state)
{
	func(a_state);
	globals::features::vrs.UpdateVRShadingRateState();
}

void VRS::Main_FinishAccumulatingDispatch::thunk(RE::BSGraphics::BSShaderAccumulator* shaderAccumulator, uint32_t renderFlags)
{
	// renderMode 24 = UI pass, which runs at display resolution (DRS=1.0).
	// VRS must be disabled before the UI pass to avoid foveated cull/low-rate
	// artifacts on HUD elements.
	if (shaderAccumulator && shaderAccumulator->GetRuntimeData().renderMode == 24) {
		globals::features::vrs.DisableVRShadingRateState();
	}
	func(shaderAccumulator, renderFlags);
}

void VRS::DrawSettings()
{
	settings.vrEnableVRS = std::min(settings.vrEnableVRS, 1u);
	bool enableVRS = settings.vrEnableVRS != 0;
	if (ImGui::Checkbox("Enable NVAPI VRS", &enableVRS))
		settings.vrEnableVRS = enableVRS ? 1u : 0u;
	ImGui::TextDisabled("Optional VR pixel-shading reduction. Default: off.");
	if (!enableVRS)
		Util::Text::WrappedInfo("VRS is idle: it does not initialize NVAPI or allocate a shading-rate surface until enabled.");
	if (auto _tt = Util::HoverTooltipWrapper()) {
		ImGui::Text("Reduces pixel shading rate in peripheral vision using concentric elliptical zones.");
		ImGui::Text("Directional-adaptive rates (2x1/1x2) preserve detail along natural eye-tracking axes.");
		ImGui::Text("Terrain Blending: terrain always renders at 1x1 when TB is active.");
		ImGui::Text("Requires an NVIDIA driver exposing NVAPI Variable Pixel Rate Shading.");
	}

	settings.vrVRSSrsPreset = std::min(settings.vrVRSSrsPreset, 2u);
	const char* srsPresets[] = { "Default", "Faster", "Extreme" };
	ImGui::SliderInt("VRS Rate Preset", (int*)&settings.vrVRSSrsPreset, 0, 2, srsPresets[settings.vrVRSSrsPreset]);
	static constexpr const char* kPresetHint[] = {
		"6 rings: 1x1 > Half > 2x2 > Eighth > 4x4 > Cull",
		"4 rings: 1x1 > 2x2 > 4x4 > Cull",
		"3 rings: 1x1 > 4x4 > Cull",
	};
	ImGui::TextDisabled("%s", kPresetHint[settings.vrVRSSrsPreset]);

	settings.vrVRSLutPreset = std::min(settings.vrVRSLutPreset, 2u);
	const char* lutPresets[] = { "Default", "Full 1x1 (debug)", "Full 4x4 (debug)" };
	ImGui::SliderInt("LUT Override", (int*)&settings.vrVRSLutPreset, 0, 2, lutPresets[settings.vrVRSLutPreset]);
	if (auto _ttLutOvr = Util::HoverTooltipWrapper()) {
		ImGui::Text("Default: normal mapping. Debug overrides force a single uniform rate.");
	}

	ImGui::Checkbox("Directional Rates", &settings.vrEnableDirectionalRates);
	if (auto _ttDir = Util::HoverTooltipWrapper()) {
		ImGui::Text("Adapts shading orientation to human peripheral vision: preserves horizontal");
		ImGui::Text("detail on left/right edges, vertical detail on top/bottom edges.");
	}
	ImGui::Checkbox("Boundary Dither", &settings.vrEnableBoundaryDither);
	if (auto _ttDith = Util::HoverTooltipWrapper()) {
		ImGui::Text("Checkerboard dithering at ring boundaries to soften transitions.");
	}

	ImGui::SliderFloat("Ring Growth Rate", &settings.vrVRSRingGrowthRate, 0.05f, 1.0f, "%.2f");
	ImGui::TextDisabled("How fast quality drops from center to edge. Smaller = more gradual, larger = sharper drop.");
	if (auto _ttRing = Util::HoverTooltipWrapper()) {
		ImGui::Text("0.25 means each ring is 25%% wider than the previous one.");
		ImGui::Text("Lower values create more rings with gentler transitions.");
	}

	{
		ImGui::Separator();
		ImGui::TextColored(ImVec4(1.0f, 0.9f, 0.3f, 1.0f), "VRS shares the Upscaling foveated region (per-eye). Full Eye means no VRS savings.");
		ImGui::TextDisabled("Use the same subrect as Foveated Upscaling/Screenshot when you want matching coverage.");
		auto& subrect = globals::features::upscaling.foveatedRender.subrectController;
		if (ImGui::Button("Use Center 75%%"))
			subrect.ApplyPresetByName(FoveatedRender::kPresetCenter75);
		ImGui::SameLine();
		if (ImGui::Button("Use Center 50%%"))
			subrect.ApplyPresetByName(FoveatedRender::kPresetCenter50);
		const auto& leftUV = subrect.GetUV();
		const auto& rightUV = subrect.GetRightEyeUV();
		if (leftUV.IsFullEye() && rightUV.IsFullEye())
			Util::Text::Warning("Shared subrect is Full Eye; VRS will remain effectively 1x1 until a cropped region is selected.");
		ID3D11ShaderResourceView* previewSrv = nullptr;
		ID3D11Texture2D* previewTex = nullptr;
		if (auto renderer = globals::game::renderer) {
			auto& framebuffer = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kVR_FRAMEBUFFER];
			previewSrv = framebuffer.SRV;
			previewTex = static_cast<ID3D11Texture2D*>(framebuffer.texture);
		}
		subrect.DrawEditor(previewSrv, previewTex, 0.5f, 0.0f, Util::Subrect::OpaquePreviewBlendCallback);
	}

	ImGui::Checkbox("Enable Diagnostics", &settings.vrEnableDiagnostics);
	if (auto _ttDiag = Util::HoverTooltipWrapper()) {
		ImGui::Text("Enable tile statistics, debug visualization, and diagnostics panel.");
		ImGui::Text("Adds minor per-rebuild overhead (~80KB upload + O(tiles) stats).");
	}

	if (settings.vrEnableDiagnostics && ImGui::TreeNodeEx("VRS Diagnostics")) {
		auto vrsState = nvVrs.GetDebugState();
		auto activeRateLabel = [](uint32_t level) -> const char* {
			switch (level) {
			case 0:
				return "1x1";
			case 1:
				return "2x1";
			case 2:
				return "1x2";
			case 3:
				return "2x2";
			case 4:
				return "4x2";
			case 5:
				return "2x4";
			case 6:
				return "4x4";
			case 7:
				return "Cull";
			default:
				return "Unknown";
			}
		};
		auto drawLegendRow = [](const char* label, const char* rate, ImVec4 color) {
			ImGui::ColorButton(label, color, ImGuiColorEditFlags_NoTooltip | ImGuiColorEditFlags_NoDragDrop, ImVec2(14.0f, 14.0f));
			ImGui::SameLine();
			ImGui::Text("%s -> %s", label, rate);
		};

		ImGui::Text("NVAPI: %s | Active: %s", vrsState.supported ? "OK" : (vrsState.initialized ? "Unsupported" : "Not Init"), vrsState.active ? "Yes" : "No");
		ImGui::Text("Surface: %u x %u  Viewports: %u", vrsState.tileWidth, vrsState.tileHeight, vrsState.lastViewportCount);
		ImGui::Text("Pattern Rebuild/Reuse: %llu / %llu", vrsState.patternRebuildCount, vrsState.patternReuseCount);

		static constexpr const char* kDisableReasons[] = { "None", "SettingsDisabled", "InvalidContext", "InitFailed", "SurfaceFailed", "BindSurfaceFailed", "BindRateTableFailed", "UIPass", "TerrainBlending" };
		static constexpr const char* kRebuildReasons[] = { "None", "FirstCreate", "ResolutionChanged" };
		const auto drIdx = static_cast<uint32_t>(vrsState.lastDisableReason);
		const auto rrIdx = static_cast<uint32_t>(vrsState.lastRebuildReason);
		ImGui::Text("Disable: %s  Rebuild: %s", drIdx < std::size(kDisableReasons) ? kDisableReasons[drIdx] : "?", rrIdx < std::size(kRebuildReasons) ? kRebuildReasons[rrIdx] : "?");

		if (vrsState.failureCount > 0) {
			ImGui::TextColored(ImVec4(1, 0.3f, 0.3f, 1), "Failures: %llu  Last: %s (nvapi=%d)", vrsState.failureCount, vrsState.lastFailureSite, vrsState.lastNvapiStatus);
		}

		ImGui::Text("Tiles: %llu / %llu / %llu / %llu / %llu / %llu / %llu / %llu",
			vrsState.lastTileLevelCount[0],
			vrsState.lastTileLevelCount[1],
			vrsState.lastTileLevelCount[2],
			vrsState.lastTileLevelCount[3],
			vrsState.lastTileLevelCount[4],
			vrsState.lastTileLevelCount[5],
			vrsState.lastTileLevelCount[6],
			vrsState.lastTileLevelCount[7]);
		ImGui::Separator();
		ImGui::Text("SRS Legend");
		drawLegendRow("L0", activeRateLabel(0), ImVec4(0.20f, 0.85f, 0.35f, 1.0f));
		drawLegendRow("L1", activeRateLabel(1), ImVec4(0.20f, 0.75f, 0.85f, 1.0f));
		drawLegendRow("L2", activeRateLabel(2), ImVec4(0.75f, 0.85f, 0.20f, 1.0f));
		drawLegendRow("L3", activeRateLabel(3), ImVec4(0.95f, 0.80f, 0.20f, 1.0f));
		drawLegendRow("L4", activeRateLabel(4), ImVec4(0.98f, 0.55f, 0.15f, 1.0f));
		drawLegendRow("L5", activeRateLabel(5), ImVec4(0.95f, 0.45f, 0.30f, 1.0f));
		drawLegendRow("L6", activeRateLabel(6), ImVec4(0.86f, 0.22f, 0.22f, 1.0f));
		drawLegendRow("L7", activeRateLabel(7), ImVec4(0.30f, 0.30f, 0.30f, 1.0f));

		if (auto* debugSRV = nvVrs.GetDebugVisualizationSRV()) {
			ImGui::Separator();
			ImGui::Text("SRS Debug Visualization");
			const float maxW = 800.0f;
			const float aspect = static_cast<float>(vrsState.tileHeight) / std::max(static_cast<float>(vrsState.tileWidth), 1.0f);
			const float displayW = std::min(static_cast<float>(vrsState.tileWidth) * 4.0f, maxW);
			const float displayH = displayW * aspect;
			ImGui::Image(reinterpret_cast<ImTextureID>(debugSRV),
				ImVec2(displayW, displayH));
		}
		ImGui::TreePop();
	}
}

void VRS::SaveSettings(json& o_json)
{
	o_json = settings;
	// The crop region is owned and persisted by Upscaling::FoveatedRender.
}

void VRS::LoadSettings(json& o_json)
{
	settings = o_json;

	if (settings.vrEnableVRS > 1) {
		logger::warn("[VRS] Loaded vrEnableVRS {} out of range, clamping to 1", settings.vrEnableVRS);
		settings.vrEnableVRS = 1;
	}
	if (settings.vrVRSSrsPreset > 2) {
		logger::warn("[VRS] Loaded vrVRSSrsPreset {} out of range, clamping to 2", settings.vrVRSSrsPreset);
		settings.vrVRSSrsPreset = 2;
	}
	if (settings.vrVRSLutPreset > 2) {
		logger::warn("[VRS] Loaded vrVRSLutPreset {} out of range, clamping to 2", settings.vrVRSLutPreset);
		settings.vrVRSLutPreset = 2;
	}
	if (settings.vrVRSRingGrowthRate < 0.05f || settings.vrVRSRingGrowthRate > 1.0f) {
		logger::warn("[VRS] Loaded vrVRSRingGrowthRate {} out of range, clamping", settings.vrVRSRingGrowthRate);
		settings.vrVRSRingGrowthRate = std::clamp(settings.vrVRSRingGrowthRate, 0.05f, 1.0f);
	}
}

void VRS::RestoreDefaultSettings()
{
	settings = {};
}

void VRS::Reset()
{
	nvVrs.Disable(globals::d3d::context);
}

void VRS::OnSceneTransitionReset(bool /*opening*/)
{
	nvVrs.Disable(globals::d3d::context);
}

json VRS::GetDiagnostics()
{
	const auto& state = nvVrs.GetDebugState();
	return {
		{ "enabled", settings.vrEnableVRS != 0 },
		{ "hooksInstalled", hardwareAvailable_ },
		{ "nvapiInitialized", state.initialized },
		{ "supported", state.supported },
		{ "active", state.active },
		{ "tileWidth", state.tileWidth },
		{ "tileHeight", state.tileHeight },
		{ "lastViewportCount", state.lastViewportCount },
		{ "patternRebuildCount", state.patternRebuildCount },
		{ "patternReuseCount", state.patternReuseCount },
		{ "failureCount", state.failureCount },
		{ "lastFailureSite", state.lastFailureSite ? state.lastFailureSite : "None" },
		{ "lastNvapiStatus", state.lastNvapiStatus },
		{ "lastDisableReason", static_cast<uint32_t>(state.lastDisableReason) },
		{ "lastRebuildReason", static_cast<uint32_t>(state.lastRebuildReason) }
	};
}

void VRS::UpdateVRShadingRateState()
{
	if (!globals::game::isVR || !loaded || !hardwareAvailable_ || !globals::state || !globals::features::upscaling.loaded) {
		nvVrs.Disable(globals::d3d::context);
		return;
	}

	auto& upscaling = globals::features::upscaling;
	NvVrsController::Settings vrsSettings{};
	const bool menuOpen = globals::state->IsPausedOrMenuOpen(globals::game::ui);
	vrsSettings.enable = settings.vrEnableVRS != 0 && !globals::state->isLoadingMenuOpen && !menuOpen;
	vrsSettings.srsPreset = settings.vrVRSSrsPreset;
	vrsSettings.lutPreset = settings.vrVRSLutPreset;
	vrsSettings.ringGrowthRate = settings.vrVRSRingGrowthRate;
	vrsSettings.enableDirectionalRates = settings.vrEnableDirectionalRates;
	vrsSettings.enableBoundaryDither = settings.vrEnableBoundaryDither;
	vrsSettings.enableDiagnostics = settings.vrEnableDiagnostics;

	float2 displaySize = globals::state->screenSize;
	float2 renderSize = { displaySize.x * upscaling.resolutionScale.x, displaySize.y * upscaling.resolutionScale.y };
	if (upscaling.perfMode.IsHookActive()) {
		displaySize = upscaling.perfMode.GetDisplayScreenSize();
		renderSize = { static_cast<float>(upscaling.perfMode.GetRenderEyeWidth() * 2u), static_cast<float>(upscaling.perfMode.GetRenderEyeHeight()) };
	}
	if (!std::isfinite(displaySize.x) || !std::isfinite(displaySize.y) || !std::isfinite(renderSize.x) || !std::isfinite(renderSize.y)) {
		nvVrs.Disable(globals::d3d::context);
		return;
	}

	NvVrsController::FrameInfo frameInfo{};
	frameInfo.displayWidth = std::max(static_cast<int>(displaySize.x), 1);
	frameInfo.displayHeight = std::max(static_cast<int>(displaySize.y), 1);
	frameInfo.renderWidth = std::max(static_cast<int>(renderSize.x), 1);
	frameInfo.renderHeight = std::max(static_cast<int>(renderSize.y), 1);
	auto& foveated = upscaling.foveatedRender;
	auto leftUV = foveated.GetEffectiveLeftUV();
	auto rightUV = foveated.GetEffectiveRightUV();
	if (vrsSettings.enable && foveated.IsActive() && foveated.settings.neuralRenderingEyeTrackedFoveation &&
		foveated.settings.neuralRenderingEnabled && foveated.GetDlssMode() == FoveatedRender::DlssMode::kDefault &&
		upscaling.GetUpscaleMethod() == Upscaling::UpscaleMethod::kDLSS) {
		const FoveatedRenderImpl::NativeOpenVRGaze::Config config{
			.enabled = true,
			.smoothingMs = foveated.settings.neuralRenderingEyeTrackedSmoothingMs,
			.quantizationPixels = foveated.settings.neuralRenderingEyeTrackedQuantizationPixels,
			.cropPaddingPixels = foveated.settings.neuralRenderingEyeTrackedCropPaddingPixels,
		};
		const auto gaze = FoveatedRenderImpl::NativeOpenVRGaze::ResolveForFrame(config, leftUV, rightUV,
			frameInfo.renderWidth / 2, frameInfo.renderHeight, globals::state->frameCount,
			FoveatedRenderImpl::NativeOpenVRGaze::IsDynamicGazeAllowed());
		leftUV = gaze.leftUV;
		rightUV = gaze.rightUV;
	}
	vrsSettings.leftSubrectUV = { leftUV.x, leftUV.y, leftUV.w, leftUV.h };
	vrsSettings.rightSubrectUV = { rightUV.x, rightUV.y, rightUV.w, rightUV.h };

	nvVrs.Update(vrsSettings, frameInfo, globals::d3d::device, globals::d3d::context);
}

void VRS::DisableVRShadingRateState()
{
	nvVrs.SetLastDisableReason(NvVrsController::DisableReason::UIPass);
	nvVrs.Disable(globals::d3d::context);
}

void VRS::SuspendVRS()
{
	nvVrs.SetLastDisableReason(NvVrsController::DisableReason::TerrainBlending);
	nvVrs.Suspend(globals::d3d::context);
}

void VRS::ResumeVRS()
{
	nvVrs.Resume(globals::d3d::context);
}
