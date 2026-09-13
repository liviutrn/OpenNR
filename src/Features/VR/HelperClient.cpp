// VR feature's ImGuiVRHelper client: wraps the client SDK with Community Shaders
// glue (keybind<->combo mapping, rebind persistence, Menu::IsEnabled, status HUD).
// Two clients: the focus-driven menu and the always-on status HUD.

#include "Features/VR.h"

#include <algorithm>
#include <format>
#include <imgui.h>

#include "Globals.h"
#include "ImGuiVRHelperClientSDK.h"
#include "Menu.h"
#include "Menu/OverlayRenderer.h"
#include "Menu/ThemeManager.h"
#include "State.h"
#include "Utils/Input.h"

namespace
{
	namespace API = ImGuiVRHelperPluginAPI;
	constexpr auto kClientName = "OpenNR";

	// One VR feature singleton, so a single client of each kind is file-local.
	API::Client g_client;  // focus-driven menu client
	API::Client g_hud;     // always-on HUD-mode client (status overlays)
	bool g_hudConnected = false;

	bool g_combosRegistered = false;
	API::ComboId g_overlayOpenCombo = 0;
	API::ComboId g_overlayCloseCombo = 0;

	// ButtonCombo and API::InputCombo are layout-compatible but distinct types.
	std::vector<API::InputCombo> ToApi(const std::vector<ButtonCombo>& binds)
	{
		std::vector<API::InputCombo> out;
		out.reserve(binds.size());
		for (const auto& b : binds)
			out.emplace_back(static_cast<API::InputDeviceType>(static_cast<uint32_t>(b.GetDevice())), b.GetKey());
		return out;
	}

	// On rebind: write the chord back into the settings vector and persist.
	API::Client::RebindCallback MakePersist(std::vector<ButtonCombo>& target)
	{
		return [&target](const API::InputCombo* keys, std::size_t n) {
			target.clear();
			target.reserve(n);
			for (std::size_t i = 0; i < n; ++i)
				target.emplace_back(static_cast<InputDeviceType>(static_cast<uint32_t>(keys[i].GetDevice())), keys[i].GetKey());
			if (globals::state)
				globals::state->Save(State::ConfigMode::USER);
			logger::info("ImGuiVRHelper: persisted VR combo rebind ({} keys)", n);
		};
	}

	// Lazy so settings are loaded. Menu open/close are the helper's; we keep only
	// the secondary in-menu overlay toggle. defaults enable the table's Reset.
	void EnsureCombosRegistered()
	{
		if (g_combosRegistered)
			return;
		auto& s = globals::features::vr.settings;
		const VR::Settings d{};
		g_overlayOpenCombo = g_client.AddCombo("Open overlay", ToApi(s.VROverlayOpenKeys),
			MakePersist(s.VROverlayOpenKeys), ToApi(d.VROverlayOpenKeys));
		g_overlayCloseCombo = g_client.AddCombo("Close overlay", ToApi(s.VROverlayCloseKeys),
			MakePersist(s.VROverlayCloseKeys), ToApi(d.VROverlayCloseKeys));
		g_combosRegistered = true;
		logger::info("ImGuiVRHelper: registered VR overlay combos (overlayOpen={}, overlayClose={})",
			g_overlayOpenCombo, g_overlayCloseCombo);
	}
}

void VR::ConnectHelper()
{
	if (!globals::game::isVR)
		return;
	// RendersOnFocus: render into the panel whenever the helper grants focus, even
	// if Menu::IsEnabled is false. OwnCursor: keep drawing our own ImGui cursor in
	// VR too (content-aware per hovered widget, and honors Theme.UseCustomCursor)
	// instead of the helper's composited pointer.
	const auto clientName = std::string(kClientName);
	const auto versionStr = std::format("{}.{}.{}", Plugin::VERSION.major(), Plugin::VERSION.minor(), Plugin::VERSION.patch());
	if (!g_client.Connect(clientName.c_str(), versionStr.c_str(),
			API::kClientFlag_RendersOnFocus | API::kClientFlag_OwnCursor)) {
		logger::warn("ImGuiVRHelper not detected; VR menus remain desktop-only. Install the bundled ImGuiVRHelper v1.7.0 runtime plugin.");
		return;
	}
	logger::info("ImGuiVRHelper handshake successful (build {}), client_id={}, vr_keyboard={}",
		g_client.Helper()->GetBuildNumber(), g_client.Id(), g_client.HasKeyboard());
}

bool VR::IsHelperRegistered() const { return g_client.IsConnected(); }
bool VR::HelperRequestsRender() const { return g_client.HasFocus(); }

void VR::RenderHelperToPanel() { g_client.RenderToPanel(); }

void VR::FeedHelperEvent(uint32_t device, uint32_t key, bool pressed, float stickX, float stickY)
{
	g_client.FeedVREvent(device, key, pressed, stickX, stickY);
}

void VR::DrawHelperBindingsTable() { g_client.DrawBindingsTable(); }

bool VR::GetHelperPanelSize(uint32_t& width, uint32_t& height) const
{
	if (!g_client.IsConnected() || !g_client.Helper())
		return false;
	API::PanelHandle panel{};
	// GetPanel allocates the panel RTV lazily (after the helper's D3D init), so
	// this returns false until then — callers fall back to the desktop path.
	if (!g_client.Helper()->GetPanel(g_client.Id(), &panel) || !panel.width || !panel.height)
		return false;
	width = panel.width;
	height = panel.height;
	return true;
}

void VR::UpdateHelper()
{
	if (!g_client.IsConnected())
		return;

	EnsureCombosRegistered();

	auto* menu = globals::menu;
	if (!menu) {
		g_client.PumpInput(false);
		return;
	}

	// Focus is the single source of truth for VR menu visibility; reconcile it with
	// our menu-open flag both ways.
	g_client.ReconcileFocus(menu->IsEnabled);
	const bool focused = g_client.HasFocus();

	if (focused) {
		if (g_client.Fired(g_overlayOpenCombo))
			menu->overlayVisible = true;
		if (g_client.Fired(g_overlayCloseCombo))
			menu->overlayVisible = false;
	} else if (g_overlayOpenCombo || g_overlayCloseCombo) {
		// Drain latches while closed so they don't fire stale on reopen.
		g_client.Fired(g_overlayOpenCombo);
		g_client.Fired(g_overlayCloseCombo);
	}

	// The active PumpKeyboard/PumpInput calls must happen after the DX11 and
	// Win32 ImGui backends have started this frame. OverlayRenderer performs that
	// late pump immediately before ImGui::NewFrame(). Keep only the helper's
	// inactive release/parking path here when there is no focused panel, because
	// closed overlays do not start an ImGui frame at all.
	if (!focused && !menu->IsEnabled)
		g_client.PumpInput(false);
}

void VR::PumpHelperInput(bool panelReady)
{
	if (!g_client.IsConnected())
		return;

	auto* menu = globals::menu;
	if (!menu || !panelReady) {
		g_client.PumpInput(false);
		return;
	}

	const bool active = menu->IsEnabled || g_client.HasFocus();
	if (!active) {
		g_client.PumpInput(false);
		return;
	}

	// Automatic VR text entry and wand/controller input are ImGui-IO operations.
	// They intentionally run after ImGui_ImplWin32_NewFrame() has injected the
	// desktop cursor. The helper owns the cursor only while the current wand ray
	// is actually on the VR panel; when it is off-panel, PumpInput(false) preserves
	// the desktop mouse position and buttons instead of parking the cursor.
	float pointerU = 0.0f;
	float pointerV = 0.0f;
	const bool pointerInPanel = g_client.Helper() &&
		g_client.Helper()->GetPointer(g_client.Id(), &pointerU, &pointerV, nullptr);
	g_client.PumpKeyboard();
	const float clampedDeadzone = std::clamp(settings.mouseDeadzone, 0.0f, 1.0f);
	g_client.PumpInput(pointerInPanel, clampedDeadzone);
}

void VR::RenderStatusHud()
{
	if (!globals::game::isVR || !g_client.IsConnected())
		return;

	auto* menu = Menu::GetSingleton();
	if (!globals::d3d::device || !globals::d3d::context || !menu)
		return;

	if (!g_hudConnected) {
		const auto hudName = std::format("{}.HUD", kClientName);
		const auto versionStr = std::format("{}.{}.{}", Plugin::VERSION.major(), Plugin::VERSION.minor(), Plugin::VERSION.patch());
		if (!g_hud.Connect(hudName.c_str(), versionStr.c_str(),
				API::kClientFlag_HUDMode))
			return;
		// Font first: SetupImGuiStyle reads io.FontDefault to scale style metrics,
		// so it must see the real font, not this context's just-created default.
		// LoadStandaloneFont, not ReloadFont: the latter's ImFont* writes into
		// menu.loadedFontRoles corrupt the main menu context reading that cache.
		g_hud.SetHudStyleCallback([menu]() {
			ThemeManager::LoadStandaloneFont(*menu);
			ThemeManager::SetupImGuiStyle(*menu);
		});
		g_hudConnected = true;
	}

	// A dedicated HUD context is load-bearing: rendering these on the menu's own
	// context would clear its input state each frame and break interaction.
	const bool menuShown = g_client.HasFocus() || menu->IsEnabled;
	const ImVec2 displaySize = ImGui::GetIO().DisplaySize;

	g_hud.RenderHud(globals::d3d::device, globals::d3d::context, displaySize, [menuShown]() {
		if (menuShown)
			return;  // menu renders the overlays itself; HUD stands down
		OverlayRenderer::RenderShaderCompilationStatus(
			[](std::vector<InputCombo> keys) -> const char* {
				static std::string cache;
				cache = Util::Input::KeyIdToString(keys);
				return cache.c_str();
			});
		OverlayRenderer::RenderShaderBlockingStatus();
		OverlayRenderer::RenderFeatureOverlays();
		globals::features::vr.dynamicNearClip.DrawReadout();
	});
}
