#include "Features/OpenNRCapture.h"

#include <PCH.h>

#include "Globals.h"
#include "Utils/D3D.h"
#include "Utils/ExternalOutput.h"
#include "Utils/DevBenchUx.h"
#include "Features/Upscaling/NeuralRendering/Integration.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <format>
#include <limits>
#include <mutex>
#include <string>
#include <thread>
#include <utility>

#include <d3d11.h>
#include <dxgi.h>
#include <imgui_stdlib.h>
#include <stb_image_write.h>
#include <wrl/client.h>

namespace
{
	using Microsoft::WRL::ComPtr;
	using Clock = std::chrono::steady_clock;

	constexpr std::uint32_t kMinCropSize = 16;
	constexpr std::uint32_t kMaxCropSize = 4096;
	constexpr std::uint32_t kMaxCropCount = 4;
	constexpr std::uint32_t kMaxQueueCapacity = 64;
	constexpr std::uint32_t kMaxBurstFrames = 100000;
	constexpr std::uint32_t kMaxSamples = 100000000;
	constexpr auto kGpuReadbackTimeout = std::chrono::seconds(5);

	std::atomic<std::uint64_t> g_sequenceSerial{ 1 };

	std::uint32_t ClampCropSize(std::uint32_t a_value)
	{
		return std::clamp(a_value, kMinCropSize, kMaxCropSize);
	}

	std::uint32_t ClampCropCount(std::uint32_t a_value)
	{
		return std::clamp(a_value, 1u, kMaxCropCount);
	}

	std::uint32_t ClampQueueCapacity(std::uint32_t a_value)
	{
		return std::clamp(a_value, 1u, kMaxQueueCapacity);
	}

	std::string SanitizeComponent(std::string_view a_value)
	{
		std::string result;
		result.reserve(a_value.size());
		for (const char c : a_value) {
			if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
				(c >= '0' && c <= '9') || c == '-' || c == '_') {
				result.push_back(c);
			} else {
				result.push_back('_');
			}
		}
		return result.empty() ? "capture" : result;
	}

	std::filesystem::path GameRoot()
	{
		wchar_t buffer[MAX_PATH]{};
		const DWORD length = GetModuleFileNameW(nullptr, buffer, static_cast<DWORD>(std::size(buffer)));
		if (length > 0 && length < std::size(buffer))
			return std::filesystem::path(buffer).parent_path();
		return std::filesystem::current_path();
	}

	std::filesystem::path ResolveOutputRoot(const std::string& a_configuredPath)
	{
		std::filesystem::path path = a_configuredPath.empty() ? "C:/OpenNR/Captures" : a_configuredPath;
		if (!path.is_absolute())
			path = GameRoot() / path;
		try {
			return OpenNRStorage::ResolveExternalOutput(path);
		} catch (const std::exception& error) {
			logger::error("OpenNR Capture output rejected: {} ({})", path.string(), error.what());
			return {};
		}
	}

	std::string FormatName(DXGI_FORMAT a_format)
	{
		switch (a_format) {
		case DXGI_FORMAT_R8G8B8A8_TYPELESS:
			return "R8G8B8A8_TYPELESS";
		case DXGI_FORMAT_R8G8B8A8_UNORM:
			return "R8G8B8A8_UNORM";
		case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
			return "R8G8B8A8_UNORM_SRGB";
		case DXGI_FORMAT_B8G8R8A8_TYPELESS:
			return "B8G8R8A8_TYPELESS";
		case DXGI_FORMAT_B8G8R8A8_UNORM:
			return "B8G8R8A8_UNORM";
		case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
			return "B8G8R8A8_UNORM_SRGB";
		case DXGI_FORMAT_B8G8R8X8_TYPELESS:
			return "B8G8R8X8_TYPELESS";
		case DXGI_FORMAT_B8G8R8X8_UNORM:
			return "B8G8R8X8_UNORM";
		case DXGI_FORMAT_R16G16B16A16_TYPELESS:
			return "R16G16B16A16_TYPELESS";
		case DXGI_FORMAT_R16G16B16A16_FLOAT:
			return "R16G16B16A16_FLOAT";
		case DXGI_FORMAT_R16G16B16A16_UNORM:
			return "R16G16B16A16_UNORM";
		case DXGI_FORMAT_R10G10B10A2_TYPELESS:
			return "R10G10B10A2_TYPELESS";
		case DXGI_FORMAT_R10G10B10A2_UNORM:
			return "R10G10B10A2_UNORM";
		case DXGI_FORMAT_R11G11B10_FLOAT:
			return "R11G11B10_FLOAT";
		case DXGI_FORMAT_R16_UNORM:
			return "R16_UNORM";
		case DXGI_FORMAT_R16G16_TYPELESS:
			return "R16G16_TYPELESS";
		case DXGI_FORMAT_R16G16_FLOAT:
			return "R16G16_FLOAT";
		case DXGI_FORMAT_R16G16_SNORM:
			return "R16G16_SNORM";
		case DXGI_FORMAT_R32_TYPELESS:
			return "R32_TYPELESS";
		case DXGI_FORMAT_R32_FLOAT:
			return "R32_FLOAT";
		case DXGI_FORMAT_R32G32_TYPELESS:
			return "R32G32_TYPELESS";
		case DXGI_FORMAT_R32G32_FLOAT:
			return "R32G32_FLOAT";
		default:
			return std::format("DXGI_FORMAT_{}", static_cast<std::uint32_t>(a_format));
		}
	}

	std::uint32_t BytesPerPixel(DXGI_FORMAT a_format)
	{
		switch (a_format) {
		case DXGI_FORMAT_R8G8B8A8_TYPELESS:
		case DXGI_FORMAT_R8G8B8A8_UNORM:
		case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
		case DXGI_FORMAT_B8G8R8A8_TYPELESS:
		case DXGI_FORMAT_B8G8R8A8_UNORM:
		case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
		case DXGI_FORMAT_B8G8R8X8_TYPELESS:
		case DXGI_FORMAT_B8G8R8X8_UNORM:
		case DXGI_FORMAT_R10G10B10A2_TYPELESS:
		case DXGI_FORMAT_R10G10B10A2_UNORM:
		case DXGI_FORMAT_R11G11B10_FLOAT:
			return 4;
		case DXGI_FORMAT_R16_UNORM:
		case DXGI_FORMAT_R16G16_TYPELESS:
		case DXGI_FORMAT_R16G16_FLOAT:
		case DXGI_FORMAT_R16G16_SNORM:
		case DXGI_FORMAT_R32_TYPELESS:
		case DXGI_FORMAT_R32_FLOAT:
			return a_format == DXGI_FORMAT_R16_UNORM ? 2 : 4;
		case DXGI_FORMAT_R16G16B16A16_TYPELESS:
		case DXGI_FORMAT_R16G16B16A16_FLOAT:
		case DXGI_FORMAT_R16G16B16A16_UNORM:
		case DXGI_FORMAT_R32G32_TYPELESS:
		case DXGI_FORMAT_R32G32_FLOAT:
			return 8;
		default:
			return 0;
		}
	}

	std::uint8_t ToByte(float a_value)
	{
		const float clamped = std::clamp(a_value, 0.0f, 1.0f);
		return static_cast<std::uint8_t>(std::lround(clamped * 255.0f));
	}

	std::uint8_t ToSrgbByte(float a_linear)
	{
		const float clamped = std::clamp(a_linear, 0.0f, 1.0f);
		return ToByte(std::pow(clamped, 1.0f / 2.2f));
	}

	float HalfToFloat(std::uint16_t a_half)
	{
		const std::uint32_t sign = (a_half & 0x8000u) << 16;
		const std::uint32_t exponent = (a_half >> 10) & 0x1Fu;
		const std::uint32_t mantissa = a_half & 0x03FFu;
		std::uint32_t result = 0;
		if (exponent == 0) {
			if (mantissa == 0) {
				result = sign;
			} else {
				std::uint32_t normalized = mantissa;
				std::int32_t exponentValue = -14;
				while ((normalized & 0x0400u) == 0) {
					normalized <<= 1;
					--exponentValue;
				}
				normalized &= 0x03FFu;
				result = sign | (static_cast<std::uint32_t>(exponentValue + 127) << 23) | (normalized << 13);
			}
		} else if (exponent == 0x1Fu) {
			result = sign | 0x7F800000u | (mantissa << 13);
		} else {
			result = sign | ((exponent + 112u) << 23) | (mantissa << 13);
		}
		float value = 0.0f;
		std::memcpy(&value, &result, sizeof(value));
		return value;
	}

	bool RenameTemporary(const std::filesystem::path& a_temporary, const std::filesystem::path& a_target)
	{
		std::error_code ec;
		std::filesystem::rename(a_temporary, a_target, ec);
		if (!ec)
			return true;
		std::filesystem::remove(a_target, ec);
		ec.clear();
		std::filesystem::rename(a_temporary, a_target, ec);
		if (ec)
			std::filesystem::remove(a_temporary, ec);
		return !ec;
	}

	bool WriteJsonAtomic(const std::filesystem::path& a_path, const json& a_value)
	{
		std::error_code ec;
		std::filesystem::create_directories(a_path.parent_path(), ec);
		if (ec)
			return false;
		const auto temporary = a_path.string() + ".tmp";
		{
			std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
			if (!stream)
				return false;
			const auto text = a_value.dump(2);
			stream.write(text.data(), static_cast<std::streamsize>(text.size()));
			stream.put('\n');
			if (!stream)
				return false;
		}
		return RenameTemporary(temporary, a_path);
	}
}

class OpenNRCaptureFeature::Impl
{
public:
	explicit Impl(OpenNRCaptureFeature& a_owner) : owner(a_owner) {}

	struct PendingItem
	{
		ComPtr<ID3D11Texture2D> staging;
		D3D11_TEXTURE2D_DESC desc{};
		bool writePreview = true;
		std::filesystem::path pngPath;
		std::filesystem::path rawPath;
		std::size_t metadataIndex = 0;
		std::vector<std::uint8_t> bytes;
		std::uint32_t rowPitch = 0;
		bool readbackReady = false;
	};

	struct PendingFrame
	{
		// GPU-owned objects are consumed on the render thread before the frame enters
		// the writer queue, so no background thread touches Skyrim's immediate context.
		ComPtr<ID3D11DeviceContext> context;
		ComPtr<ID3D11Query> completion;
		std::vector<PendingItem> items;
		json metadata;
		json sequenceMetadata;
		std::filesystem::path sequenceRoot;
		Clock::time_point submittedAt = Clock::now();
	};

	OpenNRCaptureFeature& owner;
	mutable std::mutex queueMutex;
	std::condition_variable queueCv;
	std::deque<PendingFrame> gpuQueue;
	std::deque<PendingFrame> writerQueue;
	std::thread worker;
	ComPtr<ID3D11Device> device;
	ComPtr<ID3D11DeviceContext> context;
	bool workerStop = false;
	bool workerRunning = false;

	bool recording = false;
	bool activeFrame = false;
	bool activeFullFrame = false;
	bool stopAfterActiveFrame = false;
	bool singleShot = false;
	bool burstMode = false;
	bool pendingSingle = false;
	std::uint32_t burstRemaining = 0;
	std::uint64_t sequenceFrameId = 0;
	std::uint64_t sampleCount = 0;
	std::uint64_t activeSampleIndex = 0;
	std::uint64_t activeFrameId = 0;
	std::uint64_t droppedFramesBefore = 0;
	std::string sequenceId;
	std::filesystem::path sequenceRoot;
	json sequenceMetadata;
	OpenNRCaptureFeature::FrameInfo activeInfo;
	json activeMetadata;
	std::vector<PendingItem> activeItems;
	std::string activeFullFrameMode = "none";
	Clock::time_point nextDue = Clock::now();
	bool dueDeferred = false;
	std::array<bool, 3> previousHotkeyState{};

	std::atomic<std::uint64_t> droppedFrames{ 0 };
	std::atomic<std::uint64_t> backpressureEvents{ 0 };
	std::atomic<std::uint64_t> droppedItems{ 0 };
	std::atomic<std::uint64_t> writtenFrames{ 0 };
	std::atomic<std::uint64_t> failedFrames{ 0 };
	std::atomic<std::uint64_t> writtenItems{ 0 };

	~Impl()
	{
		StopWorker();
	}

	json BuildSequenceMetadata() const
	{
		json crops = json::array();
		for (const auto& crop : owner.settings.crops)
			crops.push_back({ { "center_x", crop.centerX }, { "center_y", crop.centerY } });
		const bool masterSequence = owner.settings.captureFullFrame && owner.settings.captureFullFrameSequence;
		const char* fullFramePolicy = !owner.settings.captureFullFrame ? "none" :
			owner.settings.captureFullFrameSequence ? "every_sample" :
			owner.settings.fullFrameEverySamples > 0 ? "periodic" : "none";
		return {
			{ "schema_version", 2 },
			{ "capture_version", "opennr-guides-2" },
			{ "dataset", "OpenNR-VR" },
			{ "sequence_id", sequenceId },
			{ "created_utc", std::chrono::duration_cast<std::chrono::milliseconds>(
				std::chrono::system_clock::now().time_since_epoch()).count() },
			{ "source", "OpenNR DLSSNR Feature 18 render textures" },
			{ "desktop_capture", false },
			{ "capture_full_frame", owner.settings.captureFullFrame },
			{ "capture_full_frame_sequence", owner.settings.captureFullFrameSequence },
			{ "full_frame_capture_policy", fullFramePolicy },
			{ "dataset_role", masterSequence ? "full_resolution_master_sequence" : "sampled_crop_sequence" },
			{ "training_crops_present", owner.settings.cropCount > 0 },
			{ "queue_capacity", ClampQueueCapacity(owner.settings.queueCapacity) },
			{ "queue_policy", "defer_until_capacity" },
			{ "crop_size", ClampCropSize(owner.settings.cropSize) },
			{ "crop_count", ClampCropCount(owner.settings.cropCount) },
			{ "full_frame_every_samples", owner.settings.fullFrameEverySamples },
			{ "capture_rate_fps", owner.settings.captureRateFps },
			{ "burst_frames", owner.settings.burstFrames },
			{ "history_reset_policy", "request_on_sequence_start" },
			{ "max_samples", owner.settings.maxSamples },
			{ "pre_nr", owner.settings.capturePreNR },
			{ "post_nr", owner.settings.capturePostNR },
			{ "raw_teacher", owner.settings.captureRawTeacher },
			{ "depth", owner.settings.captureDepth },
			{ "motion_vectors", owner.settings.captureMotionVectors },
			{ "renderer_conditionings", {
				{ "enabled", owner.settings.captureRendererConditionings },
				{ "source", "Skyrim deferred G-buffer render targets at the Neural Rendering call boundary" },
				{ "alignment", "native renderer coordinates; stereo color rectangle scaled to main-target dimensions; crop_rect is native pixels, not color pixels" },
				{ "channels", {
					{ "gbuffer_albedo", "ALBEDO / kINDIRECT; base-color G-buffer" },
					{ "gbuffer_normal_roughness", "NORMALROUGHNESS / kRAWINDIRECT_DOWNSCALED; encoded view-space normal and glossiness" },
					{ "gbuffer_masks", "MASKS / kRAWINDIRECT_PREVIOUS; engine-defined material/lighting mask channels" },
					{ "gbuffer_masks2", "MASKS2 / kRAWINDIRECT_PREVIOUS_DOWNSCALED; vertex-AO mask channel" },
					{ "gbuffer_specular", "SPECULAR / kINDIRECT_DOWNSCALED; deferred specular accumulation" },
					{ "gbuffer_reflectance", "REFLECTANCE / kRAWINDIRECT; reflectance contribution when populated" }
				} },
				{ "not_exposed", {
					{ "illumination", "No single verified lighting-only tensor is exposed at this boundary" },
					{ "material_object_semantics", "No object/material ID or semantic label buffer is exposed" },
					{ "teacher_history", "The carried history inside nvngx_dlssnr.dll is opaque; only reset metadata is recorded" }
				} }
			} },
			{ "write_color_previews", owner.settings.writeColorPreviews },
			{ "left_eye", owner.settings.captureLeftEye },
			{ "right_eye", owner.settings.captureRightEye },
			{ "toggle_capture_key", owner.settings.toggleCaptureKey },
			{ "single_capture_key", owner.settings.singleCaptureKey },
			{ "burst_capture_key", owner.settings.burstCaptureKey },
			{ "output_directory", owner.settings.outputDirectory },
			{ "crop_presets", crops }
		};
	}

	void Start()
	{
		if (!owner.settings.enableCapture) {
			logger::warn("OpenNR Capture is disabled in settings; enable it before recording");
			return;
		}
		if (recording)
			return;
		const auto outputRoot = ResolveOutputRoot(owner.settings.outputDirectory);
		if (outputRoot.empty())
			return;
		// A new sequence must begin from a known Feature 18 temporal state.  The
		// request is consumed on the render thread before the first eligible sample,
		// so the first frame's history_reset metadata describes the actual teacher
		// dispatch rather than relying on the user to open/close the UI menu.
		NeuralRendering::RequestHistoryReset();
		const auto timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
			std::chrono::system_clock::now().time_since_epoch()).count();
		std::error_code existsError;
		do {
			sequenceId = std::format("seq-{}-{}", timestamp, g_sequenceSerial.fetch_add(1, std::memory_order_relaxed));
			sequenceRoot = outputRoot / sequenceId;
			existsError.clear();
		} while (std::filesystem::exists(sequenceRoot, existsError) && !existsError);
		sequenceMetadata = BuildSequenceMetadata();
		sequenceFrameId = 0;
		sampleCount = 0;
		activeSampleIndex = 0;
		activeFrameId = 0;
		droppedFramesBefore = droppedFrames.load(std::memory_order_relaxed);
		nextDue = Clock::now();
		dueDeferred = false;
		recording = true;
		logger::info("OpenNR Capture started (history reset requested): {}", sequenceRoot.string());
	}

	void Stop()
	{
		recording = false;
		pendingSingle = false;
		burstRemaining = 0;
		burstMode = false;
		singleShot = false;
		dueDeferred = false;
		if (activeFrame)
			Abort();
		logger::info("OpenNR Capture stopped: sequence={} samples={} dropped={}", sequenceId, sampleCount,
			droppedFrames.load(std::memory_order_relaxed));
	}

	void RequestSingle()
	{
		if (!owner.settings.enableCapture)
			return;
		const bool wasRecording = recording;
		if (!recording)
			Start();
		if (recording) {
			pendingSingle = true;
			singleShot = !wasRecording;
		}
	}

	void RequestBurst()
	{
		if (!owner.settings.enableCapture)
			return;
		if (!recording)
			Start();
		if (recording) {
			burstRemaining = std::clamp(owner.settings.burstFrames, 1u, kMaxBurstFrames);
			burstMode = true;
			singleShot = false;
			// Start the finite burst immediately, then use the configured capture
			// cadence between samples instead of capturing every render frame.
			nextDue = Clock::now();
		}
	}

	void PollHotkeys()
	{
		// Capture must be explicitly enabled through the feature settings before
		// any key state is queried. This is also a defensive guard for callers
		// outside the normal Present hook.
		if (!owner.settings.enableCapture)
			return;

		// Query and map the immediate D3D11 context on the render thread. The
		// writer thread is deliberately limited to CPU-owned buffers and files.
		ProcessGpuReadbacks();

		const std::array<std::uint32_t, 3> keys{
			owner.settings.toggleCaptureKey,
			owner.settings.singleCaptureKey,
			owner.settings.burstCaptureKey
		};
		for (std::size_t index = 0; index < keys.size(); ++index) {
			const auto key = keys[index];
			const bool down = key != 0 && (GetAsyncKeyState(static_cast<int>(key)) & 0x8000) != 0;
			if (down && !previousHotkeyState[index]) {
				switch (index) {
				case 0:
					owner.ToggleCapture();
					break;
				case 1:
					owner.RequestSingle();
					break;
				case 2:
					owner.RequestBurst();
					break;
				default:
					break;
				}
			}
			previousHotkeyState[index] = down;
		}
	}

	bool IsDue() const
	{
		if (owner.settings.captureRateFps <= 0.0f)
			return true;
		return Clock::now() >= nextDue;
	}

	void ConsumeDue()
	{
		if (owner.settings.captureRateFps <= 0.0f)
			return;
		const auto now = Clock::now();
		const auto period = std::chrono::duration<double>(1.0 / std::max(owner.settings.captureRateFps, 0.01f));
		do {
			nextDue += std::chrono::duration_cast<Clock::duration>(period);
		} while (nextDue <= now);
	}

	bool Begin(const OpenNRCaptureFeature::FrameInfo& a_info)
	{
		if (activeFrame || !recording || !owner.settings.enableCapture)
			return false;

		bool due = false;
		bool finishAfterSample = false;
		const bool singleRequest = pendingSingle;
		const bool burstRequest = !singleRequest && burstRemaining > 0;
		if (pendingSingle) {
			due = true;
			finishAfterSample = singleShot;
		} else if (burstRemaining > 0) {
			// A burst is finite, but it must still honor capture_rate_fps. At high
			// render rates, issuing all GPU copies back-to-back can exhaust the
			// bounded readback/writer pipeline even when the machine is otherwise
			// healthy.
			due = IsDue();
			finishAfterSample = burstMode && burstRemaining == 1;
		} else {
			if (burstMode) {
				recording = false;
				burstMode = false;
			}
			due = IsDue();
		}
		if (!due)
			return false;

		const auto maxSamples = std::min<std::uint32_t>(owner.settings.maxSamples, kMaxSamples);
		if (maxSamples != 0 && sampleCount >= maxSamples) {
			recording = false;
			return false;
		}

		const auto capacity = ClampQueueCapacity(owner.settings.queueCapacity);
		{
			std::scoped_lock lock(queueMutex);
			if (gpuQueue.size() + writerQueue.size() >= capacity) {
				// Queue saturation is recoverable: keep the due sample pending and
				// retry once the GPU/readback or writer queue has room. Do not call
				// this a dropped frame because no sample was accepted yet.
				if (!dueDeferred) {
					backpressureEvents.fetch_add(1, std::memory_order_relaxed);
					dueDeferred = true;
				}
				return false;
			}
		}
		dueDeferred = false;
		if (!singleRequest)
			ConsumeDue();
		// Preserve one-shot/burst requests when the bounded queue is full. They will
		// retry on the next eligible render frame without ever waiting on the writer.
		if (singleRequest)
			pendingSingle = false;
		if (burstRequest)
			--burstRemaining;

		activeFrame = true;
		activeInfo = a_info;
		activeFrameId = ++sequenceFrameId;
		activeSampleIndex = ++sampleCount;
		activeFullFrame = owner.settings.captureFullFrame &&
			(owner.settings.captureFullFrameSequence ||
				(owner.settings.fullFrameEverySamples > 0 &&
					activeSampleIndex % owner.settings.fullFrameEverySamples == 0));
		activeFullFrameMode = activeFullFrame ?
			(owner.settings.captureFullFrameSequence ? "sequence" : "periodic") : "none";
		stopAfterActiveFrame = finishAfterSample;
		activeItems.clear();
		activeMetadata = {
			{ "schema_version", 2 },
			{ "capture_version", "opennr-guides-2" },
			{ "sequence_id", sequenceId },
			{ "frame_id", activeFrameId },
			{ "sample_index", activeSampleIndex },
			{ "host_frame", a_info.hostFrame },
			{ "route", a_info.route },
			{ "color_width", a_info.colorWidth },
			{ "color_height", a_info.colorHeight },
			{ "model_width", a_info.modelWidth },
			{ "model_height", a_info.modelHeight },
			{ "model_resolution_percent", a_info.modelResolutionPercent },
			{ "guide_width", a_info.guideWidth },
			{ "guide_height", a_info.guideHeight },
			{ "pass_count", a_info.passCount },
			{ "motion_vector_scale_x", a_info.motionVectorScaleX },
			{ "motion_vector_scale_y", a_info.motionVectorScaleY },
			{ "motion_vector_contract", "exact_feature18_bound_resource" },
			{ "history_reset", a_info.historyReset },
			{ "temporal_reuse", a_info.temporalReuse },
			{ "temporal_frame_index", a_info.temporalFrameIndex },
			{ "temporal_skipped_since_full", a_info.temporalSkippedSinceFull },
			{ "temporal_next_anchor_reset", a_info.temporalNextAnchorReset },
			{ "renderer_conditionings_requested", owner.settings.captureRendererConditionings },
			{ "renderer_conditionings_available", a_info.rendererConditioningsAvailable },
			{ "teacher_settings", {
				{ "intensity", a_info.intensity },
				{ "local_tone_strength", a_info.localToneStrength },
				{ "local_structure_strength", a_info.localStructureStrength },
				{ "skin_structure_strength", a_info.skinStructureStrength },
				{ "style", a_info.style },
				{ "use_auto_mask", a_info.useAutoMask },
				{ "ui_correction", a_info.uiCorrection }
			} },
			{ "capture_rate_fps", owner.settings.captureRateFps },
			{ "full_frame_validation", activeFullFrame },
			{ "full_frame_mode", activeFullFrameMode },
			{ "master_sequence_frame", activeFullFrameMode == "sequence" },
			{ "dropped_frames_before", droppedFramesBefore },
			{ "backpressure_events_before", backpressureEvents.load(std::memory_order_relaxed) },
			{ "artifacts", json::array() }
		};
		return true;
	}

	bool Capture(ID3D11Resource* a_source, std::uint32_t a_sourceX, std::uint32_t a_sourceY,
		std::uint32_t a_sourceWidth, std::uint32_t a_sourceHeight, std::string_view a_stage,
		std::uint32_t a_eyeIndex, bool a_fullFrame, bool a_writePreview)
	{
		if (!activeFrame || !a_source || a_sourceWidth == 0 || a_sourceHeight == 0 ||
			a_eyeIndex > 1 || (a_eyeIndex == 0 && !owner.settings.captureLeftEye) ||
			(a_eyeIndex == 1 && !owner.settings.captureRightEye))
			return false;

		ComPtr<ID3D11Texture2D> sourceTexture;
		if (FAILED(a_source->QueryInterface(IID_PPV_ARGS(&sourceTexture))))
			return false;
		D3D11_TEXTURE2D_DESC sourceDesc{};
		sourceTexture->GetDesc(&sourceDesc);
		if (sourceDesc.ArraySize != 1 || sourceDesc.MipLevels != 1 || sourceDesc.SampleDesc.Count != 1 ||
			static_cast<std::uint64_t>(a_sourceX) + a_sourceWidth > sourceDesc.Width ||
			static_cast<std::uint64_t>(a_sourceY) + a_sourceHeight > sourceDesc.Height)
			return false;

		if (!device || !context || globals::d3d::device != device.Get() || globals::d3d::context != context.Get()) {
			device = globals::d3d::device;
			context = globals::d3d::context;
		}
		if (!device || !context)
			return false;

		const std::uint32_t cropCount = a_fullFrame ? 1 : ClampCropCount(owner.settings.cropCount);
		const std::uint32_t cropSize = std::min({ ClampCropSize(owner.settings.cropSize), a_sourceWidth, a_sourceHeight });
		if (cropSize == 0)
			return false;

		const auto stage = SanitizeComponent(a_stage);
		const auto frameDirectory = sequenceRoot / "frames" / std::format("frame_{:08}", activeFrameId);
		bool queued = false;
		for (std::uint32_t cropIndex = 0; cropIndex < cropCount; ++cropIndex) {
			std::uint32_t cropX = 0;
			std::uint32_t cropY = 0;
			std::uint32_t width = cropSize;
			std::uint32_t height = cropSize;
			if (a_fullFrame) {
				width = a_sourceWidth;
				height = a_sourceHeight;
			} else {
				const auto& preset = cropIndex < owner.settings.crops.size() ? owner.settings.crops[cropIndex] : OpenNRCaptureFeature::CropPreset{};
				const float centerX = std::clamp(preset.centerX, 0.0f, 1.0f);
				const float centerY = std::clamp(preset.centerY, 0.0f, 1.0f);
				cropX = static_cast<std::uint32_t>(std::lround(centerX * static_cast<float>(a_sourceWidth - width)));
				cropY = static_cast<std::uint32_t>(std::lround(centerY * static_cast<float>(a_sourceHeight - height)));
			}

			D3D11_TEXTURE2D_DESC stagingDesc = sourceDesc;
			stagingDesc.Width = width;
			stagingDesc.Height = height;
			stagingDesc.Usage = D3D11_USAGE_STAGING;
			stagingDesc.BindFlags = 0;
			stagingDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
			stagingDesc.MiscFlags = 0;
			stagingDesc.MipLevels = 1;
			stagingDesc.ArraySize = 1;
			stagingDesc.SampleDesc.Count = 1;
			stagingDesc.SampleDesc.Quality = 0;

			PendingItem item;
			item.desc = stagingDesc;
			item.writePreview = a_writePreview;
			if (FAILED(device->CreateTexture2D(&stagingDesc, nullptr, &item.staging))) {
				droppedItems.fetch_add(1, std::memory_order_relaxed);
				continue;
			}
			Util::SetResourceName(item.staging.Get(), "OpenNRCapture::Staging::%s::eye%u::%u", stage.c_str(), a_eyeIndex, cropIndex);

			D3D11_BOX sourceBox{
				a_sourceX + cropX,
				a_sourceY + cropY,
				0,
				a_sourceX + cropX + width,
				a_sourceY + cropY + height,
				1
			};
			context->CopySubresourceRegion(item.staging.Get(), 0, 0, 0, 0, sourceTexture.Get(), 0, &sourceBox);

			const auto suffix = a_fullFrame ? "full" : std::format("crop{:02}", cropIndex);
			if (a_writePreview)
				item.pngPath = frameDirectory / std::format("{}_eye{}_{}.png", stage, a_eyeIndex, suffix);
			item.rawPath = frameDirectory / std::format("{}_eye{}_{}.raw.bin", stage, a_eyeIndex, suffix);
			item.metadataIndex = activeMetadata["artifacts"].size();
			activeMetadata["artifacts"].push_back({
				{ "stage", stage },
				{ "eye", a_eyeIndex },
				{ "crop_index", cropIndex },
				{ "full_frame", a_fullFrame },
				{ "source_rect", { { "x", a_sourceX }, { "y", a_sourceY }, { "width", a_sourceWidth }, { "height", a_sourceHeight } } },
				{ "crop_rect", { { "x", cropX }, { "y", cropY }, { "width", width }, { "height", height } } },
				{ "width", width },
				{ "height", height },
				{ "format", static_cast<std::uint32_t>(stagingDesc.Format) },
				{ "format_name", FormatName(stagingDesc.Format) },
				{ "png_path", a_writePreview ? item.pngPath.lexically_relative(sequenceRoot).generic_string() : std::string{} },
				{ "raw_path", item.rawPath.lexically_relative(sequenceRoot).generic_string() },
				{ "png_required", a_writePreview },
				{ "raw_required", true },
				{ "png_written", false },
				{ "raw_written", false },
				{ "png_is_lossless_rgb8", false },
				{ "row_pitch", 0 }
			});
			activeItems.push_back(std::move(item));
			queued = true;
		}
		return queued;
	}

	void End()
	{
		if (!activeFrame)
			return;
		if (activeItems.empty()) {
			Abort();
			return;
		}
		if (!device || !context) {
			Abort();
			return;
		}

		D3D11_QUERY_DESC queryDesc{ D3D11_QUERY_EVENT, 0 };
		ComPtr<ID3D11Query> query;
		if (FAILED(device->CreateQuery(&queryDesc, &query))) {
			Abort();
			return;
		}
		context->End(query.Get());

		PendingFrame pending;
		pending.context = context;
		pending.completion = std::move(query);
		pending.items = std::move(activeItems);
		pending.metadata = std::move(activeMetadata);
		pending.sequenceRoot = sequenceRoot;
		pending.sequenceMetadata = sequenceMetadata;
		pending.submittedAt = Clock::now();

		EnsureWorker();
		bool enqueued = false;
		{
			std::scoped_lock lock(queueMutex);
			const auto capacity = ClampQueueCapacity(owner.settings.queueCapacity);
			if (gpuQueue.size() + writerQueue.size() < capacity) {
				gpuQueue.push_back(std::move(pending));
				enqueued = true;
			} else {
				droppedFrames.fetch_add(1, std::memory_order_relaxed);
			}
		}
		if (!enqueued)
			logger::warn("OpenNR Capture queue became full before frame {} could be enqueued", activeFrameId);

		const bool stop = stopAfterActiveFrame;
		activeFrame = false;
		activeFullFrame = false;
		activeFullFrameMode = "none";
		stopAfterActiveFrame = false;
		activeItems.clear();
		activeMetadata = {};
		if (stop) {
			recording = false;
			singleShot = false;
			burstMode = false;
		}
	}

	void Abort()
	{
		activeFrame = false;
		activeFullFrame = false;
		activeFullFrameMode = "none";
		stopAfterActiveFrame = false;
		activeItems.clear();
		activeMetadata = {};
	}

	void EnsureWorker()
	{
		if (worker.joinable())
			return;
		device = globals::d3d::device;
		context = globals::d3d::context;
		if (!device || !context)
			return;
		workerStop = false;
		workerRunning = true;
		worker = std::thread([this]() { WorkerLoop(); });
	}

	void StopWorker()
	{
		if (!worker.joinable())
			return;
		{
			std::scoped_lock lock(queueMutex);
			workerStop = true;
		}
		queueCv.notify_all();
		worker.join();
		workerRunning = false;
		std::scoped_lock lock(queueMutex);
		gpuQueue.clear();
		writerQueue.clear();
	}

	bool Readback(ID3D11DeviceContext* a_context, PendingItem& a_item,
		std::vector<std::uint8_t>& a_bytes, std::uint32_t& a_rowPitch)
	{
		if (!a_context || !a_item.staging)
			return false;
		D3D11_MAPPED_SUBRESOURCE mapped{};
		if (FAILED(a_context->Map(a_item.staging.Get(), 0, D3D11_MAP_READ, 0, &mapped)))
			return false;
		const auto bytesPerPixel = BytesPerPixel(a_item.desc.Format);
		const auto packedRowBytes = bytesPerPixel == 0 ? mapped.RowPitch : a_item.desc.Width * bytesPerPixel;
		if (!mapped.pData || mapped.RowPitch < packedRowBytes) {
			a_context->Unmap(a_item.staging.Get(), 0);
			return false;
		}
		a_rowPitch = mapped.RowPitch;
		a_bytes.resize(static_cast<std::size_t>(packedRowBytes) * a_item.desc.Height);
		for (std::uint32_t row = 0; row < a_item.desc.Height; ++row) {
			std::memcpy(a_bytes.data() + static_cast<std::size_t>(row) * packedRowBytes,
				static_cast<const std::uint8_t*>(mapped.pData) + static_cast<std::size_t>(row) * mapped.RowPitch,
				packedRowBytes);
		}
		a_context->Unmap(a_item.staging.Get(), 0);
		return true;
	}

	void ProcessGpuReadbacks()
	{
		// Keep all immediate-context query and map calls on the render thread. The
		// writer thread receives CPU-owned bytes only.
		if (gpuQueue.empty())
			return;
		{
			std::scoped_lock lock(queueMutex);
			if (writerQueue.size() >= ClampQueueCapacity(owner.settings.queueCapacity))
				return;
		}

		auto& frame = gpuQueue.front();
		BOOL complete = FALSE;
		const HRESULT result = frame.context && frame.completion ?
			frame.context->GetData(frame.completion.Get(), &complete, sizeof(complete), D3D11_ASYNC_GETDATA_DONOTFLUSH) :
			E_POINTER;
		if (result == S_FALSE && Clock::now() - frame.submittedAt <= kGpuReadbackTimeout)
			return;
		if (FAILED(result) || result == S_FALSE || complete == FALSE) {
			frame.metadata["failure_reason"] = "gpu_query_timeout_or_failure";
		} else {
			bool allReadback = true;
			for (auto& item : frame.items) {
				item.readbackReady = Readback(frame.context.Get(), item, item.bytes, item.rowPitch);
				frame.metadata["artifacts"][item.metadataIndex]["row_pitch"] = item.rowPitch;
				allReadback = allReadback && item.readbackReady;
			}
			if (!allReadback)
				frame.metadata["failure_reason"] = "gpu_readback_failed";
		}
		// Do not move any D3D11 resource ownership to the writer thread, including
		// frames whose query or readback failed.
		for (auto& item : frame.items)
			item.staging.Reset();

		frame.completion.Reset();
		frame.context.Reset();
		PendingFrame ready = std::move(frame);
		gpuQueue.pop_front();
		{
			std::scoped_lock lock(queueMutex);
			writerQueue.push_back(std::move(ready));
		}
		queueCv.notify_one();
	}

	bool ConvertToRgb8(const PendingItem& a_item, const std::vector<std::uint8_t>& a_bytes,
		std::vector<std::uint8_t>& a_rgb)
	{
		const auto pixelCount = static_cast<std::size_t>(a_item.desc.Width) * a_item.desc.Height;
		a_rgb.resize(pixelCount * 3);
		const auto format = a_item.desc.Format;
		for (std::size_t index = 0; index < pixelCount; ++index) {
			const auto* source = a_bytes.data() + index * BytesPerPixel(format);
			std::uint8_t red = 0;
			std::uint8_t green = 0;
			std::uint8_t blue = 0;
			switch (format) {
			case DXGI_FORMAT_R8G8B8A8_TYPELESS:
			case DXGI_FORMAT_R8G8B8A8_UNORM:
			case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
				red = source[0];
				green = source[1];
				blue = source[2];
				break;
			case DXGI_FORMAT_B8G8R8A8_TYPELESS:
			case DXGI_FORMAT_B8G8R8A8_UNORM:
			case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
			case DXGI_FORMAT_B8G8R8X8_TYPELESS:
			case DXGI_FORMAT_B8G8R8X8_UNORM:
				red = source[2];
				green = source[1];
				blue = source[0];
				break;
			case DXGI_FORMAT_R10G10B10A2_TYPELESS:
			case DXGI_FORMAT_R10G10B10A2_UNORM: {
				std::uint32_t packed = 0;
				std::memcpy(&packed, source, sizeof(packed));
				red = ToByte(static_cast<float>(packed & 0x3FFu) / 1023.0f);
				green = ToByte(static_cast<float>((packed >> 10) & 0x3FFu) / 1023.0f);
				blue = ToByte(static_cast<float>((packed >> 20) & 0x3FFu) / 1023.0f);
				break;
			}
			case DXGI_FORMAT_R16G16B16A16_TYPELESS:
			case DXGI_FORMAT_R16G16B16A16_UNORM: {
				std::uint16_t channels[4]{};
				std::memcpy(channels, source, sizeof(channels));
				red = ToByte(static_cast<float>(channels[0]) / 65535.0f);
				green = ToByte(static_cast<float>(channels[1]) / 65535.0f);
				blue = ToByte(static_cast<float>(channels[2]) / 65535.0f);
				break;
			}
			case DXGI_FORMAT_R16G16B16A16_FLOAT: {
				std::uint16_t channels[4]{};
				std::memcpy(channels, source, sizeof(channels));
				red = ToSrgbByte(channels[0] == 0x7C00 ? 1.0f : HalfToFloat(channels[0]));
				green = ToSrgbByte(channels[1] == 0x7C00 ? 1.0f : HalfToFloat(channels[1]));
				blue = ToSrgbByte(channels[2] == 0x7C00 ? 1.0f : HalfToFloat(channels[2]));
				break;
			}
			default:
				return false;
			}
			a_rgb[index * 3 + 0] = red;
			a_rgb[index * 3 + 1] = green;
			a_rgb[index * 3 + 2] = blue;
		}
		return true;
	}

	bool WriteRaw(const std::filesystem::path& a_path, const std::vector<std::uint8_t>& a_bytes)
	{
		std::error_code ec;
		std::filesystem::create_directories(a_path.parent_path(), ec);
		if (ec)
			return false;
		const auto temporary = a_path.string() + ".tmp";
		{
			std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
			if (!stream)
				return false;
			stream.write(reinterpret_cast<const char*>(a_bytes.data()), static_cast<std::streamsize>(a_bytes.size()));
			if (!stream)
				return false;
		}
		return RenameTemporary(temporary, a_path);
	}

	bool WritePng(const PendingItem& a_item, const std::vector<std::uint8_t>& a_rgb)
	{
		std::error_code ec;
		std::filesystem::create_directories(a_item.pngPath.parent_path(), ec);
		if (ec)
			return false;
		const auto temporary = a_item.pngPath.string() + ".tmp.png";
		const int result = stbi_write_png(temporary.c_str(), static_cast<int>(a_item.desc.Width),
			static_cast<int>(a_item.desc.Height), 3, a_rgb.data(), static_cast<int>(a_item.desc.Width * 3));
		if (result == 0)
			return false;
		return RenameTemporary(temporary, a_item.pngPath);
	}

	void EnsureSequenceManifest(const PendingFrame& a_frame)
	{
		std::error_code ec;
		const auto path = a_frame.sequenceRoot / "sequence.json";
		if (!std::filesystem::exists(path, ec))
			WriteJsonAtomic(path, a_frame.sequenceMetadata);
	}

	bool AppendFrameRecord(PendingFrame& a_frame)
	{
		std::error_code ec;
		std::filesystem::create_directories(a_frame.sequenceRoot, ec);
		if (ec)
			return false;
		std::ofstream stream(a_frame.sequenceRoot / "frames.jsonl", std::ios::binary | std::ios::app);
		if (!stream)
			return false;
		const auto line = a_frame.metadata.dump();
		stream.write(line.data(), static_cast<std::streamsize>(line.size()));
		stream.put('\n');
		return static_cast<bool>(stream);
	}

	void WriteFrame(PendingFrame& a_frame)
	{
		EnsureSequenceManifest(a_frame);
		bool allComplete = true;
		bool anyComplete = false;
		for (auto& item : a_frame.items) {
			bool rawWritten = false;
			bool pngWritten = false;
			bool pngLosslessRgb8 = false;
			if (item.readbackReady) {
				rawWritten = WriteRaw(item.rawPath, item.bytes);
				std::vector<std::uint8_t> rgb;
				if (item.writePreview && ConvertToRgb8(item, item.bytes, rgb)) {
					pngWritten = WritePng(item, rgb);
					pngLosslessRgb8 = pngWritten;
				}
			}
			a_frame.metadata["artifacts"][item.metadataIndex]["row_pitch"] = item.rowPitch;
			a_frame.metadata["artifacts"][item.metadataIndex]["raw_written"] = rawWritten;
			a_frame.metadata["artifacts"][item.metadataIndex]["png_written"] = pngWritten;
			a_frame.metadata["artifacts"][item.metadataIndex]["png_is_lossless_rgb8"] = pngLosslessRgb8;
			allComplete = allComplete && rawWritten && (!item.writePreview || pngWritten);
			anyComplete = anyComplete || rawWritten;
			if (rawWritten)
				writtenItems.fetch_add(1, std::memory_order_relaxed);
		}
		if (!allComplete && !a_frame.metadata.contains("failure_reason"))
			a_frame.metadata["failure_reason"] = "gpu_readback_or_file_write_failed";
		a_frame.metadata["status"] = allComplete ? "complete" : (anyComplete ? "partial" : "failed");
		a_frame.metadata["written_utc"] = std::chrono::duration_cast<std::chrono::milliseconds>(
			std::chrono::system_clock::now().time_since_epoch()).count();

		if (!AppendFrameRecord(a_frame)) {
			failedFrames.fetch_add(1, std::memory_order_relaxed);
			return;
		}
		if (allComplete)
			writtenFrames.fetch_add(1, std::memory_order_relaxed);
		else
			failedFrames.fetch_add(1, std::memory_order_relaxed);
	}

	void WorkerLoop()
	{
		CoInitializeEx(nullptr, COINIT_MULTITHREADED);
		for (;;) {
			PendingFrame frame;
			{
				std::unique_lock lock(queueMutex);
				queueCv.wait(lock, [this]() { return workerStop || !writerQueue.empty(); });
				if (writerQueue.empty() && workerStop)
					break;
				frame = std::move(writerQueue.front());
				writerQueue.pop_front();
			}
			WriteFrame(frame);
		}
		CoUninitialize();
	}

	bool IsCapturing() const { return recording; }
	bool IsFullFrame() const { return activeFullFrame; }

	json Diagnostics() const
	{
		std::size_t queued = 0;
		{
			std::scoped_lock lock(queueMutex);
			queued = gpuQueue.size() + writerQueue.size();
		}
		return {
			{ "recording", recording },
			{ "active_frame", activeFrame },
			{ "sequence_id", sequenceId },
			{ "next_frame_id", sequenceFrameId + 1 },
			{ "captured_samples", sampleCount },
			{ "queued_frames", queued },
			{ "queue_capacity", ClampQueueCapacity(owner.settings.queueCapacity) },
			{ "written_frames", writtenFrames.load(std::memory_order_relaxed) },
			{ "written_items", writtenItems.load(std::memory_order_relaxed) },
			{ "dropped_frames", droppedFrames.load(std::memory_order_relaxed) },
			{ "backpressure_events", backpressureEvents.load(std::memory_order_relaxed) },
			{ "dropped_items", droppedItems.load(std::memory_order_relaxed) },
			{ "failed_frames", failedFrames.load(std::memory_order_relaxed) },
			{ "capture_rate_fps", owner.settings.captureRateFps },
			{ "crop_size", ClampCropSize(owner.settings.cropSize) },
			{ "crop_count", ClampCropCount(owner.settings.cropCount) },
			{ "capture_full_frame", owner.settings.captureFullFrame },
			{ "capture_full_frame_sequence", owner.settings.captureFullFrameSequence },
			{ "full_frame_every_samples", owner.settings.fullFrameEverySamples },
			{ "full_frame_capture_policy", owner.settings.captureFullFrame ?
				(owner.settings.captureFullFrameSequence ? "every_sample" :
					(owner.settings.fullFrameEverySamples > 0 ? "periodic" : "none")) : "none" },
			{ "active_full_frame_mode", activeFullFrameMode }
		};
	}
};

OpenNRCaptureFeature::OpenNRCaptureFeature() : impl_(std::make_unique<Impl>(*this)) {}
OpenNRCaptureFeature::~OpenNRCaptureFeature() = default;

void OpenNRCaptureFeature::PollHotkeys() { impl_->PollHotkeys(); }
void OpenNRCaptureFeature::StartCapture() { impl_->Start(); }
void OpenNRCaptureFeature::StopCapture() { impl_->Stop(); }
void OpenNRCaptureFeature::ToggleCapture()
{
	if (impl_->IsCapturing())
		StopCapture();
	else
		StartCapture();
}
void OpenNRCaptureFeature::RequestSingle() { impl_->RequestSingle(); }
void OpenNRCaptureFeature::RequestBurst() { impl_->RequestBurst(); }
bool OpenNRCaptureFeature::BeginFrame(const FrameInfo& a_info) { return impl_->Begin(a_info); }
bool OpenNRCaptureFeature::CaptureTexture(ID3D11Resource* a_source, std::uint32_t a_sourceX, std::uint32_t a_sourceY,
	std::uint32_t a_sourceWidth, std::uint32_t a_sourceHeight, std::string_view a_stage,
	std::uint32_t a_eyeIndex, bool a_fullFrame, bool a_writePreview)
{
	return impl_->Capture(a_source, a_sourceX, a_sourceY, a_sourceWidth, a_sourceHeight, a_stage, a_eyeIndex, a_fullFrame, a_writePreview);
}
void OpenNRCaptureFeature::EndFrame() { impl_->End(); }
void OpenNRCaptureFeature::RecordRendererConditioningDiagnostic(const json& a_diagnostic)
{
	if (!impl_->activeFrame)
		return;
	impl_->activeMetadata["renderer_conditioning_diagnostics"].push_back(a_diagnostic);
	if (impl_->activeSampleIndex == 1)
		logger::info("[OpenNR Conditioning] sequence={} host_frame={} {}", impl_->sequenceId,
			impl_->activeInfo.hostFrame, a_diagnostic.dump());
}
void OpenNRCaptureFeature::AbortFrame() { impl_->Abort(); }
bool OpenNRCaptureFeature::IsCapturing() const { return impl_->IsCapturing(); }
bool OpenNRCaptureFeature::IsFullFrameValidationFrame() const { return impl_->IsFullFrame(); }

void OpenNRCaptureFeature::RestoreDefaultSettings()
{
	settings = Settings{};
}

void OpenNRCaptureFeature::LoadSettings(json& a_json)
{
	settings.enableCapture = a_json.value("enable_capture", settings.enableCapture);
	settings.capturePreNR = a_json.value("capture_pre_nr", settings.capturePreNR);
	settings.capturePostNR = a_json.value("capture_post_nr", settings.capturePostNR);
	settings.captureRawTeacher = a_json.value("capture_raw_teacher", settings.captureRawTeacher);
	settings.captureDepth = a_json.value("capture_depth", settings.captureDepth);
	settings.captureMotionVectors = a_json.value("capture_motion_vectors", settings.captureMotionVectors);
	settings.captureRendererConditionings = a_json.value("capture_renderer_conditionings", settings.captureRendererConditionings);
	settings.writeColorPreviews = a_json.value("write_color_previews", settings.writeColorPreviews);
	settings.captureFullFrame = a_json.value("capture_full_frame", settings.captureFullFrame);
	settings.captureFullFrameSequence = a_json.value("capture_full_frame_sequence", settings.captureFullFrameSequence);
	settings.captureLeftEye = a_json.value("capture_left_eye", settings.captureLeftEye);
	settings.captureRightEye = a_json.value("capture_right_eye", settings.captureRightEye);
	settings.captureRateFps = std::clamp(a_json.value("capture_rate_fps", settings.captureRateFps), 0.0f, 240.0f);
	settings.burstFrames = std::clamp(a_json.value("burst_frames", settings.burstFrames), 1u, kMaxBurstFrames);
	settings.cropSize = ClampCropSize(a_json.value("crop_size", settings.cropSize));
	settings.cropCount = ClampCropCount(a_json.value("crop_count", settings.cropCount));
	settings.queueCapacity = ClampQueueCapacity(a_json.value("queue_capacity", settings.queueCapacity));
	settings.fullFrameEverySamples = a_json.value("full_frame_every_samples", settings.fullFrameEverySamples);
	settings.maxSamples = std::min<std::uint32_t>(a_json.value("max_samples", settings.maxSamples), kMaxSamples);
	settings.toggleCaptureKey = a_json.value("toggle_capture_key", settings.toggleCaptureKey);
	settings.singleCaptureKey = a_json.value("single_capture_key", settings.singleCaptureKey);
	settings.burstCaptureKey = a_json.value("burst_capture_key", settings.burstCaptureKey);
	settings.outputDirectory = a_json.value("output_directory", settings.outputDirectory);
	if (a_json.contains("crops") && a_json["crops"].is_array()) {
		settings.crops.clear();
		for (const auto& crop : a_json["crops"]) {
			if (!crop.is_object())
				continue;
			settings.crops.push_back({
				std::clamp(crop.value("center_x", 0.5f), 0.0f, 1.0f),
				std::clamp(crop.value("center_y", 0.5f), 0.0f, 1.0f)
			});
			if (settings.crops.size() == kMaxCropCount)
				break;
		}
	}
	if (settings.crops.empty())
		settings.crops = Settings{}.crops;
}

void OpenNRCaptureFeature::SaveSettings(json& a_json)
{
	a_json["enable_capture"] = settings.enableCapture;
	a_json["capture_pre_nr"] = settings.capturePreNR;
	a_json["capture_post_nr"] = settings.capturePostNR;
	a_json["capture_raw_teacher"] = settings.captureRawTeacher;
	a_json["capture_depth"] = settings.captureDepth;
	a_json["capture_motion_vectors"] = settings.captureMotionVectors;
	a_json["capture_renderer_conditionings"] = settings.captureRendererConditionings;
	a_json["write_color_previews"] = settings.writeColorPreviews;
	a_json["capture_full_frame"] = settings.captureFullFrame;
	a_json["capture_full_frame_sequence"] = settings.captureFullFrameSequence;
	a_json["capture_left_eye"] = settings.captureLeftEye;
	a_json["capture_right_eye"] = settings.captureRightEye;
	a_json["capture_rate_fps"] = settings.captureRateFps;
	a_json["burst_frames"] = settings.burstFrames;
	a_json["crop_size"] = settings.cropSize;
	a_json["crop_count"] = settings.cropCount;
	a_json["queue_capacity"] = settings.queueCapacity;
	a_json["full_frame_every_samples"] = settings.fullFrameEverySamples;
	a_json["max_samples"] = settings.maxSamples;
	a_json["toggle_capture_key"] = settings.toggleCaptureKey;
	a_json["single_capture_key"] = settings.singleCaptureKey;
	a_json["burst_capture_key"] = settings.burstCaptureKey;
	a_json["output_directory"] = settings.outputDirectory;
	a_json["crops"] = json::array();
	for (const auto& crop : settings.crops)
		a_json["crops"].push_back({ { "center_x", crop.centerX }, { "center_y", crop.centerY } });
}

void OpenNRCaptureFeature::DrawSettings()
{
	ImGui::TextWrapped("Captures GPU render textures around Feature 18. It never captures the desktop or presented swap chain.");
	ImGui::Checkbox("Enable capture", &settings.enableCapture);
	ImGui::Checkbox("Capture pre-NR input", &settings.capturePreNR);
	ImGui::Checkbox("Capture post-NR teacher", &settings.capturePostNR);
	ImGui::Checkbox("Write raw teacher readback", &settings.captureRawTeacher);
	ImGui::Checkbox("Capture Feature 18 depth", &settings.captureDepth);
	ImGui::Checkbox("Capture Feature 18 motion vectors", &settings.captureMotionVectors);
	ImGui::Checkbox("Capture renderer G-buffer conditionings", &settings.captureRendererConditionings);
	if (settings.captureRendererConditionings)
		ImGui::TextWrapped("Opt-in: captures aligned albedo, normal/roughness, engine masks, specular, and reflectance. Illumination, semantic IDs, and exact teacher history are not exposed by this path.");
	ImGui::Checkbox("Write color PNG previews", &settings.writeColorPreviews);
	ImGui::Checkbox("Capture full-frame artifacts", &settings.captureFullFrame);
	ImGui::Checkbox("Full-resolution master sequence (every sample)", &settings.captureFullFrameSequence);
	if (settings.captureFullFrameSequence)
		ImGui::TextWrapped("Master mode writes complete per-eye color and native guide resources for every sampled frame, while keeping the configured training crops.");
	ImGui::Checkbox("Left eye", &settings.captureLeftEye);
	ImGui::Checkbox("Right eye", &settings.captureRightEye);
	ImGui::SliderFloat("Capture rate (frames/s)", &settings.captureRateFps, 0.0f, 120.0f, "%.1f");
	int cropSize = static_cast<int>(settings.cropSize);
	if (ImGui::SliderInt("Crop size", &cropSize, static_cast<int>(kMinCropSize), static_cast<int>(kMaxCropSize)))
		settings.cropSize = ClampCropSize(static_cast<std::uint32_t>(cropSize));
	int cropCount = static_cast<int>(settings.cropCount);
	if (ImGui::SliderInt("Crops per stage", &cropCount, 1, static_cast<int>(kMaxCropCount)))
		settings.cropCount = ClampCropCount(static_cast<std::uint32_t>(cropCount));
	int queueCapacity = static_cast<int>(settings.queueCapacity);
	if (ImGui::SliderInt("Queue capacity (frames)", &queueCapacity, 1, static_cast<int>(kMaxQueueCapacity)))
		settings.queueCapacity = ClampQueueCapacity(static_cast<std::uint32_t>(queueCapacity));
	int fullFrameEvery = static_cast<int>(settings.fullFrameEverySamples);
	if (ImGui::InputInt("Full frame every N samples", &fullFrameEvery))
		settings.fullFrameEverySamples = fullFrameEvery < 0 ? 0u : static_cast<std::uint32_t>(fullFrameEvery);
	int burstFrames = static_cast<int>(settings.burstFrames);
	if (ImGui::InputInt("Burst frames", &burstFrames))
		settings.burstFrames = std::clamp(burstFrames, 1, static_cast<int>(kMaxBurstFrames));
	ImGui::InputText("Output directory", &settings.outputDirectory);
	for (std::size_t cropIndex = 0; cropIndex < settings.cropCount && cropIndex < settings.crops.size(); ++cropIndex) {
		auto& crop = settings.crops[cropIndex];
		ImGui::PushID(static_cast<int>(cropIndex));
		ImGui::SliderFloat("Center X", &crop.centerX, 0.0f, 1.0f, "%.3f");
		ImGui::SliderFloat("Center Y", &crop.centerY, 0.0f, 1.0f, "%.3f");
		ImGui::PopID();
	}
	ImGui::Text("Hotkeys: [ start/stop, ] single, \\ burst");
	if (ImGui::Button("Start"))
		StartCapture();
	ImGui::SameLine();
	if (ImGui::Button("Stop"))
		StopCapture();
	ImGui::SameLine();
	if (ImGui::Button("Single"))
		RequestSingle();
	ImGui::SameLine();
	if (ImGui::Button("Burst"))
		RequestBurst();
	const auto diagnostics = GetDiagnostics();
	ImGui::Text("Sequence %s | queued %u/%u | written %u | dropped %u",
		diagnostics.value("sequence_id", std::string{}).c_str(),
		diagnostics.value("queued_frames", 0u), diagnostics.value("queue_capacity", 0u),
		diagnostics.value("written_frames", 0u), diagnostics.value("dropped_frames", 0u));
	ImGui::Text("Queue deferrals: %llu",
		static_cast<unsigned long long>(diagnostics.value("backpressure_events", std::uint64_t{ 0 })));
}

json OpenNRCaptureFeature::GetDiagnostics() { return impl_->Diagnostics(); }
json OpenNRCaptureFeature::GetDiagnostics() const { return impl_->Diagnostics(); }
json OpenNRCaptureFeature::GetRuntimeFlags()
{
	const auto diagnostics = GetDiagnostics();
	return {
		{ "recording", IsCapturing() },
		{ "full_frame_validation_frame", IsFullFrameValidationFrame() },
		{ "full_frame_mode", diagnostics.value("active_full_frame_mode", "none") }
	};
}
bool OpenNRCaptureFeature::SetRuntimeFlag(std::string_view a_name, bool a_value)
{
	if (a_name == "recording") {
		if (a_value)
			StartCapture();
		else
			StopCapture();
		return true;
	}
	return false;
}

void OpenNRCaptureFeature::RegisterUxActions()
{
	FEATURE_COMMAND("start", "Start an OpenNR GPU capture sequence", [](Feature* a_self, const json&) {
		static_cast<OpenNRCaptureFeature*>(a_self)->StartCapture();
	});
	FEATURE_COMMAND("stop", "Stop the OpenNR GPU capture sequence", [](Feature* a_self, const json&) {
		static_cast<OpenNRCaptureFeature*>(a_self)->StopCapture();
	});
	FEATURE_COMMAND("single", "Capture one eligible OpenNR frame", [](Feature* a_self, const json&) {
		static_cast<OpenNRCaptureFeature*>(a_self)->RequestSingle();
	});
	FEATURE_COMMAND("burst", "Capture the configured OpenNR burst", [](Feature* a_self, const json&) {
		static_cast<OpenNRCaptureFeature*>(a_self)->RequestBurst();
	});
	FEATURE_QUERY("status", "Return OpenNR capture queue and writer diagnostics", [](const Feature* a_self, const json&) -> json {
		return static_cast<const OpenNRCaptureFeature*>(a_self)->GetDiagnostics();
	});
}
