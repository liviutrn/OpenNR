#pragma once

#include <array>
#include <cstdint>
#include <filesystem>
#include <string>

struct ID3D12Device;
struct ID3D12GraphicsCommandList;
struct ID3D12Resource;

namespace NeuralRendering
{
	struct PassParameters
	{
		float intensity = 1.70f;
		float localToneStrength = 1.00f;
		float localStructureStrength = 1.70f;
		float skinStructureStrength = -1.0f;
		std::uint32_t style = 0;
		bool useAutoMask = true;
		bool uiCorrection = false;
	};

	struct Tuning
	{
		float intensity = 1.70f;
		float localToneStrength = 1.00f;
		float localStructureStrength = 1.70f;
		float skinStructureStrength = -1.0f;
		std::uint32_t style = 0;
		bool useAutoMask = true;
		bool uiCorrection = false;
		std::array<PassParameters, 3> passParameters{};
		// Post-SR continuation after a successful pre-SR pass starts at pass two.
		std::uint32_t passParameterOffset = 0;
		std::uint32_t modelResolutionPercent = 100;
		// 0 = current bounded full-resolution resolve; 1 = exact-area input plus
		// conservative matched-residual composition for reduced model resolutions.
		std::uint32_t modelResolveMode = 0;
		// 0 = single pass, 1 = 2x, 2 = 3x sequential Feature 18 evaluations.
		// The adaptive controller may reduce this count under pressure.
		std::uint32_t multiPass = 0;
		float secondPassContribution = 1.0f;
		// Reduce the centered second-pass region independently per axis in 2x mode.
		std::uint32_t secondPassCropReductionX = 0;
		std::uint32_t secondPassCropReductionY = 0;
		std::uint32_t secondPassBlendMode = 0;
		std::uint32_t secondPassMaskMode = 1;
		float secondPassFeatherWidth = 32.0f;
		float secondPassFalloffCurve = 1.0f;
		float secondPassDitherStrength = 1.0f;
		bool stereoResidualReprojection = false;
		std::uint32_t stereoResidualAnchorEye = 0;
		// Allocate up to this many pass resources when adaptive pass reduction is
		// active, so a pressure response does not recreate the cascade resources.
		std::uint32_t adaptiveMaxPassCount = 1;
		// Experimental stereo mode: 0 = disabled, 2 = alternate native Feature 18
		// anchors between eyes each host frame and reproject the other eye's saved
		// residual using accumulated game motion vectors.
		std::uint32_t temporalReuseCadence = 0;
		float temporalReuseDepthThreshold = 0.05f;
		float temporalReuseColorTolerance = 0.08f;
		// Comparison switch. Resetting after an eye's skipped frame prevents
		// native history ghosting but can create a visible cadence discontinuity.
		bool temporalReuseResetAfterSkip = false;
		// Opt-in adaptive-resolution handoff. The controller changes only the
		// native NR tier; the display/compositor cadence remains owned by VR.
		bool adaptiveResolution = false;
		// The crop route keeps its own current-frame feathering contract. Mixing
		// a previous NR image with moving crop coordinates can produce a stereo
		// ghost, so integration disables this only while adaptive crop is active.
		bool adaptiveHandoff = true;
		float adaptiveHandoffAlpha = 1.0f;
		float adaptiveDepthThreshold = 0.05f;
		// -1 prepares lower quality, +1 prepares higher quality, 0 holds prewarming.
		std::int32_t adaptivePrewarmDirection = 0;
		std::uint32_t adaptiveMemoryCeiling = 100;
		float nrContribution = 1.0f;
		float detailBoost = 1.0f;

		[[nodiscard]] Tuning ForPass(std::uint32_t passIndex) const;
	};

	inline Tuning Tuning::ForPass(std::uint32_t passIndex) const
	{
		passIndex += passParameterOffset;
		if (passIndex >= passParameters.size())
			return *this;
		Tuning result = *this;
		const auto& parameters = passParameters[passIndex];
		result.intensity = parameters.intensity;
		result.localToneStrength = parameters.localToneStrength;
		result.localStructureStrength = parameters.localStructureStrength;
		result.skinStructureStrength = parameters.skinStructureStrength;
		result.style = parameters.style;
		result.useAutoMask = parameters.useAutoMask;
		result.uiCorrection = parameters.uiCorrection;
		return result;
	}

	/**
	 * Describes the exact resource extents presented to native Feature 18.
	 *
	 * Feature 18 has separate color, depth, motion-vector, and output regions.
	 * Keeping those regions together prevents the direct carrier path from
	 * inferring one guide's extent from another (or from the output size), which
	 * is especially important after per-eye VR isolation and for low-resolution
	 * motion vectors.
	 */
	struct Feature18GuideContract
	{
		std::uint32_t colorBaseX = 0;
		std::uint32_t colorBaseY = 0;
		std::uint32_t colorWidth = 0;
		std::uint32_t colorHeight = 0;

		std::uint32_t depthBaseX = 0;
		std::uint32_t depthBaseY = 0;
		std::uint32_t depthWidth = 0;
		std::uint32_t depthHeight = 0;

		std::uint32_t motionBaseX = 0;
		std::uint32_t motionBaseY = 0;
		std::uint32_t motionWidth = 0;
		std::uint32_t motionHeight = 0;

		std::uint32_t outputBaseX = 0;
		std::uint32_t outputBaseY = 0;
		std::uint32_t outputWidth = 0;
		std::uint32_t outputHeight = 0;

		// Optional stable creation extents. Adaptive crop changes the valid
		// evaluation subrect every few frames, but a native Feature 18 handle
		// must not be recreated for each of those valid-region changes. Zero
		// means use the corresponding current valid extent.
		std::uint32_t creationInputWidth = 0;
		std::uint32_t creationInputHeight = 0;
		std::uint32_t creationOutputWidth = 0;
		std::uint32_t creationOutputHeight = 0;

		float motionVectorScaleX = 1.0f;
		float motionVectorScaleY = 1.0f;
		bool motionVectorsLowResolution = false;

		[[nodiscard]] std::uint32_t FeatureInputWidth() const
		{
			return creationInputWidth != 0 ? creationInputWidth : colorWidth;
		}
		[[nodiscard]] std::uint32_t FeatureInputHeight() const
		{
			return creationInputHeight != 0 ? creationInputHeight : colorHeight;
		}
		[[nodiscard]] std::uint32_t FeatureOutputWidth() const
		{
			return creationOutputWidth != 0 ? creationOutputWidth : outputWidth;
		}
		[[nodiscard]] std::uint32_t FeatureOutputHeight() const
		{
			return creationOutputHeight != 0 ? creationOutputHeight : outputHeight;
		}

		[[nodiscard]] bool IsValid() const
		{
			return colorWidth != 0 && colorHeight != 0 &&
				depthWidth != 0 && depthHeight != 0 &&
				motionWidth != 0 && motionHeight != 0 &&
				outputWidth != 0 && outputHeight != 0;
		}
	};

	enum class RuntimeStatus
	{
		NotProbed, NotFound, VersionUnavailable, UnsupportedVersion, LoadFailed, MissingExport,
		Ready, InitializationFailed, CoreUnavailable, ParameterAllocationFailed, Initialized,
	};

	class Runtime
	{
	public:
		static Runtime& Instance();
		~Runtime();
		Runtime(const Runtime&) = delete;
		Runtime& operator=(const Runtime&) = delete;

		bool Probe(const std::filesystem::path& explicitPath = {});
		bool Initialize(ID3D12Device* device, const std::filesystem::path& dataPath = {});
		bool Execute(ID3D12GraphicsCommandList* commandList, std::uint32_t slot,
			ID3D12Resource* color, ID3D12Resource* depth, ID3D12Resource* motionVectors, ID3D12Resource* output,
			const Feature18GuideContract& guide, const Tuning& tuning, bool reset);
		/** @brief Creates the native handle without evaluating it, used to hide adjacent-tier transitions. */
		bool PrewarmFeature(ID3D12GraphicsCommandList* commandList, std::uint32_t slot,
			const Feature18GuideContract& guide);
		[[nodiscard]] bool HasFeature(std::uint32_t slot) const;
		void ResetFeature(std::uint32_t slot);
		/** @brief Releases the native handles owned by one persistent renderer stage. */
		void ResetFeatureRange(std::uint32_t firstSlot, std::uint32_t slotCount);
		/** @brief Detects a live feature that must be retired after the GPU completes its last use. */
		bool NeedsRecreation(std::uint32_t slot, std::uint32_t width, std::uint32_t height, bool lowResolutionMotion) const;
		/** @brief Same check with separate native input and output creation extents. */
		bool NeedsRecreation(std::uint32_t slot, std::uint32_t inputWidth, std::uint32_t inputHeight,
			std::uint32_t outputWidth, std::uint32_t outputHeight, bool lowResolutionMotion) const;
		void ResetFeatures();
		void Shutdown();

		[[nodiscard]] RuntimeStatus Status() const { return status_; }
		[[nodiscard]] const std::string& Version() const { return version_; }
		[[nodiscard]] const std::string& Detail() const { return detail_; }
		[[nodiscard]] std::uint32_t NgxResult() const { return ngxResult_; }
		[[nodiscard]] std::uint32_t ApplicationId() const { return applicationId_; }
		[[nodiscard]] std::uint32_t ApiVersion() const { return apiVersion_; }
		[[nodiscard]] std::uint64_t SuccessfulFrames() const { return successfulFrames_; }

	private:
		// Two renderer stages x two eyes x nine fixed
		// resolution tiers x three cascade stages.
		static constexpr std::uint32_t kFeatureSlotCount = 108;
		Runtime() = default;
		bool EnsureFeature(ID3D12GraphicsCommandList* commandList, std::uint32_t slot,
			const Feature18GuideContract& guide, bool* created = nullptr);
		void* module_ = nullptr;
		void* parameters_ = nullptr;
		void* featureHandles_[kFeatureSlotCount]{};
		std::uint32_t featureInputWidth_[kFeatureSlotCount]{};
		std::uint32_t featureInputHeight_[kFeatureSlotCount]{};
		std::uint32_t featureOutputWidth_[kFeatureSlotCount]{};
		std::uint32_t featureOutputHeight_[kFeatureSlotCount]{};
		bool featureMotionVectorsLowResolution_[kFeatureSlotCount]{};
		ID3D12Device* device_ = nullptr;
		RuntimeStatus status_ = RuntimeStatus::NotProbed;
		std::filesystem::path path_;
		std::string version_;
		std::string detail_;
		std::uint32_t ngxResult_ = 0;
		std::uint32_t applicationId_ = 0;
		std::uint32_t apiVersion_ = 0;
		std::uint64_t successfulFrames_ = 0;
	};

	const char* ToString(RuntimeStatus status);
}
