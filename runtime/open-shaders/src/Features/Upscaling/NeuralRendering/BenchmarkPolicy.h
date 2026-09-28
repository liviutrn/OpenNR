#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

/**
 * @brief Pure scheduling and statistics for the in-headset settings benchmark.
 *
 * The benchmark brackets every variant with baseline blocks (B V0 B V1 B ...) so
 * slow drift (thermal clocks, head pose, scene streaming) is measured instead of
 * silently attributed to a setting. Later repeats run the variants in reverse
 * order so drift that correlates with time cancels out across repeats.
 */
namespace NeuralRendering::Benchmark
{
	inline constexpr int kBaselineBlock = -1;

	/** @brief Block order for `variantCount` variants and `repeats` passes. */
	[[nodiscard]] inline std::vector<int> BuildSchedule(std::size_t variantCount, std::uint32_t repeats)
	{
		std::vector<int> schedule;
		if (variantCount == 0 || repeats == 0)
			return schedule;
		schedule.push_back(kBaselineBlock);
		for (std::uint32_t pass = 0; pass < repeats; ++pass) {
			for (std::size_t i = 0; i < variantCount; ++i) {
				const std::size_t index = (pass % 2 == 0) ? i : variantCount - 1 - i;
				schedule.push_back(static_cast<int>(index));
				schedule.push_back(kBaselineBlock);
			}
		}
		return schedule;
	}

	/** @brief Nearest-rank percentile of finite samples; NaN when there are none. */
	[[nodiscard]] inline float Percentile(std::vector<float> samples, float percentile)
	{
		std::erase_if(samples, [](float value) { return !std::isfinite(value); });
		if (samples.empty())
			return std::numeric_limits<float>::quiet_NaN();
		std::sort(samples.begin(), samples.end());
		const float clamped = std::clamp(percentile, 0.0f, 100.0f);
		const auto rank = static_cast<std::size_t>(std::ceil(clamped / 100.0f * static_cast<float>(samples.size())));
		return samples[std::clamp<std::size_t>(rank, 1, samples.size()) - 1];
	}

	[[nodiscard]] inline float Median(const std::vector<float>& samples)
	{
		return Percentile(samples, 50.0f);
	}

	struct BlockStats
	{
		int variant = kBaselineBlock;
		float median = std::numeric_limits<float>::quiet_NaN();
		float p90 = std::numeric_limits<float>::quiet_NaN();
		std::uint32_t samples = 0;
	};

	struct VariantDelta
	{
		int variant = 0;
		/** Mean over repeats of (variant median - mean of the bracketing baseline medians). */
		float deltaMs = std::numeric_limits<float>::quiet_NaN();
		float variantMedianMs = std::numeric_limits<float>::quiet_NaN();
		float baselineMedianMs = std::numeric_limits<float>::quiet_NaN();
		/**
		 * Uncertainty: the largest disagreement between the two bracketing baselines
		 * (drift across the block) or between repeats, whichever is larger.
		 */
		float uncertaintyMs = std::numeric_limits<float>::quiet_NaN();
		std::uint32_t repeats = 0;
	};

	/**
	 * @brief Turns a completed block sequence (same order as BuildSchedule) into
	 * per-variant deltas. Blocks without samples are ignored, and a variant block
	 * without a valid baseline on either side produces no delta.
	 */
	[[nodiscard]] inline std::vector<VariantDelta> ComputeDeltas(const std::vector<BlockStats>& blocks, std::size_t variantCount)
	{
		struct Accumulator
		{
			std::vector<float> deltas;
			std::vector<float> variantMedians;
			std::vector<float> baselineMedians;
			float drift = 0.0f;
		};
		std::vector<Accumulator> accumulators(variantCount);
		auto validBaseline = [&](std::size_t index) {
			return blocks[index].variant == kBaselineBlock && blocks[index].samples > 0 && std::isfinite(blocks[index].median);
		};
		for (std::size_t i = 0; i < blocks.size(); ++i) {
			const auto& block = blocks[i];
			if (block.variant < 0 || static_cast<std::size_t>(block.variant) >= variantCount ||
				block.samples == 0 || !std::isfinite(block.median))
				continue;
			float before = std::numeric_limits<float>::quiet_NaN();
			float after = std::numeric_limits<float>::quiet_NaN();
			for (std::size_t j = i; j-- > 0;)
				if (validBaseline(j)) {
					before = blocks[j].median;
					break;
				}
			for (std::size_t j = i + 1; j < blocks.size(); ++j)
				if (validBaseline(j)) {
					after = blocks[j].median;
					break;
				}
			float reference = std::numeric_limits<float>::quiet_NaN();
			float drift = 0.0f;
			if (std::isfinite(before) && std::isfinite(after)) {
				reference = 0.5f * (before + after);
				drift = std::abs(after - before);
			} else if (std::isfinite(before)) {
				reference = before;
			} else if (std::isfinite(after)) {
				reference = after;
			}
			if (!std::isfinite(reference))
				continue;
			auto& accumulator = accumulators[static_cast<std::size_t>(block.variant)];
			accumulator.deltas.push_back(block.median - reference);
			accumulator.variantMedians.push_back(block.median);
			accumulator.baselineMedians.push_back(reference);
			accumulator.drift = std::max(accumulator.drift, drift);
		}

		std::vector<VariantDelta> results;
		results.reserve(variantCount);
		for (std::size_t v = 0; v < variantCount; ++v) {
			const auto& accumulator = accumulators[v];
			VariantDelta result{};
			result.variant = static_cast<int>(v);
			result.repeats = static_cast<std::uint32_t>(accumulator.deltas.size());
			if (!accumulator.deltas.empty()) {
				float sum = 0.0f, variantSum = 0.0f, baselineSum = 0.0f;
				for (std::size_t k = 0; k < accumulator.deltas.size(); ++k) {
					sum += accumulator.deltas[k];
					variantSum += accumulator.variantMedians[k];
					baselineSum += accumulator.baselineMedians[k];
				}
				const float count = static_cast<float>(accumulator.deltas.size());
				result.deltaMs = sum / count;
				result.variantMedianMs = variantSum / count;
				result.baselineMedianMs = baselineSum / count;
				const auto [lowest, highest] = std::minmax_element(accumulator.deltas.begin(), accumulator.deltas.end());
				result.uncertaintyMs = std::max(accumulator.drift, *highest - *lowest);
			}
			results.push_back(result);
		}
		return results;
	}
}
