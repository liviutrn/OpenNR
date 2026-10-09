#pragma once

#include "NeuralRendering/SinglePassLadder.h"

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

	// Independent controls for sequential Feature 18 pass 2. Route ownership
	// (gaze/adaptive controller) remains shared: pass 2 derives its region from
	// the live pass-1 region every frame instead of maintaining a competing crop.
	struct SequentialPassSettings
	{
		uint coveragePercent = 100;  // relative linear coverage of the live pass-1 crop
		uint modelResolution = 100;
		uint preset = 0;
		float intensity = 1.70f;
		float localTone = 1.00f;
		float localStructure = 1.70f;
		float skinStructure = -1.0f;
		uint style = 0;
		bool autoMask = true;
		bool uiCorrection = false;
		uint resolveMode = 0;
		bool resultShapingEnabled = false;
		float resultEditStrength = 1.0f;
		float resultBrightening = 1.0f;
		float resultDarkening = 1.0f;
		float resultColor = 1.0f;
		float resultHueShiftStrength = 1.0f;
		float resultShadows = 1.0f;
		float resultMidtones = 1.0f;
		float resultHighlights = 1.0f;
		float resultMaxBrighteningStops = 0.0f;
		float resultMaxDarkeningStops = 0.0f;
		float resultMaxColorChangeStops = 0.0f;
		float resultLargeScaleTone = 1.0f;
		float resultFineDetail = 1.0f;
		float resultDetailRadius = 1.0f;
		float resultHaloSuppression = 0.0f;
		uint stabilizeMode = 0;
		float stabilizeTimeMs = 60.0f;
		bool stabilizeDetail = false;
		float stabilizeDepthThreshold = 0.05f;
		float stabilizeColorTolerance = 0.08f;
		uint blendMode = static_cast<uint>(SubrectBlendMode::kFeather);
		uint maskMode = static_cast<uint>(SubrectMaskMode::kOval);
		float featherWidth = 64.0f;
		float falloffCurve = 1.0f;
		float ditherStrength = 1.0f;
	};

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
		uint stretchMode = (uint)StretchMode::kPoint;
		float peripheryBlurRadius = 1.0f;
		uint debugVisualize = 0;  // tint cheap-stretched periphery red; runtime toggle
		uint peripheryAAMode = static_cast<uint>(PeripheryAAMode::kTemporalSmooth);
		float peripheryTemporalAlpha = 0.16f;
		uint subrectBlendMode = static_cast<uint>(SubrectBlendMode::kDither);
		uint subrectMaskMode = static_cast<uint>(SubrectMaskMode::kOval);
		float subrectFeatherWidth = 128.0f;
		// Shape of the oval/feather transition. 1.0 is the balanced smoothstep
		// curve; lower values move the neural result farther into the band, while
		// higher values keep the stretched periphery longer before the handoff.
		float subrectFalloffCurve = 0.5f;
		float subrectDitherStrength = 1.0f;
		// First-run NR defaults mirror the validated internal DLSSNR tuning target.
		// FoveatedRender itself remains opt-in, so this does not activate NR outside
		// an explicitly enabled foveated-DLSS session.
		bool neuralRenderingEnabled = true;
		uint neuralRenderingModelResolution = 100;
		bool neuralRenderingSinglePassLadder = true;
		float neuralRenderingLadderBudgetMs = 20.0f;
		float neuralRenderingLadderReserveMs = 1.0f;
		float neuralRenderingLadderHandoffMs = 150.0f;
		float neuralRenderingDisableAboveMs = 24.0f;
		float neuralRenderingEnableBelowMs = 14.0f;
		uint neuralRenderingCropDrop = 20;
		uint neuralRenderingForcedStage = 0;
		// NR-only centered coverage (linear %, per axis). DLSS stays full eye; Feature 18
		// runs at 100% model resolution on the center and is edge-blended onto DLSS.
		uint neuralRenderingCoverage = 100;
		uint neuralRenderingPreset = 0;  // 0 = Default; 5 = Custom
		float neuralRenderingIntensity = 1.70f;
		float neuralRenderingLocalTone = 1.00f;
		float neuralRenderingLocalStructure = 1.70f;
		float neuralRenderingSkinStructure = -1.0f;
		uint neuralRenderingStyle = 0;  // 0 = Natural, 1 = Fabric Detail, 2 = Cinematic
		bool neuralRenderingAutoMask = true;
		bool neuralRenderingUICorrection = false;
		// Optional display-space edits applied after Feature 18. Neutral values
		// preserve the native NR result when the stage is enabled.
		bool neuralRenderingResultShapingEnabled = false;
		float neuralRenderingResultEditStrength = 1.0f;
		float neuralRenderingResultBrightening = 1.0f;
		float neuralRenderingResultDarkening = 1.0f;
		float neuralRenderingResultColor = 1.0f;
		float neuralRenderingResultHueShiftStrength = 1.0f;
		float neuralRenderingResultShadows = 1.0f;
		float neuralRenderingResultMidtones = 1.0f;
		float neuralRenderingResultHighlights = 1.0f;
		float neuralRenderingResultMaxBrighteningStops = 0.0f;
		float neuralRenderingResultMaxDarkeningStops = 0.0f;
		float neuralRenderingResultMaxColorChangeStops = 0.0f;
		float neuralRenderingResultLargeScaleTone = 1.0f;
		float neuralRenderingResultFineDetail = 1.0f;
		float neuralRenderingResultDetailRadius = 1.0f;
		float neuralRenderingResultHaloSuppression = 0.0f;
		float neuralRenderingNearBlackProtection = 0.0f;
		float neuralRenderingNearBlackThreshold = 0.035f;
		float neuralRenderingNearBlackLiftSoftness = 0.001f;
		// 0 = off, 1 = static-pixel, 2 = game-motion-vector reprojection.
		std::uint32_t neuralRenderingStabilizeMode = 0;
		float neuralRenderingStabilizeTimeMs = 60.0f;
		bool neuralRenderingStabilizeDetail = false;
		float neuralRenderingStabilizeDepthThreshold = 0.05f;
		float neuralRenderingStabilizeColorTolerance = 0.08f;
		// Experimental OptiScaler-inspired stage order. Default remains the
		// post-upscale route; the pre-upscale route is full-eye only in VR and
		// falls back to post-upscale when its guide contract is unavailable.
		uint neuralRenderingPreUpscale = 0;
		// 0 = classic bounded resolve, 1 = exact-area + matched residual.
		uint neuralRenderingResolveMode = 1;
		// Experimental screenshot/benchmark mode: 0 = single pass, 1 = two, or
		// 2 = three sequential Feature 18 evaluations. Runtime-gated away from
		// pre-upscale and cropped VR paths.
		uint neuralRenderingMultiPass = 0;
		// Pass 2 is independently tunable but inherits route ownership (gaze/adaptive
		// crop center) from pass 1. coveragePercent is relative to the live pass-1
		// crop, not the persisted static preset.
		SequentialPassSettings neuralRenderingPass2{};
		// Experimental stereo atlas: pack both eyes into one Feature 18 evaluation
		// per sequential stage. Off by default; incompatible geometry fails closed
		// to the normal independent-eye path.
		bool neuralRenderingStereoAtlas = true;
		uint neuralRenderingStereoAtlasGuardPixels = 50;
		// Adaptive controller estimate used when deciding whether a two-pass route
		// can fit the frame budget without oscillating simply because pass 2 toggles.
		float neuralRenderingAdaptiveSecondPassCostMs = 6.0f;
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
		// N2 only: alternate the native eye each frame instead of skipping both eyes together.
		bool neuralRenderingTemporalReuseStaggerEyes = false;
		// Opt-in in-game adaptive NR test. The controller derives a 2:1
		// application budget from the selected headset refresh unless a custom FPS
		// target is set, then moves through the short native ladder; it never changes
		// the display/compositor mode.
		bool neuralRenderingAdaptiveEnabled = true;
		uint neuralRenderingAdaptiveRefreshHz = 80;
		// Zero keeps the refresh-derived budget for existing settings. When set,
		// the controller uses this custom application target instead.
		uint neuralRenderingAdaptiveTargetFps = 0;
		uint neuralRenderingAdaptiveMinimumResolution = 70;
		uint neuralRenderingAdaptiveDownshiftFrames = 4;
		uint neuralRenderingAdaptiveUpshiftFrames = 12;
		uint neuralRenderingAdaptiveMinimumDwellFrames = 30;
		float neuralRenderingAdaptiveGuardTimeMs = 1.0f;
		// v05 KISS controller. All four thresholds are direct SteamVR application
		// GPU frametime values and are user-configurable in the 10-30 ms range.
		float neuralRenderingAdaptivePassIncreaseBelowMs = 14.0f;
		float neuralRenderingAdaptiveCropIncreaseBelowMs = 16.0f;
		float neuralRenderingAdaptiveCropDecreaseAboveMs = 18.0f;
		float neuralRenderingAdaptivePassDecreaseAboveMs = 20.0f;
		float neuralRenderingAdaptiveSmoothingMs = 250.0f;
		float neuralRenderingAdaptiveDecreaseHoldMs = 350.0f;
		float neuralRenderingAdaptiveIncreaseHoldMs = 1200.0f;
		float neuralRenderingAdaptiveCooldownMs = 1000.0f;
		bool neuralRenderingAdaptiveDiagnostics = false;
		// Optional companion for the shared foveated crop. It is coordinated with
		// adaptive NR and is hard-disabled while eye-tracked foveation owns UVs.
		bool neuralRenderingAdaptiveCropEnabled = false;
		// Adaptive crop's upper tier is independent of the static crop preset. This
		// lets a user compare against a smaller static preset, then re-arm adaptive
		// crop at its normal 85% tier without silently changing the saved preset.
		uint neuralRenderingAdaptiveCropMaximumCoverage = 100;
		uint neuralRenderingAdaptiveCropMinimumCoverage = 60;
		uint neuralRenderingAdaptiveCropDownshiftFrames = 2;
		uint neuralRenderingAdaptiveCropUpshiftFrames = 24;
		uint neuralRenderingAdaptiveCropMinimumDwellFrames = 60;
		uint neuralRenderingAdaptiveCropTransitionFrames = 8;
		// Isolated native OpenVR gaze-provider experiment. The provider moves a
		// fixed-size crop around the per-eye gaze point; it is opt-in, NR-only,
		// and falls back to the persisted static crop whenever the native API is
		// unavailable, stale, unfocused, or in a menu/loading context.
		bool neuralRenderingEyeTrackedFoveation = true;
		float neuralRenderingEyeTrackedSmoothingMs = 0.0f;
		uint neuralRenderingEyeTrackedQuantizationPixels = 0;
		float neuralRenderingEyeTrackedDeadZonePercent = 0.0f;
		bool neuralRenderingEyeTrackedAdaptiveSmoothing = true;
		bool neuralRenderingEyeTrackedFreezeCrop = false;
		float neuralRenderingEyeTrackedResponsiveness = 8.0f;
		float neuralRenderingEyeTrackedSlowPercent = 10.0f;
		float neuralRenderingEyeTrackedFastPercent = 100.0f;
		float neuralRenderingEyeTrackedJumpPercent = 100.0f;
		float neuralRenderingEyeTrackedJumpSpeed = 20.0f;
		float neuralRenderingEyeTrackedMaxLagPercent = 25.0f;
		bool neuralRenderingAdaptiveFirstPassPriority = false;
		float neuralRenderingAdaptiveFirstPassIncreaseBelowMs = 14.0f;
		float neuralRenderingAdaptiveFirstPassHoldMs = 1200.0f;
		bool neuralRenderingAdaptiveFirstPassCostGuard = false;
		float neuralRenderingAdaptiveFirstPassCostMs = 6.0f;
		float neuralRenderingAdaptiveFirstPassMarginMs = 1.0f;
		float neuralRenderingAdaptiveFirstPassRetryMs = 3000.0f;
		uint neuralRenderingAdaptiveRelativeCropFloor = 60;
		uint neuralRenderingAdaptiveRelativeCropStep = 20;
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
	bool measureNRProtection = false;
	NeuralRendering::AdaptiveCropController adaptiveCropController;
	Util::Subrect::Controller subrectController;
	std::uint32_t adaptiveActivePasses = 1;
	std::uint32_t adaptiveConfiguredPasses = 1;
	bool adaptivePassInitialized = false;
	std::uint32_t adaptiveUpdateFrame = UINT32_MAX;
	std::array<float, 10> adaptiveWorkloadKey{};
	bool adaptiveWorkloadObserved = false;
	std::uint32_t adaptiveCropTargetCoverage = 100;
	std::uint32_t adaptiveLadderStage = 0;
	std::uint32_t adaptiveModelResolution = 100;
	std::uint32_t adaptiveBlockedGrowthStage = UINT32_MAX;
	float adaptiveGrowthBaselineMs = 0.0f;
	float adaptiveBlockedGrowthBaselineMs = 0.0f;
	// v05 authoritative controller state. Inherited v03/v04 diagnostic members
	// remain for source compatibility but do not participate in v05 decisions.
	float adaptiveFilteredFrameTimeMs = 0.0f;
	float adaptiveLastFrameTimeMs = 0.0f;
	float adaptiveDecreaseHoldMs = 0.0f;
	float adaptiveIncreaseHoldMs = 0.0f;
	float adaptiveCooldownRemainingMs = 0.0f;
	std::uint32_t adaptivePendingAction = 0;
	NeuralRendering::SinglePassLadder::Config adaptivePolicyConfig{};
	bool adaptivePolicyObserved = false;
	float adaptiveResumeRemainingMs = 0.0f;
	std::uint32_t adaptiveLastAction = 0;
	std::uint32_t adaptiveLastActionFrom = 0;
	std::uint32_t adaptiveLastActionTo = 0;
	float adaptiveLastActionFrameTimeMs = 0.0f;

	// Called from Upscaling::DrawSettings. DrawEnable renders the always-visible
	// header + Enable checkbox at the parent's top level; DrawSettings renders
	// the body knobs inside a collapsible TreeNode (Upscaling wraps it in
	// BeginDisabled when settings.enabled == 0).
	void DrawEnable();
	void DrawSettings(bool showSharedPanelNote = true, bool vrControlsFirst = false,
		bool showNeuralRenderingStatusButton = true);
	void DrawNeuralRenderingStatusButton();
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
