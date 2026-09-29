#pragma once

#include <nlohmann/json.hpp>

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

/**
 * @brief In-headset A/B benchmark for renderer settings.
 *
 * Applies each configured variant (a set of partial feature-settings patches),
 * lets it settle, records the SteamVR compositor's per-frame application GPU and
 * CPU times, and restores the user's settings between variants. Every variant
 * is bracketed by baseline blocks so drift is measured, not attributed to a
 * setting. Settings are never saved to disk by the benchmark; the original
 * values are restored on completion, cancellation, or failure.
 *
 * Variants come from Data/SKSE/Plugins/CommunityShaders/OpenNR-SettingsBenchmark.json
 * (editable), falling back to a built-in list. Results are written as JSON next
 * to the CommunityShaders log.
 */
namespace NeuralRendering::SettingsBenchmark
{
	using json = nlohmann::json;

	struct Patch
	{
		std::string feature;  ///< Feature short name, e.g. "ScreenSpaceGI"
		json settings;        ///< Partial settings blob, same shape as the feature's saved settings
	};

	struct Variant
	{
		std::string id;
		std::string label;
		std::string group;
		std::string note;
		std::vector<Patch> patches;
		bool enabled = true;
	};

	struct Config
	{
		std::uint32_t warmupFrames = 45;
		std::uint32_t measureFrames = 90;
		std::uint32_t repeats = 1;
		float countdownSeconds = 8.0f;
	};

	struct Result
	{
		std::string id;
		std::string label;
		std::string group;
		std::string error;
		float gpuDeltaMs = 0.0f;
		float gpuUncertaintyMs = 0.0f;
		float gpuVariantMs = 0.0f;
		float gpuBaselineMs = 0.0f;
		float cpuDeltaMs = 0.0f;
		std::uint32_t repeats = 0;
	};

	enum class Phase
	{
		Idle,
		Countdown,
		Switching,
		Warmup,
		Measuring,
		Finished,
		Cancelled,
		Failed,
	};

	struct Status
	{
		Phase phase = Phase::Idle;
		std::string message;
		std::string currentLabel;
		std::uint32_t block = 0;
		std::uint32_t blockCount = 0;
		std::uint32_t framesInBlock = 0;
		std::uint32_t framesNeeded = 0;
		bool paused = false;
		float countdownRemaining = 0.0f;
		std::filesystem::path resultPath;
		std::vector<Result> results;
	};

	/** @brief Variants from the JSON file, or the built-in list when it is absent/invalid. */
	std::vector<Variant>& Variants();
	Config& Configuration();
	/** @brief Reloads variants/config from disk (keeps built-ins on error). */
	void ReloadDefinitions();

	/** @brief Starts the benchmark; measurement begins after the countdown once no menu is open. */
	bool Start(std::string* error = nullptr);
	/** @brief Cancels a running benchmark and restores the original settings. */
	void Cancel();
	/**
	 * @brief Applies one variant's patches as the live settings (not saved; use the
	 * normal Save button to keep them). Refused while a benchmark is running.
	 */
	bool ApplyVariantPermanently(const std::string& id, std::string* error = nullptr);
	[[nodiscard]] bool IsRunning();
	[[nodiscard]] Status GetStatus();
	[[nodiscard]] const char* PhaseName(Phase phase);
	[[nodiscard]] json StatusJson();

	/** @brief Once per rendered world frame, on the render (main) thread. */
	void Tick();

	/** @brief ImGui panel for the Neural Rendering page. */
	void DrawPanel();
}
