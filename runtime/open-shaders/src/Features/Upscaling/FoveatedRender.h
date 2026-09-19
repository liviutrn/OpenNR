#pragma once

// ============================================================================
// FoveatedRender — VR DLSS enhancement mode of Upscaling
// ============================================================================
//
// Foveated subrect-DLSS path: only the user-selected region gets full DLSS
// upscaling; the periphery is cheaply stretched via SubrectStretchCS. Halves
// (or more) the DLSS workload. Composes with VRS, Screenshot, and the lossless
// recording feature through the shared Util::Subrect module — use the same
// preset for consistent results across them.
//
// Architecturally a mode inside Upscaling (mirroring DLSSperf): a static-
// inline member, not a peer Feature. Settings that overlap with Upscaling's
// (quality mode, sharpness, DLSS preset, Streamline log level) read directly
// from `globals::features::upscaling.settings` rather than being duplicated.
// VR only -- flat has no lens-driven periphery quality cliff to exploit, so
// the perf/quality tradeoff doesn't carry over. Supports both DLSS and FSR3
// (host path); under FSR, only DlssMode::kDefault is available -- kFaster
// relies on Streamline's SBS-subrect read, which has no FSR equivalent.
//
// ============================================================================

#include "../../Utils/BootSnapshot.h"
#include "../../Utils/Subrect.h"
#include "NeuralRendering/AdaptiveController.h"
#include "NeuralRendering/AdaptiveCropController.h"

#include <chrono>
#include <cstdint>

struct FoveatedRender
{
	// DLSS execution mode for VR
	enum class DlssMode : uint
	{
		kDefault = 0,  // Per-eye isolation: 2 extra resource sets, 2 evaluates. Supports F/J/K/L/M.
		kFaster = 1,   // SBS viewport: tell SL to read subrect from SBS directly, no extra resources, 2 evaluates. J/K incompatible, only L/M/F.
	};

	// Subrect blend mode when writing DLSS output back over stretched background
	enum class SubrectBlendMode : uint
	{
		kHardCopy = 0,  // CopySubresourceRegion (no blending — sharp edge)
		kFeather = 1,   // smoothstep alpha ramp over N pixels
		kDither = 2,    // Blue-noise binary threshold in feather band
	};

	// Shape of the feather/dither composite mask. The DLSS/Feature 18 input and
	// output remain rectangular; this only controls how the sharp subrect is
	// composited over the cheap periphery.
	enum class SubrectMaskMode : uint
	{
		kRectangle = 0,  // Preserve the rectangular edge behavior
		kOval = 1,       // Aspect-corrected elliptical transition
	};

	// Periphery AA algorithm applied after background stretch
	enum class PeripheryAAMode : uint
	{
		kNone = 0,            // No dedicated periphery AA
		kTemporalSmooth = 1,  // Motion-compensated temporal accumulation (anti-flicker)
	};

	// Stretch algorithm for DRS → full-eye background (used by SubrectStretchCS shader)
	enum class StretchMode : uint
	{
		kBilinear = 0,      // Default bilinear sampling (clean upscale)
		kPoint = 1,         // Nearest-neighbor / point (cheapest, VRS-like broadcast)
		kGaussianBlur = 2,  // 3x3 Gaussian blur (soft periphery)
	};

	/** @brief Translated display names for the enums above -- single source shared by
	 *  DrawSettings' dropdowns and Upscaling::GetProfilePreviewText. */
	static const char* DlssModeName(DlssMode mode);
	static const char* StretchModeName(StretchMode mode);
	static const char* PeripheryAAModeName(PeripheryAAMode mode);
	static const char* SubrectBlendModeName(SubrectBlendMode mode);
	static const char* SubrectMaskModeName(SubrectMaskMode mode);

	// FoveatedRender-specific settings. Quality mode / sharpness / DLSS preset /
	// Streamline log level live on Upscaling::Settings and are read through
	// the accessors below — do not duplicate them here. Sharpening on/off is
	// controlled by the shared sharpnessDLSS slider (0 disables RCAS).
	//
	// Do not add UI sliders for MV-dilation / reactive-mask / transparency-mask
	// toggles until the shader permutations are plumbed: EncodeTexturesCS needs
	// per-toggle defines, the encode pass needs a conditional skip when all are
	// off, and EvaluateDLSS needs per-toggle arg gating. Knobs without wiring
	// are silent no-ops that mislead users.
	struct Settings
	{
		uint enabled = 0;  // opt-in: requires restart to take effect via LatchEnabled()
		uint dlssMode = (uint)DlssMode::kDefault;
		uint stretchMode = (uint)StretchMode::kGaussianBlur;
		float peripheryBlurRadius = 1.0f;
		uint debugVisualize = 0;  // tint cheap-stretched periphery red; runtime toggle
		uint peripheryAAMode = static_cast<uint>(PeripheryAAMode::kTemporalSmooth);
		float peripheryTemporalAlpha = 0.16f;
		uint subrectBlendMode = static_cast<uint>(SubrectBlendMode::kFeather);
		uint subrectMaskMode = static_cast<uint>(SubrectMaskMode::kOval);
		float subrectFeatherWidth = 64.0f;
		// Shape of the oval/feather transition. 1.0 is the balanced smoothstep
		// curve; lower values move the neural result farther into the band, while
		// higher values keep the stretched periphery longer before the handoff.
		float subrectFalloffCurve = 1.0f;
		float subrectDitherStrength = 1.0f;
		// First-run NR defaults mirror the validated internal DLSSNR tuning target.
		// FoveatedRender itself remains opt-in, so this does not activate NR outside
		// an explicitly enabled foveated-DLSS session.
		bool neuralRenderingEnabled = true;
		uint neuralRenderingModelResolution = 100;
		uint neuralRenderingPreset = 0;  // 0 = Default; 5 = Custom
		float neuralRenderingIntensity = 1.70f;
		float neuralRenderingLocalTone = 1.00f;
		float neuralRenderingLocalStructure = 1.70f;
		float neuralRenderingSkinStructure = -1.0f;
		uint neuralRenderingStyle = 0;  // 0 = Natural, 1 = Fabric Detail, 2 = Cinematic, 3 = Strong
		bool neuralRenderingAutoMask = true;
		bool neuralRenderingUICorrection = false;
		// Experimental OptiScaler-inspired stage order. Default remains the
		// post-upscale route; the pre-upscale route is full-eye only in VR and
		// falls back to post-upscale when its guide contract is unavailable.
		uint neuralRenderingPreUpscale = 0;
		// 0 = classic bounded resolve, 1 = exact-area + matched residual.
		uint neuralRenderingResolveMode = 0;
		// Experimental screenshot/benchmark mode: 0 = single pass, 1 = two, or
		// 2 = three sequential Feature 18 evaluations. Runtime-gated away from
		// pre-upscale and cropped VR paths.
		uint neuralRenderingMultiPass = 0;
		// Experimental Feature 18 temporal reuse. 0 = off; 2/3/4 means a full
		// neural pass every Nth frame, with exact-MV residual reprojection between
		// full passes. Runtime-gated to native-size single-pass full-eye or stable
		// fixed crop-local layouts; moving crop origins remain disabled.
		uint neuralRenderingTemporalReuseCadence = 0;
		float neuralRenderingTemporalDepthThreshold = 0.05f;
		float neuralRenderingTemporalColorTolerance = 0.08f;
		// Diagnostic only: keep the conservative reset after reused frames unless
		// explicitly disabled for an isolated temporal-causality experiment.
		bool neuralRenderingTemporalReuseResetAfterSkip = true;
		// Opt-in in-game adaptive NR test. The controller derives a 2:1
		// application budget from the selected headset refresh unless a custom FPS
		// target is set, then moves through the short native ladder; it never changes
		// the display/compositor mode.
		bool neuralRenderingAdaptiveEnabled = false;
		uint neuralRenderingAdaptiveRefreshHz = 80;
		// Zero keeps the refresh-derived budget for existing settings. When set,
		// the controller uses this custom application target instead.
		uint neuralRenderingAdaptiveTargetFps = 0;
		uint neuralRenderingAdaptiveMinimumResolution = 70;
		uint neuralRenderingAdaptiveDownshiftFrames = 4;
		uint neuralRenderingAdaptiveUpshiftFrames = 12;
		uint neuralRenderingAdaptiveMinimumDwellFrames = 30;
		float neuralRenderingAdaptiveGuardTimeMs = 1.0f;
		bool neuralRenderingAdaptiveDiagnostics = false;
		// Optional companion for the shared foveated crop. It is coordinated with
		// adaptive NR and is hard-disabled while eye-tracked foveation owns UVs.
		bool neuralRenderingAdaptiveCropEnabled = false;
		// Adaptive crop's upper tier is independent of the static crop preset. This
		// lets a user compare against a smaller static preset, then re-arm adaptive
		// crop at its normal 85% tier without silently changing the saved preset.
		uint neuralRenderingAdaptiveCropMaximumCoverage = 85;
		uint neuralRenderingAdaptiveCropMinimumCoverage = 60;
		uint neuralRenderingAdaptiveCropDownshiftFrames = 2;
		uint neuralRenderingAdaptiveCropUpshiftFrames = 24;
		uint neuralRenderingAdaptiveCropMinimumDwellFrames = 60;
		uint neuralRenderingAdaptiveCropTransitionFrames = 8;
		// Isolated native OpenVR gaze-provider experiment. The provider moves a
		// fixed-size crop around the per-eye gaze point; it is opt-in, NR-only,
		// and falls back to the persisted static crop whenever the native API is
		// unavailable, stale, unfocused, or in a menu/loading context.
		bool neuralRenderingEyeTrackedFoveation = false;
		float neuralRenderingEyeTrackedSmoothingMs = 0.0f;
		uint neuralRenderingEyeTrackedQuantizationPixels = 8;
	};

	inline static constexpr Util::Settings::RestartTable<Settings, 1> kRestartFields{ {
		UTIL_RESTART_FIELD(Settings, enabled, "Foveated DLSS"),
	} };
	Util::Settings::BootSnapshot<Settings> bootSnapshot{ kRestartFields };

	/** @brief Region-preset display names, shared by PostPostLoad's seed list, the
	 *  top-level preset buttons, and Upscaling::ApplyPerformanceProfile. */
	static constexpr const char* kPresetFullEye = "Full Eye";                          ///< No crop; full-eye DLSS coverage.
	static constexpr const char* kPresetCenter90 = "Center 90%";                       ///< Centered crop covering 90% of the eye.
	static constexpr const char* kPresetCenter80 = "Center 80%";                       ///< Centered crop covering 80% of the eye.
	static constexpr const char* kPresetCenter75 = "Center 75%";                       ///< Legacy centered crop covering 75% of the eye.
	static constexpr const char* kPresetCenter70 = "Center 70%";                       ///< Centered crop covering 70% of the eye.
	static constexpr const char* kPresetCenter60 = "Center 60%";                       ///< Centered crop covering 60% of the eye.
	static constexpr const char* kPresetCenter50 = "Center 50%";                       ///< Centered crop covering 50% of the eye.
	static constexpr const char* kPresetCenter40 = "Center 40%";                       ///< Centered crop covering 40% of the eye.
	static constexpr const char* kPresetCenter30 = "Center 30%";                       ///< Centered crop covering 30% of the eye.
	static constexpr const char* kPresetNasalConvergence50 = "Nasal Convergence 50%";  ///< 50% crop biased toward nasal convergence.
	static constexpr const char* kPresetNasalConvergence60 = "Nasal Convergence 60%";  ///< 60% crop biased toward nasal convergence.
	static constexpr const char* kPresetNasalConvergence70 = "Nasal Convergence 70%";  ///< 70% crop biased toward nasal convergence.

	Settings settings;
	NeuralRendering::AdaptiveController adaptiveController;
	NeuralRendering::AdaptiveCropController adaptiveCropController;
	Util::Subrect::Controller subrectController;
	// Pressure alternates crop -> NR -> crop when both controllers can help.
	// Restoration remains NR-first because crop is gated on NR maximum.
	bool adaptiveNextDownshiftIsCrop = true;
	std::uint64_t adaptiveCropDiagnosticGeneration = UINT64_MAX;

	// Called from Upscaling::DrawSettings. DrawEnable renders the always-visible
	// header + Enable checkbox at the parent's top level; DrawSettings renders
	// the body knobs inside a collapsible TreeNode (Upscaling wraps it in
	// BeginDisabled when settings.enabled == 0).
	void DrawEnable();
	void DrawSettings(bool showSharedPanelNote = true, bool vrControlsFirst = false);
	// Called from Upscaling::SaveSettings / LoadSettings to round-trip JSON.
	void SaveSettings(json& o_json);
	void LoadSettings(const json& o_json);
	void RestoreDefaultSettings();
	/** @brief Applies one of the named DLSS Neural Rendering tuning presets. */
	bool ApplyNeuralRenderingPreset(std::string_view presetName);
	void ClearShaderCache();
	// Called from Upscaling::PostPostLoad to seed subrect presets.
	void PostPostLoad();

	struct UICompositeRenderHook
	{
		static void thunk(void* imageSpaceShader, RE::BSTriShape* shape, RE::ImageSpaceEffectParam* param);
		static inline REL::Relocation<decltype(thunk)> func;
	};

	bool IsRuntimeSupported() const;
	bool IsActive() const;
	bool IsLoaded() const { return enabledAtBoot; }

	/** @brief Update the adaptive NR/crop policy once for the current engine frame. */
	void UpdateAdaptiveState(std::uint32_t frame, bool routeEligible);
	/** @brief Reset adaptive state without changing persisted user settings. */
	void ResetAdaptiveState();
	/** @brief True when a gaze/eye-tracking route owns crop geometry. */
	bool IsEyeTrackedFoveationEnabled() const;
	/** @brief Effective UVs consumed by foveated DLSS, VRS, and NR. */
	Util::Subrect::UVRegion GetEffectiveLeftUV() const;
	Util::Subrect::UVRegion GetEffectiveRightUV() const;
	bool IsAdaptiveCropRuntimeActive() const { return adaptiveCropController.IsRuntimeActive(); }
	bool IsAdaptiveCropTransitioning() const { return adaptiveCropController.IsTransitioning(); }
	std::uint32_t GetAdaptiveCropMaximumCoverage() const { return adaptiveCropController.MaximumCoverage(); }

	/** @brief True while drag-resizing the crop region, and for a few seconds after.
	 *  Read by the stretch pass alongside settings.debugVisualize. */
	bool ShouldForceVisualize() const;

	// Foveation region for per-pixel foveated effects (e.g. SSR): the rectangular DLSS subrect mapped
	// to centered-superellipse params. available is false when foveation is inactive or full-eye.
	struct FoveationProfile
	{
		bool available = false;
		float coverageScale = 1.0f;          // linear center coverage scale [0.25, 1.0]
		float centerHorizontalScale = 1.0f;  // [1.0, 2.0]
		float2 centerOffsets[2] = {};        // [0]=left eye, [1]=right eye
	};
	FoveationProfile GetFoveationProfile() const;

	// Main enable: latched at boot, change requires restart
	void LatchEnabled() { enabledAtBoot = (settings.enabled != 0); }

	// Quality mode reads through Upscaling::Settings — latch the boot value so
	// downstream RT allocations stay coherent if the user moves the slider.
	void LatchQualityMode();
	uint GetQualityModeAtBoot() const { return qualityModeAtBoot; }

	/// Render-to-display scale denominator for a quality mode index
	/// (1=Quality .. 4=UltraPerformance). Delegates to the FFX SDK ratio table.
	static float GetRenderScaleForQuality(uint qualityMode);

	// Faster mode relies on Streamline's SBS-subrect read, which has no FSR
	// equivalent -- forced to kDefault whenever FSR is the selected method.
	DlssMode GetDlssMode() const;
	StretchMode GetStretchMode() const { return (StretchMode)std::min(settings.stretchMode, 2u); }
	PeripheryAAMode GetPeripheryAAMode() const { return static_cast<PeripheryAAMode>(std::min(settings.peripheryAAMode, 1u)); }
	SubrectBlendMode GetSubrectBlendMode() const { return static_cast<SubrectBlendMode>(std::min(settings.subrectBlendMode, 2u)); }
	SubrectMaskMode GetSubrectMaskMode() const { return static_cast<SubrectMaskMode>(std::min(settings.subrectMaskMode, 1u)); }

	// Active getters: clamp + route shared fields through Upscaling::Settings.
	uint GetActiveQualityMode() const;
	uint GetActivePresetDLSS() const;
	float GetActiveSharpnessDLSS() const;

	// Re-clamp cross-feature settings (preset vs DLSS mode). Idempotent; safe to call
	// from Upscaling::LoadSettings after JSON has overwritten shared fields.
	void ClampSettings();

private:
	bool enabledAtBoot = false;                            // latched from settings.enabled at boot
	uint qualityModeAtBoot = 4;                            // latched from Upscaling::Settings::qualityMode at boot
	std::chrono::steady_clock::time_point lastDragTime{};  // epoch -- no force-visualize at boot

	bool IsPresetCompatibleWithMode(uint presetIndex) const;
	void ClampPresetToMode();
};
