#pragma once

#include "Feature.h"

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

struct ID3D11Resource;

/**
 * @brief Captures paired pre- and post-neural-rendering textures for OpenNR training.
 *
	 * GPU copies, query polling, and readback run on the render thread, while PNG/raw encoding
	 * and JSONL writes run on a bounded background queue. The feature is opt-in: while disabled,
 * the present hook does not poll hotkeys and the renderer does not enter capture setup.
 * It never captures the desktop or swap-chain presentation surface.
 */
struct OpenNRCaptureFeature final : Feature
{
	/** @brief Normalized crop center in the source eye texture. */
	struct CropPreset
	{
		float centerX = 0.5f;
		float centerY = 0.5f;
	};

	/** @brief Persisted capture settings. */
	struct Settings
	{
		bool enableCapture = false;
		bool capturePreNR = true;
		bool capturePostNR = true;
		bool captureRawTeacher = true;
		bool captureDepth = true;
		bool captureMotionVectors = true;
		/** @brief Writes RGB8 PNG previews for color tensors in sampled frames. */
		bool writeColorPreviews = true;
		bool captureFullFrame = true;
		/** @brief Write a complete per-eye frame for every sampled frame in this sequence. */
		bool captureFullFrameSequence = false;
		bool captureLeftEye = true;
		bool captureRightEye = true;
		float captureRateFps = 3.0f;
		std::uint32_t burstFrames = 8;
		std::uint32_t cropSize = 512;
		std::uint32_t cropCount = 4;
		std::uint32_t queueCapacity = 8;
		std::uint32_t fullFrameEverySamples = 100;
		std::uint32_t maxSamples = 0;
		std::uint32_t toggleCaptureKey = 0xDB;  // '[' (VK_OEM_4)
		std::uint32_t singleCaptureKey = 0xDD;  // ']' (VK_OEM_6)
		std::uint32_t burstCaptureKey = 0xDC;  // '\' (VK_OEM_5)
		std::string outputDirectory = "OpenNR_Captures";
		std::vector<CropPreset> crops{
			{ 0.50f, 0.50f },
			{ 0.25f, 0.50f },
			{ 0.75f, 0.50f },
			{ 0.50f, 0.25f }
		};
	};

	/** @brief Render-frame and teacher-route information attached to every sample. */
	struct FrameInfo
	{
		std::uint64_t hostFrame = 0;
		std::uint32_t colorWidth = 0;
		std::uint32_t colorHeight = 0;
		std::uint32_t modelWidth = 0;
		std::uint32_t modelHeight = 0;
		std::uint32_t modelResolutionPercent = 100;
		std::uint32_t guideWidth = 0;
		std::uint32_t guideHeight = 0;
		std::uint32_t passCount = 1;
		std::array<float, 2> motionVectorScaleX{ 1.0f, 1.0f };
		std::array<float, 2> motionVectorScaleY{ 1.0f, 1.0f };
		std::array<bool, 2> historyReset{ true, true };
		float intensity = 0.0f;
		float localToneStrength = 0.0f;
		float localStructureStrength = 0.0f;
		float skinStructureStrength = 0.0f;
		std::uint32_t style = 0;
		bool useAutoMask = false;
		bool uiCorrection = false;
		std::string route = "feature18";
	};

	/** @brief Stops the writer thread and releases pending GPU resources. */
#if defined(OPENNR_CAPTURE_ENABLED)
	OpenNRCaptureFeature();
	~OpenNRCaptureFeature();
#else
	OpenNRCaptureFeature() = default;
	~OpenNRCaptureFeature() = default;
#endif

	/** @brief Returns the user-facing feature name. */
	std::string GetName() override { return "OpenNR Capture"; }
	/** @brief Returns the localized feature name. */
	std::string GetDisplayName() override { return T("feature.opennr_capture.name", "OpenNR Capture"); }
	/** @brief Returns the disk/config short name. */
	std::string GetShortName() override { return "OpenNRCapture"; }
	/** @brief Places the feature in the utility settings category. */
	std::string_view GetCategory() const override { return FeatureCategories::kUtility; }
	/** @brief Allows the feature to be used by both flat and stereo VR routes. */
	bool SupportsVR() override { return true; }

#if defined(OPENNR_CAPTURE_ENABLED)
	/** @brief Draws capture controls and live queue diagnostics. */
	void DrawSettings() override;
	/** @brief Loads persisted capture settings with range validation. */
	void LoadSettings(json& a_json) override;
	/** @brief Saves persisted capture settings. */
	void SaveSettings(json& a_json) override;
	/** @brief Restores safe, opt-in defaults. */
	void RestoreDefaultSettings() override;
	/** @brief Exposes live writer and drop counters. */
	json GetDiagnostics() override;
	/** @brief Exposes diagnostics for const devbench queries. */
	json GetDiagnostics() const;
	/** @brief Exposes the runtime recording flag without persisting it. */
	json GetRuntimeFlags() override;
	/** @brief Starts or stops recording through runtime-only controls. */
	bool SetRuntimeFlag(std::string_view a_name, bool a_value) override;
	/** @brief Registers devbench start/stop/single/burst actions. */
	void RegisterUxActions() override;

	/** @brief Polls the configured edge-triggered capture hotkeys. */
	void PollHotkeys();
	/** @brief Starts a new capture sequence. */
	void StartCapture();
	/** @brief Stops recording after the current GPU work is safely released. */
	void StopCapture();
	/** @brief Toggles recording for the current sequence. */
	void ToggleCapture();
	/** @brief Requests one sample on the next eligible render route. */
	void RequestSingle();
	/** @brief Requests the configured finite burst. */
	void RequestBurst();

	/** @brief Begins a bounded sample on the render thread. */
	bool BeginFrame(const FrameInfo& a_info);
	/**
	 * @brief Queues GPU crops from a render texture for the active sample.
	 * @param a_source Source render texture; never a desktop capture surface.
	 * @param a_sourceX Source rectangle origin in pixels.
	 * @param a_sourceY Source rectangle origin in pixels.
	 * @param a_sourceWidth Source rectangle width.
	 * @param a_sourceHeight Source rectangle height.
	 * @param a_stage Dataset stage label such as input, input_source, teacher, or teacher_raw.
	 * @param a_eyeIndex Eye index (0 = left, 1 = right).
	 * @param a_fullFrame When true, records the complete source rectangle once.
	 * @param a_writePreview When false, writes only the exact typed raw tensor.
	 * @return true when at least one GPU copy was queued.
	 */
	bool CaptureTexture(ID3D11Resource* a_source, std::uint32_t a_sourceX, std::uint32_t a_sourceY,
		std::uint32_t a_sourceWidth, std::uint32_t a_sourceHeight, std::string_view a_stage,
		std::uint32_t a_eyeIndex, bool a_fullFrame = false, bool a_writePreview = true);
	/** @brief Completes the active sample with a GPU event query and enqueues it. */
	void EndFrame();
	/** @brief Releases an active sample without writing metadata. */
	void AbortFrame();
	/** @brief Returns true while a capture sequence is recording. */
	bool IsCapturing() const;
	/** @brief Returns true when the current sample includes complete per-eye artifacts. */
	bool IsFullFrameValidationFrame() const;
#else
	// The distributable DLL keeps a tiny source-compatible no-op surface for
	// renderer call sites, but does not contain the capture implementation. The
	// OpenNRCapture.ini registration is excluded from that package as well.
	void DrawSettings() override {}
	void LoadSettings(json&) override {}
	void SaveSettings(json&) override {}
	void RestoreDefaultSettings() override {}
	json GetDiagnostics() override { return json::object(); }
	json GetDiagnostics() const { return json::object(); }
	json GetRuntimeFlags() override { return json::object(); }
	bool SetRuntimeFlag(std::string_view, bool) override { return false; }
	void RegisterUxActions() override {}

	void PollHotkeys() {}
	void StartCapture() {}
	void StopCapture() {}
	void ToggleCapture() {}
	void RequestSingle() {}
	void RequestBurst() {}
	bool BeginFrame(const FrameInfo&) { return false; }
	bool CaptureTexture(ID3D11Resource*, std::uint32_t, std::uint32_t,
		std::uint32_t, std::uint32_t, std::string_view,
		std::uint32_t, bool = false, bool = true)
	{
		return false;
	}
	void EndFrame() {}
	void AbortFrame() {}
	bool IsCapturing() const { return false; }
	bool IsFullFrameValidationFrame() const { return false; }
#endif

	Settings settings;

private:
#if defined(OPENNR_CAPTURE_ENABLED)
	class Impl;
	std::unique_ptr<Impl> impl_;
#endif
};
