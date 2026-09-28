#include "SettingsBenchmark.h"

#include "BenchmarkPolicy.h"
#include "Feature.h"
#include "Globals.h"
#include "SceneSettingsManager.h"
#include "State.h"
#include "Utils/FileSystem.h"
#include "Utils/SettingsPatch.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <ctime>
#include <format>
#include <fstream>
#include <map>
#include <mutex>
#include <set>

namespace NeuralRendering::SettingsBenchmark
{
	namespace
	{
		using Clock = std::chrono::steady_clock;

		constexpr const char* kDefinitionsFile = "SKSE/Plugins/CommunityShaders/OpenNR-SettingsBenchmark.json";

		// Built-in candidates. Each changes one thing, applies live (no restart, no
		// shader-define recompile), and targets either measured cost or effects the
		// NR model might plausibly stand in for. The HMD is the judge of quality.
		constexpr const char* kBuiltInDefinitions = R"json({
  "warmupFrames": 45,
  "measureFrames": 90,
  "repeats": 1,
  "variants": [
    { "id": "nr-off", "label": "Neural Rendering off (reference)", "group": "Reference",
      "note": "Cost of NR itself in this scene.",
      "patches": [ { "feature": "Upscaling", "settings": { "foveatedRender": { "neuralRenderingEnabled": false } } } ] },
    { "id": "nr-coverage-85", "label": "NR Coverage 85%", "group": "Neural Rendering",
      "note": "Full-resolution NR on the center; DLSS periphery.",
      "patches": [ { "feature": "Upscaling", "settings": { "foveatedRender": { "neuralRenderingCoverage": 85 } } } ] },
    { "id": "nr-coverage-80", "label": "NR Coverage 80%", "group": "Neural Rendering",
      "patches": [ { "feature": "Upscaling", "settings": { "foveatedRender": { "neuralRenderingCoverage": 80 } } } ] },
    { "id": "dlss-preset-j", "label": "DLSS preset J", "group": "DLSS",
      "note": "Transformer J instead of the Balanced default K.",
      "patches": [ { "feature": "Upscaling", "settings": { "presetDLSS": 1 } } ] },
    { "id": "dlss-preset-e", "label": "DLSS preset E (CNN, deprecated)", "group": "DLSS",
      "note": "Older CNN model; NR runs on top of its output. If the delta is ~0 the driver ignored the preset.",
      "patches": [ { "feature": "Upscaling", "settings": { "presetDLSS": 5 } } ] },
    { "id": "llf-shadow-formula", "label": "Point-light shadow budget: Formula (1 ms ext / 2 ms int)", "group": "Shadows",
      "note": "Caps LLF shadow-map redraw time; lights refresh less often, shadows stay.",
      "patches": [ { "feature": "LightLimitFix", "settings": { "ShadowSettings": { "BudgetMode": 2 } } } ] },
    { "id": "llf-shadow-cap", "label": "Point-light shadow redraws: 8 per frame, 2 ms", "group": "Shadows",
      "patches": [ { "feature": "LightLimitFix", "settings": { "ShadowSettings": { "RedrawBudgetMs": 2.0, "MaxRedrawPerFrame": 8 } } } ] },
    { "id": "ssgi-ao-lite", "label": "SSGI AO: 1 slice / 3 steps", "group": "Screen space",
      "note": "NR adds contact shading on faces and cloth; tests whether coarser AO is enough.",
      "patches": [ { "feature": "ScreenSpaceGI", "settings": { "NumSlices": 1, "NumSteps": 3 } } ] },
    { "id": "ssgi-ao-off", "label": "SSGI AO off", "group": "Screen space",
      "patches": [ { "feature": "ScreenSpaceGI", "settings": { "Enabled": false } } ] },
    { "id": "volumetric-q1", "label": "Volumetric lighting quality 1", "group": "Atmosphere",
      "patches": [ { "feature": "VolumetricLighting", "settings": { "ExteriorQuality": 1, "InteriorQuality": 1 } } ] },
    { "id": "parallax-shadows-off", "label": "Parallax self-shadows off", "group": "Materials",
      "note": "NR adds local structure; parallax depth itself stays.",
      "patches": [ { "feature": "ExtendedMaterials", "settings": { "EnableShadows": 0 } } ] },
    { "id": "parallax-off", "label": "Parallax off", "group": "Materials",
      "patches": [ { "feature": "ExtendedMaterials", "settings": { "EnableParallax": 0 } } ] },
    { "id": "hair-specular-off", "label": "Hair specular off", "group": "Materials",
      "patches": [ { "feature": "HairSpecular", "settings": { "Enabled": 0 } } ] },
    { "id": "terrain-blending-off", "label": "Terrain blending off", "group": "Geometry",
      "note": "Mostly measures the extra terrain depth pass; blending seams return.",
      "patches": [ { "feature": "TerrainBlending", "settings": { "Enabled": 0 } } ] },
    { "id": "grass-mesh-lod", "label": "Grass mesh LOD on", "group": "Geometry",
      "note": "Requires Grass Optimizations loaded at boot.",
      "patches": [ { "feature": "GrassOptimizations", "settings": { "EnableMeshLOD": true } } ] },
    { "id": "screen-space-shadows-off", "label": "Screen-space shadows off", "group": "Screen space", "enabled": false,
      "patches": [ { "feature": "ScreenSpaceShadows", "settings": { "Enable": 0 } } ] },
    { "id": "wetness-off", "label": "Wetness effects off (rain only)", "group": "Atmosphere", "enabled": false,
      "patches": [ { "feature": "WetnessEffects", "settings": { "EnableWetnessEffects": 0 } } ] }
  ]
})json";

		struct BlockRecord
		{
			int variant = Benchmark::kBaselineBlock;
			std::vector<float> gpu;
			std::vector<float> cpu;
			std::vector<float> interval;
			std::uint32_t reprojected = 0;
		};

		struct RunState
		{
			Phase phase = Phase::Idle;
			std::string message;
			std::vector<int> schedule;
			std::vector<int> activeVariants;  ///< indices into Variants()
			std::vector<BlockRecord> blocks;
			std::size_t block = 0;
			std::uint32_t warmupDone = 0;
			std::uint32_t lastFrameIndex = 0;
			bool haveFrameIndex = false;
			bool paused = false;
			float countdownRemaining = 0.0f;
			Clock::time_point lastTick{};
			std::uint64_t switchGeneration = 0;
			std::uint64_t appliedGeneration = 0;
			std::map<std::string, json> baseline;  ///< feature short name -> original saved settings
			std::map<int, std::string> variantErrors;
			std::filesystem::path resultPath;
			std::vector<Result> results;
			std::string startedAt;
			std::string cellName;
		};

		std::mutex g_mutex;
		RunState g_run;
		std::vector<Variant> g_variants;
		Config g_config;
		bool g_definitionsLoaded = false;

		std::string Timestamp(const char* format)
		{
			const auto now = std::chrono::system_clock::now();
			const std::time_t time = std::chrono::system_clock::to_time_t(now);
			std::tm local{};
			localtime_s(&local, &time);
			char buffer[64]{};
			std::strftime(buffer, sizeof(buffer), format, &local);
			return buffer;
		}

		bool ParseDefinitions(const json& root, Config& config, std::vector<Variant>& variants, std::string& error)
		{
			try {
				Config parsed{};
				parsed.warmupFrames = std::clamp(root.value("warmupFrames", parsed.warmupFrames), 10u, 600u);
				parsed.measureFrames = std::clamp(root.value("measureFrames", parsed.measureFrames), 20u, 1200u);
				parsed.repeats = std::clamp(root.value("repeats", parsed.repeats), 1u, 4u);
				parsed.countdownSeconds = std::clamp(root.value("countdownSeconds", parsed.countdownSeconds), 0.0f, 60.0f);
				std::vector<Variant> parsedVariants;
				for (const auto& entry : root.at("variants")) {
					Variant variant;
					variant.id = entry.at("id").get<std::string>();
					variant.label = entry.value("label", variant.id);
					variant.group = entry.value("group", std::string("Other"));
					variant.note = entry.value("note", std::string{});
					variant.enabled = entry.value("enabled", true);
					for (const auto& patch : entry.at("patches")) {
						if (!patch.at("settings").is_object())
							throw std::runtime_error(std::format("variant '{}' has non-object settings", variant.id));
						variant.patches.push_back({ patch.at("feature").get<std::string>(), patch.at("settings") });
					}
					if (variant.patches.empty())
						throw std::runtime_error(std::format("variant '{}' has no patches", variant.id));
					parsedVariants.push_back(std::move(variant));
				}
				config = parsed;
				variants = std::move(parsedVariants);
				return true;
			} catch (const std::exception& e) {
				error = e.what();
				return false;
			}
		}

		void EnsureDefinitions()
		{
			if (g_definitionsLoaded)
				return;
			g_definitionsLoaded = true;
			std::string error;
			ParseDefinitions(json::parse(kBuiltInDefinitions), g_config, g_variants, error);
			const auto path = Util::PathHelpers::GetDataPath() / kDefinitionsFile;
			std::error_code ec;
			if (!std::filesystem::is_regular_file(path, ec))
				return;
			try {
				std::ifstream file(path);
				const json root = json::parse(file, nullptr, true, true);
				Config config;
				std::vector<Variant> variants;
				if (ParseDefinitions(root, config, variants, error)) {
					g_config = config;
					g_variants = std::move(variants);
					logger::info("[DLSSNR][Benchmark] loaded {} variants from {}", g_variants.size(), path.string());
				} else {
					logger::warn("[DLSSNR][Benchmark] {} is invalid ({}); using built-in variants", path.string(), error);
				}
			} catch (const std::exception& e) {
				logger::warn("[DLSSNR][Benchmark] could not read {} ({}); using built-in variants", path.string(), e.what());
			}
		}

		bool IsInterrupted()
		{
			auto* state = globals::state;
			return !state || state->isLoadingMenuOpen || state->IsPausedOrMenuOpen(globals::game::ui);
		}

		struct FrameSample
		{
			std::uint32_t index = 0;
			float gpuMs = 0.0f;
			float cpuMs = 0.0f;
			float intervalMs = 0.0f;
			bool reprojected = false;
		};

		bool SampleCompositor(FrameSample& sample)
		{
			auto* compositor = RE::BSOpenVR::GetIVRCompositor();
			if (!compositor)
				return false;
			vr::Compositor_FrameTiming timing{};
			timing.m_nSize = sizeof(timing);
			if (!compositor->GetFrameTiming(&timing))
				return false;
			sample.index = timing.m_nFrameIndex;
			sample.gpuMs = timing.m_flPreSubmitGpuMs + timing.m_flPostSubmitGpuMs;
			sample.cpuMs = timing.m_flNewFrameReadyMs - timing.m_flNewPosesReadyMs;
			sample.intervalMs = timing.m_flClientFrameIntervalMs;
			sample.reprojected = timing.m_nNumFramePresents > 1 || timing.m_nNumMisPresented > 0;
			return std::isfinite(sample.gpuMs) && sample.gpuMs > 0.0f && sample.gpuMs < 1000.0f;
		}

		/** Snapshots every feature any active variant touches. Main thread. */
		void SnapshotBaseline(RunState& run)
		{
			run.baseline.clear();
			for (const int index : run.activeVariants)
				for (const auto& patch : g_variants[static_cast<std::size_t>(index)].patches) {
					if (run.baseline.contains(patch.feature))
						continue;
					if (auto* feature = Feature::FindFeatureByShortName(patch.feature)) {
						json saved;
						feature->SaveSettings(saved);
						run.baseline[patch.feature] = saved;
					}
				}
		}

		/** Restores the snapshot. Main thread only. */
		void RestoreBaseline(const std::map<std::string, json>& baseline)
		{
			SceneSettingsManager::SceneLayerGuard guard(*SceneSettingsManager::GetSingleton());
			for (const auto& [name, saved] : baseline) {
				auto* feature = Feature::FindFeatureByShortName(name);
				if (!feature || !saved.is_object())
					continue;
				try {
					std::vector<std::string> unknown;
					if (!Util::Settings::ApplyPatch(*feature, saved, unknown))
						logger::warn("[DLSSNR][Benchmark] restore of {} rejected {} keys", name, unknown.size());
				} catch (const std::exception& e) {
					logger::error("[DLSSNR][Benchmark] restore of {} failed: {}", name, e.what());
				}
			}
		}

		/** Applies one variant on top of the restored baseline. Main thread only. */
		std::string ApplyVariant(const Variant& variant)
		{
			SceneSettingsManager::SceneLayerGuard guard(*SceneSettingsManager::GetSingleton());
			for (const auto& patch : variant.patches) {
				auto* feature = Feature::FindFeatureByShortName(patch.feature);
				if (!feature || !feature->loaded)
					return std::format("{} is not loaded", patch.feature);
				try {
					std::vector<std::string> unknown;
					if (!Util::Settings::ApplyPatch(*feature, patch.settings, unknown))
						return std::format("{}: unknown setting {}", patch.feature, unknown.empty() ? std::string("?") : unknown.front());
				} catch (const std::exception& e) {
					return std::format("{}: {}", patch.feature, e.what());
				}
			}
			return {};
		}

		/** Pre-flight check without applying anything. */
		std::string ValidateVariant(const Variant& variant)
		{
			for (const auto& patch : variant.patches) {
				auto* feature = Feature::FindFeatureByShortName(patch.feature);
				if (!feature || !feature->loaded)
					return std::format("{} is not loaded", patch.feature);
				json current;
				feature->SaveSettings(current);
				if (current.is_object()) {
					std::vector<std::string> unknown;
					Util::Settings::CollectUnknownSettingKeys(patch.settings, current, "", unknown);
					if (!unknown.empty())
						return std::format("{}: unknown setting {}", patch.feature, unknown.front());
				}
			}
			return {};
		}

		void RequestSwitch(RunState& run)
		{
			const int scheduled = run.schedule[run.block];
			const std::uint64_t generation = ++run.switchGeneration;
			run.phase = Phase::Switching;
			run.warmupDone = 0;
			run.blocks[run.block] = BlockRecord{ scheduled };
			const int variantIndex = scheduled >= 0 ? run.activeVariants[static_cast<std::size_t>(scheduled)] : -1;
			auto baseline = run.baseline;
			auto* task = SKSE::GetTaskInterface();
			if (!task) {
				run.phase = Phase::Failed;
				run.message = "SKSE task interface unavailable";
				return;
			}
			task->AddTask([generation, variantIndex, scheduled, baseline = std::move(baseline)]() {
				RestoreBaseline(baseline);
				std::string error;
				if (variantIndex >= 0)
					error = ApplyVariant(g_variants[static_cast<std::size_t>(variantIndex)]);
				std::scoped_lock lock(g_mutex);
				if (g_run.switchGeneration != generation)
					return;
				if (!error.empty()) {
					g_run.variantErrors[scheduled] = error;
					logger::warn("[DLSSNR][Benchmark] variant '{}' not applied: {}", g_variants[static_cast<std::size_t>(variantIndex)].id, error);
					RestoreBaseline(g_run.baseline);
				}
				g_run.appliedGeneration = generation;
			});
		}

		json BuildReport(const RunState& run, const std::vector<Benchmark::VariantDelta>& gpu,
			const std::vector<Benchmark::VariantDelta>& cpu)
		{
			json report;
			report["tool"] = "OpenNR settings benchmark";
			report["startedAt"] = run.startedAt;
			report["finishedAt"] = Timestamp("%Y-%m-%d %H:%M:%S");
			report["cell"] = run.cellName;
			report["metric"] = "SteamVR compositor application GPU time (pre+post submit), per frame";
			report["config"] = { { "warmupFrames", g_config.warmupFrames }, { "measureFrames", g_config.measureFrames }, { "repeats", g_config.repeats } };
			json blocks = json::array();
			for (const auto& block : run.blocks) {
				blocks.push_back({ { "variant", block.variant < 0 ? std::string("baseline") : g_variants[static_cast<std::size_t>(run.activeVariants[static_cast<std::size_t>(block.variant)])].id },
					{ "frames", block.gpu.size() },
					{ "gpuMedianMs", Benchmark::Median(block.gpu) },
					{ "gpuP90Ms", Benchmark::Percentile(block.gpu, 90.0f) },
					{ "cpuMedianMs", Benchmark::Median(block.cpu) },
					{ "frameIntervalMedianMs", Benchmark::Median(block.interval) },
					{ "reprojectedFrames", block.reprojected } });
			}
			report["blocks"] = blocks;
			json results = json::array();
			for (std::size_t i = 0; i < run.activeVariants.size(); ++i) {
				const auto& variant = g_variants[static_cast<std::size_t>(run.activeVariants[i])];
				json entry{ { "id", variant.id }, { "label", variant.label }, { "group", variant.group },
					{ "patches", json::array() } };
				for (const auto& patch : variant.patches)
					entry["patches"].push_back({ { "feature", patch.feature }, { "settings", patch.settings } });
				if (auto it = run.variantErrors.find(static_cast<int>(i)); it != run.variantErrors.end())
					entry["error"] = it->second;
				entry["gpuDeltaMs"] = gpu[i].deltaMs;
				entry["gpuUncertaintyMs"] = gpu[i].uncertaintyMs;
				entry["gpuVariantMedianMs"] = gpu[i].variantMedianMs;
				entry["gpuBaselineMedianMs"] = gpu[i].baselineMedianMs;
				entry["cpuDeltaMs"] = cpu[i].deltaMs;
				entry["repeats"] = gpu[i].repeats;
				results.push_back(entry);
			}
			report["results"] = results;
			return report;
		}

		void FinishLocked(RunState& run)
		{
			std::vector<Benchmark::BlockStats> gpuBlocks, cpuBlocks;
			for (const auto& block : run.blocks) {
				gpuBlocks.push_back({ block.variant, Benchmark::Median(block.gpu), Benchmark::Percentile(block.gpu, 90.0f),
					static_cast<std::uint32_t>(block.gpu.size()) });
				cpuBlocks.push_back({ block.variant, Benchmark::Median(block.cpu), Benchmark::Percentile(block.cpu, 90.0f),
					static_cast<std::uint32_t>(block.cpu.size()) });
			}
			const auto gpu = Benchmark::ComputeDeltas(gpuBlocks, run.activeVariants.size());
			const auto cpu = Benchmark::ComputeDeltas(cpuBlocks, run.activeVariants.size());

			run.results.clear();
			for (std::size_t i = 0; i < run.activeVariants.size(); ++i) {
				const auto& variant = g_variants[static_cast<std::size_t>(run.activeVariants[i])];
				Result result{ variant.id, variant.label, variant.group };
				if (auto it = run.variantErrors.find(static_cast<int>(i)); it != run.variantErrors.end())
					result.error = it->second;
				result.gpuDeltaMs = gpu[i].deltaMs;
				result.gpuUncertaintyMs = gpu[i].uncertaintyMs;
				result.gpuVariantMs = gpu[i].variantMedianMs;
				result.gpuBaselineMs = gpu[i].baselineMedianMs;
				result.cpuDeltaMs = cpu[i].deltaMs;
				result.repeats = gpu[i].repeats;
				run.results.push_back(result);
				logger::info("[DLSSNR][Benchmark] {:<34} GPU {:+.2f} ms (+/-{:.2f}) variant {:.2f} ms baseline {:.2f} ms CPU {:+.2f} ms{}",
					variant.id, result.gpuDeltaMs, result.gpuUncertaintyMs, result.gpuVariantMs, result.gpuBaselineMs,
					result.cpuDeltaMs, result.error.empty() ? std::string{} : " [" + result.error + "]");
			}

			try {
				if (auto directory = logger::log_directory()) {
					*directory /= "OpenNR-SettingsBenchmark";
					std::filesystem::create_directories(*directory);
					run.resultPath = *directory / std::format("benchmark-{}.json", Timestamp("%Y%m%d-%H%M%S"));
					std::ofstream file(run.resultPath);
					file << BuildReport(run, gpu, cpu).dump(2);
					logger::info("[DLSSNR][Benchmark] results written to {}", run.resultPath.string());
				}
			} catch (const std::exception& e) {
				logger::warn("[DLSSNR][Benchmark] could not write results: {}", e.what());
			}

			run.phase = Phase::Finished;
			run.message = "Finished; original settings restored.";
			if (auto* task = SKSE::GetTaskInterface())
				task->AddTask([baseline = run.baseline]() { RestoreBaseline(baseline); });
		}
	}

	std::vector<Variant>& Variants()
	{
		std::scoped_lock lock(g_mutex);
		EnsureDefinitions();
		return g_variants;
	}

	Config& Configuration()
	{
		std::scoped_lock lock(g_mutex);
		EnsureDefinitions();
		return g_config;
	}

	void ReloadDefinitions()
	{
		std::scoped_lock lock(g_mutex);
		if (g_run.phase == Phase::Countdown || g_run.phase == Phase::Switching ||
			g_run.phase == Phase::Warmup || g_run.phase == Phase::Measuring)
			return;
		g_definitionsLoaded = false;
		EnsureDefinitions();
	}

	bool Start(std::string* error)
	{
		std::scoped_lock lock(g_mutex);
		EnsureDefinitions();
		auto fail = [&](std::string message) {
			if (error)
				*error = message;
			g_run.message = message;
			return false;
		};
		if (g_run.phase == Phase::Countdown || g_run.phase == Phase::Switching ||
			g_run.phase == Phase::Warmup || g_run.phase == Phase::Measuring)
			return fail("A benchmark is already running.");
		if (!globals::game::isVR || !RE::BSOpenVR::GetIVRCompositor())
			return fail("The benchmark needs SteamVR compositor timing (VR only).");

		RunState run;
		for (std::size_t i = 0; i < g_variants.size(); ++i) {
			if (!g_variants[i].enabled)
				continue;
			const auto problem = ValidateVariant(g_variants[i]);
			if (!problem.empty()) {
				logger::info("[DLSSNR][Benchmark] skipping '{}': {}", g_variants[i].id, problem);
				continue;
			}
			run.activeVariants.push_back(static_cast<int>(i));
		}
		if (run.activeVariants.empty())
			return fail("No enabled variant can run (features not loaded?).");

		run.schedule = Benchmark::BuildSchedule(run.activeVariants.size(), g_config.repeats);
		run.blocks.assign(run.schedule.size(), BlockRecord{});
		SnapshotBaseline(run);
		run.phase = Phase::Countdown;
		run.countdownRemaining = g_config.countdownSeconds;
		run.lastTick = Clock::now();
		run.startedAt = Timestamp("%Y-%m-%d %H:%M:%S");
		if (auto* player = RE::PlayerCharacter::GetSingleton())
			if (auto* cell = player->GetParentCell())
				run.cellName = cell->GetName() ? cell->GetName() : "";
		run.message = "Close the menu and stand still; measurement starts after the countdown.";
		g_run = std::move(run);
		logger::info("[DLSSNR][Benchmark] started: {} variants, {} blocks, warmup {} / measure {} frames",
			g_run.activeVariants.size(), g_run.schedule.size(), g_config.warmupFrames, g_config.measureFrames);
		return true;
	}

	void Cancel()
	{
		std::scoped_lock lock(g_mutex);
		if (g_run.phase != Phase::Countdown && g_run.phase != Phase::Switching &&
			g_run.phase != Phase::Warmup && g_run.phase != Phase::Measuring)
			return;
		++g_run.switchGeneration;  // drop any in-flight switch
		g_run.phase = Phase::Cancelled;
		g_run.message = "Cancelled; original settings restored.";
		if (auto* task = SKSE::GetTaskInterface())
			task->AddTask([baseline = g_run.baseline]() { RestoreBaseline(baseline); });
		logger::info("[DLSSNR][Benchmark] cancelled");
	}

	bool ApplyVariantPermanently(const std::string& id, std::string* error)
	{
		std::scoped_lock lock(g_mutex);
		EnsureDefinitions();
		auto fail = [&](std::string message) {
			if (error)
				*error = message;
			g_run.message = message;
			return false;
		};
		if (g_run.phase == Phase::Countdown || g_run.phase == Phase::Switching ||
			g_run.phase == Phase::Warmup || g_run.phase == Phase::Measuring)
			return fail("Finish or cancel the benchmark first.");
		const auto it = std::ranges::find_if(g_variants, [&](const Variant& variant) { return variant.id == id; });
		if (it == g_variants.end())
			return fail(std::format("Unknown variant '{}'.", id));
		auto* task = SKSE::GetTaskInterface();
		if (!task)
			return fail("SKSE task interface unavailable");
		task->AddTask([variant = *it]() {
			const auto problem = ApplyVariant(variant);
			std::scoped_lock lock(g_mutex);
			g_run.message = problem.empty() ?
			                    std::format("Applied '{}'. Use Save Settings to keep it.", variant.label) :
			                    std::format("'{}' not applied: {}", variant.label, problem);
			logger::info("[DLSSNR][Benchmark] {}", g_run.message);
		});
		return true;
	}

	bool IsRunning()
	{
		std::scoped_lock lock(g_mutex);
		return g_run.phase == Phase::Countdown || g_run.phase == Phase::Switching ||
		       g_run.phase == Phase::Warmup || g_run.phase == Phase::Measuring;
	}

	const char* PhaseName(Phase phase)
	{
		switch (phase) {
		case Phase::Idle: return "idle";
		case Phase::Countdown: return "countdown";
		case Phase::Switching: return "switching";
		case Phase::Warmup: return "warmup";
		case Phase::Measuring: return "measuring";
		case Phase::Finished: return "finished";
		case Phase::Cancelled: return "cancelled";
		case Phase::Failed: return "failed";
		}
		return "unknown";
	}

	Status GetStatus()
	{
		std::scoped_lock lock(g_mutex);
		Status status;
		status.phase = g_run.phase;
		status.message = g_run.message;
		status.block = static_cast<std::uint32_t>(g_run.block);
		status.blockCount = static_cast<std::uint32_t>(g_run.schedule.size());
		status.paused = g_run.paused;
		status.countdownRemaining = g_run.countdownRemaining;
		status.resultPath = g_run.resultPath;
		status.results = g_run.results;
		if (g_run.block < g_run.schedule.size()) {
			const int scheduled = g_run.schedule[g_run.block];
			status.currentLabel = scheduled < 0 ? std::string("Baseline (your settings)") :
			                                      g_variants[static_cast<std::size_t>(g_run.activeVariants[static_cast<std::size_t>(scheduled)])].label;
			status.framesNeeded = g_run.phase == Phase::Warmup ? g_config.warmupFrames : g_config.measureFrames;
			status.framesInBlock = g_run.phase == Phase::Warmup ? g_run.warmupDone :
			                                                       static_cast<std::uint32_t>(g_run.blocks[g_run.block].gpu.size());
		}
		return status;
	}

	json StatusJson()
	{
		const auto status = GetStatus();
		json results = json::array();
		for (const auto& result : status.results)
			results.push_back({ { "id", result.id }, { "label", result.label }, { "gpuDeltaMs", result.gpuDeltaMs },
				{ "gpuUncertaintyMs", result.gpuUncertaintyMs }, { "cpuDeltaMs", result.cpuDeltaMs },
				{ "error", result.error } });
		return json{ { "phase", PhaseName(status.phase) }, { "message", status.message }, { "block", status.block },
			{ "blockCount", status.blockCount }, { "current", status.currentLabel }, { "paused", status.paused },
			{ "resultPath", status.resultPath.string() }, { "results", results } };
	}

	void Tick()
	{
		std::scoped_lock lock(g_mutex);
		auto& run = g_run;
		if (run.phase != Phase::Countdown && run.phase != Phase::Switching &&
			run.phase != Phase::Warmup && run.phase != Phase::Measuring)
			return;

		const auto now = Clock::now();
		const float elapsed = std::chrono::duration<float>(now - run.lastTick).count();
		run.lastTick = now;
		run.paused = IsInterrupted();

		if (run.phase == Phase::Countdown) {
			if (!run.paused)
				run.countdownRemaining -= std::clamp(elapsed, 0.0f, 0.25f);
			if (run.countdownRemaining <= 0.0f) {
				run.block = 0;
				RequestSwitch(run);
			}
			return;
		}

		if (run.phase == Phase::Switching) {
			if (run.appliedGeneration == run.switchGeneration) {
				run.phase = Phase::Warmup;
				run.warmupDone = 0;
				run.haveFrameIndex = false;
			}
			return;
		}

		FrameSample sample;
		if (!SampleCompositor(sample))
			return;
		const bool newFrame = !run.haveFrameIndex || sample.index != run.lastFrameIndex;
		run.lastFrameIndex = sample.index;
		run.haveFrameIndex = true;
		if (!newFrame)
			return;

		if (run.paused) {
			// A menu or loading screen changes the workload; restart this block's settle time.
			run.phase = Phase::Warmup;
			run.warmupDone = 0;
			auto& record = run.blocks[run.block];
			record.gpu.clear();
			record.cpu.clear();
			record.interval.clear();
			record.reprojected = 0;
			return;
		}

		if (run.phase == Phase::Warmup) {
			if (++run.warmupDone >= g_config.warmupFrames)
				run.phase = Phase::Measuring;
			return;
		}

		auto& record = run.blocks[run.block];
		record.gpu.push_back(sample.gpuMs);
		if (std::isfinite(sample.cpuMs) && sample.cpuMs >= 0.0f)
			record.cpu.push_back(sample.cpuMs);
		if (std::isfinite(sample.intervalMs) && sample.intervalMs > 0.0f)
			record.interval.push_back(sample.intervalMs);
		record.reprojected += sample.reprojected ? 1u : 0u;
		if (record.gpu.size() < g_config.measureFrames)
			return;

		if (++run.block >= run.schedule.size()) {
			FinishLocked(run);
			return;
		}
		RequestSwitch(run);
	}

	void DrawPanel()
	{
		EnsureDefinitions();
		const auto status = GetStatus();
		const bool running = status.phase == Phase::Countdown || status.phase == Phase::Switching ||
		                     status.phase == Phase::Warmup || status.phase == Phase::Measuring;

		ImGui::TextWrapped("Measures real GPU cost on your scene: each change is applied live, settled, timed with the SteamVR "
						   "compositor, and bracketed by runs of your own settings. Your settings are restored afterwards and nothing is saved.");
		ImGui::TextDisabled("Stand still in a representative spot, keep the head steady, close the menu. About 2-4 minutes.");

		if (!running) {
			ImGui::BeginDisabled(running);
			std::string lastGroup;
			for (auto& variant : g_variants) {
				if (variant.group != lastGroup) {
					ImGui::SeparatorText(variant.group.c_str());
					lastGroup = variant.group;
				}
				ImGui::PushID(variant.id.c_str());
				ImGui::Checkbox(variant.label.c_str(), &variant.enabled);
				if (!variant.note.empty() && ImGui::IsItemHovered())
					ImGui::SetTooltip("%s", variant.note.c_str());
				ImGui::PopID();
			}
			int warmup = static_cast<int>(g_config.warmupFrames);
			int measure = static_cast<int>(g_config.measureFrames);
			int repeats = static_cast<int>(g_config.repeats);
			if (ImGui::SliderInt("Settle frames", &warmup, 10, 240))
				g_config.warmupFrames = static_cast<std::uint32_t>(warmup);
			if (ImGui::SliderInt("Measured frames", &measure, 30, 600))
				g_config.measureFrames = static_cast<std::uint32_t>(measure);
			if (ImGui::SliderInt("Repeats", &repeats, 1, 4))
				g_config.repeats = static_cast<std::uint32_t>(repeats);
			ImGui::EndDisabled();
			if (ImGui::Button("Start settings benchmark")) {
				std::string error;
				Start(&error);
			}
			ImGui::SameLine();
			if (ImGui::Button("Reload variant file"))
				ReloadDefinitions();
		} else {
			if (ImGui::Button("Cancel benchmark"))
				Cancel();
			if (status.phase == Phase::Countdown)
				ImGui::Text("Starting in %.0f s%s", std::max(0.0f, status.countdownRemaining), status.paused ? " (waiting for the menu to close)" : "");
			else
				ImGui::Text("Block %u / %u: %s | %s %u / %u%s", status.block + 1, status.blockCount, status.currentLabel.c_str(),
					PhaseName(status.phase), status.framesInBlock, status.framesNeeded, status.paused ? " (paused)" : "");
		}
		if (!status.message.empty())
			ImGui::TextDisabled("%s", status.message.c_str());

		if (!status.results.empty() && ImGui::BeginTable("##nr_benchmark_results", 5,
				ImGuiTableFlags_RowBg | ImGuiTableFlags_BordersInnerH | ImGuiTableFlags_SizingStretchProp)) {
			ImGui::TableSetupColumn("Change");
			ImGui::TableSetupColumn("GPU ms");
			ImGui::TableSetupColumn("+/-");
			ImGui::TableSetupColumn("CPU ms");
			ImGui::TableSetupColumn("");
			ImGui::TableHeadersRow();
			for (const auto& result : status.results) {
				ImGui::TableNextRow();
				ImGui::TableNextColumn();
				ImGui::TextUnformatted(result.label.c_str());
				if (!result.error.empty() && ImGui::IsItemHovered())
					ImGui::SetTooltip("%s", result.error.c_str());
				ImGui::TableNextColumn();
				if (!result.error.empty() || !std::isfinite(result.gpuDeltaMs))
					ImGui::TextDisabled("n/a");
				else
					ImGui::TextColored(result.gpuDeltaMs < -result.gpuUncertaintyMs ? ImVec4(0.45f, 0.9f, 0.45f, 1.0f) :
					                                                                  ImGui::GetStyleColorVec4(ImGuiCol_Text),
						"%+.2f", result.gpuDeltaMs);
				ImGui::TableNextColumn();
				ImGui::TextDisabled("%.2f", std::isfinite(result.gpuUncertaintyMs) ? result.gpuUncertaintyMs : 0.0f);
				ImGui::TableNextColumn();
				ImGui::TextDisabled("%+.2f", std::isfinite(result.cpuDeltaMs) ? result.cpuDeltaMs : 0.0f);
				ImGui::TableNextColumn();
				ImGui::BeginDisabled(running || !result.error.empty());
				ImGui::PushID(result.id.c_str());
				if (ImGui::SmallButton("Apply"))
					ApplyVariantPermanently(result.id);
				ImGui::PopID();
				ImGui::EndDisabled();
			}
			ImGui::EndTable();
			ImGui::TextDisabled("Negative = faster. Green = saving larger than the measured drift. Apply keeps a change live for a look test; Save Settings makes it permanent.");
		}
		if (!status.resultPath.empty())
			ImGui::TextDisabled("Saved: %s", status.resultPath.string().c_str());
	}
}
