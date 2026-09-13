#pragma once

#include <cstdint>
#include <filesystem>
#include <string>

struct ID3D12Device;
struct ID3D12GraphicsCommandList;
struct ID3D12Resource;

namespace NeuralRendering
{
	struct Tuning
	{
		float intensity = 1.70f;
		float localToneStrength = 1.00f;
		float localStructureStrength = 1.70f;
		float skinStructureStrength = -1.0f;
		std::uint32_t style = 0;
		bool useAutoMask = true;
		bool uiCorrection = false;
		std::uint32_t modelResolutionPercent = 100;
		// 0 = current bounded full-resolution resolve; 1 = exact-area input plus
		// conservative matched-residual composition for reduced model resolutions.
		std::uint32_t modelResolveMode = 0;
		// Experimental screenshot/benchmark cascade: 0 = single pass, 1 = 2x,
		// 2 = 3x sequential Feature 18 evaluations. Each stage has separate
		// resources/history; the renderer gates this away from cropped VR paths.
		std::uint32_t multiPass = 0;
		// Experimental temporal reuse: 0 = disabled, otherwise run a full
		// Feature 18 pass every Nth frame and reproject the saved residual on the
		// intervening frames. The renderer only enables this for native-size,
		// single-pass, full-eye layouts with exact game motion vectors.
		std::uint32_t temporalReuseCadence = 0;
		float temporalReuseDepthThreshold = 0.05f;
		float temporalReuseColorTolerance = 0.08f;
		// Opt-in adaptive-resolution handoff. The controller changes only the
		// native NR tier; the display/compositor cadence remains owned by VR.
		bool adaptiveResolution = false;
		float adaptiveHandoffAlpha = 1.0f;
		float adaptiveDepthThreshold = 0.05f;
	};

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

		float motionVectorScaleX = 1.0f;
		float motionVectorScaleY = 1.0f;
		bool motionVectorsLowResolution = false;

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
		void ResetFeature(std::uint32_t slot);
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
		// Two eyes x seven resolution tiers x three cascade stages. The adaptive
		// controller keeps each tier's NGX feature handle isolated so a handoff
		// never reuses a handle configured for a different model extent.
		static constexpr std::uint32_t kFeatureSlotCount = 42;
		Runtime() = default;
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
