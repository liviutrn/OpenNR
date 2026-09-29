#pragma once

#include <algorithm>
#include <array>
#include <cstdint>

namespace NeuralRendering
{
	/**
	 * @brief OpenNR 2.20 treats any NR model/input area below the full display eye as a
	 * no-go because it weakens the neural effect. Reduced model tiers, adaptive NR tiers
	 * and pre-upscale NR are therefore locked off at load time and at the runtime boundary.
	 */
	inline constexpr bool kFullResolutionNeuralRenderingOnly = true;

	/** @brief Centered NR-only coverage presets (linear per axis). 100 = the full eye. */
	inline constexpr std::array<std::uint32_t, 7> kNeuralCoveragePresets{ 100, 95, 90, 85, 80, 75, 70 };

	[[nodiscard]] inline std::uint32_t NormalizeNeuralCoverage(std::uint32_t percent)
	{
		return std::find(kNeuralCoveragePresets.begin(), kNeuralCoveragePresets.end(), percent) !=
		               kNeuralCoveragePresets.end() ?
		           percent :
		           100u;
	}

	/**
	 * @brief Feature 18 receives motion-vector scale in guide pixels (UV * guide extent).
	 * Display-space passes that add motion to color-pixel positions must convert it; the
	 * post-upscale VR route has guides at render resolution and color at display resolution.
	 */
	[[nodiscard]] inline float GuideToColorMotionScale(float guidePixelScale, std::uint32_t colorExtent,
		std::uint32_t guideExtent)
	{
		return guideExtent == 0 ? guidePixelScale :
		                          guidePixelScale * static_cast<float>(colorExtent) / static_cast<float>(guideExtent);
	}

	/** @brief One eye's centered NR-only region in local eye coordinates, plus its matching guide rect. */
	struct NeuralCoverageRect
	{
		std::uint32_t colorX = 0;
		std::uint32_t colorY = 0;
		std::uint32_t colorWidth = 0;
		std::uint32_t colorHeight = 0;
		std::uint32_t guideX = 0;
		std::uint32_t guideY = 0;
		std::uint32_t guideWidth = 0;
		std::uint32_t guideHeight = 0;

		[[nodiscard]] bool IsValid() const { return colorWidth && colorHeight && guideWidth && guideHeight; }
	};

	/**
	 * @brief Picks the guide rectangle first in whole guide pixels, then maps its edges to
	 * display pixels, so color/guide misalignment stays below half a display pixel.
	 */
	[[nodiscard]] inline NeuralCoverageRect ComputeNeuralCoverageRect(std::uint32_t eyeWidth, std::uint32_t eyeHeight,
		std::uint32_t guideWidth, std::uint32_t guideHeight, std::uint32_t coveragePercent)
	{
		NeuralCoverageRect rect{};
		if (!eyeWidth || !eyeHeight || guideWidth < 2 || guideHeight < 2)
			return rect;
		coveragePercent = NormalizeNeuralCoverage(coveragePercent);
		auto guideSpan = [&](std::uint32_t extent) {
			const auto span = static_cast<std::uint32_t>((static_cast<std::uint64_t>(extent) * coveragePercent + 50) / 100);
			// Keep the span parity equal to the extent so the rectangle is exactly centered.
			const auto centered = span + ((extent - span) & 1u);
			return std::clamp<std::uint32_t>(centered, 2u, extent);
		};
		rect.guideWidth = guideSpan(guideWidth);
		rect.guideHeight = guideSpan(guideHeight);
		rect.guideX = (guideWidth - rect.guideWidth) / 2;
		rect.guideY = (guideHeight - rect.guideHeight) / 2;
		auto mapEdge = [](std::uint32_t edge, std::uint32_t colorExtent, std::uint32_t guideExtent) {
			return static_cast<std::uint32_t>((static_cast<std::uint64_t>(edge) * colorExtent + guideExtent / 2) / guideExtent);
		};
		const auto left = mapEdge(rect.guideX, eyeWidth, guideWidth);
		const auto right = mapEdge(rect.guideX + rect.guideWidth, eyeWidth, guideWidth);
		const auto top = mapEdge(rect.guideY, eyeHeight, guideHeight);
		const auto bottom = mapEdge(rect.guideY + rect.guideHeight, eyeHeight, guideHeight);
		rect.colorX = left;
		rect.colorY = top;
		rect.colorWidth = right > left ? right - left : 0;
		rect.colorHeight = bottom > top ? bottom - top : 0;
		return rect;
	}

	/**
	 * @brief Eye-staggered N2 residual reuse: one eye receives native Feature 18 per frame
	 * while the other reuses its previous-frame residual, keeping per-frame NR cost flat.
	 */
	[[nodiscard]] inline std::uint32_t StaggeredNativeEye(std::uint64_t temporalFrameIndex)
	{
		return static_cast<std::uint32_t>(temporalFrameIndex & 1u);
	}

	/** @brief Separates a model-tier change from changes that invalidate display-space handoff history. */
	struct TemporalHistoryConfig
	{
		bool adaptive = false;
		std::uint32_t modelResolution = 100;
		std::uint32_t cadence = 0;
		float depthThreshold = 0.05f;
		float colorTolerance = 0.08f;
		std::uint32_t passes = 1;

		bool operator==(const TemporalHistoryConfig&) const = default;

		[[nodiscard]] bool PreservesHandoff(const TemporalHistoryConfig& next) const
		{
			auto sameTier = next;
			sameTier.modelResolution = modelResolution;
			return adaptive && next.adaptive && *this == sameTier;
		}
	};

	/** @brief Tracks the active/previous tier; the renderer may add its two immediate neighbors for bounded prewarm. */
	struct TierResidency
	{
		std::uint32_t current = UINT32_MAX;
		std::uint32_t previous = UINT32_MAX;

		bool Select(std::uint32_t tier, bool retainPrevious)
		{
			const bool changed = current != tier;
			if (changed) {
				previous = current;
				current = tier;
			}
			if (!retainPrevious)
				previous = UINT32_MAX;
			return changed;
		}

		[[nodiscard]] bool Contains(std::uint32_t tier) const
		{
			return tier == current || tier == previous;
		}
	};
}
