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
		float intensity = 0.8f;
		float localToneStrength = 0.75f;
		float localStructureStrength = 0.9f;
		float skinStructureStrength = 0.9f;
		// The supplied runtime and the reference bridge expose three style indices.
		std::uint32_t style = 2;
		// The private NR hint is an integer selected at feature creation time. The
		// shipped bridge uses 1, so preserve that as the safe default while still
		// allowing the user to experiment with the neighboring runtime indices.
		std::uint32_t preset = 1;
		bool useAutoMask = true;
		bool uiCorrection = false;
		bool depthInverted = false;
		float motionScaleX = 1.0f;
		float motionScaleY = 1.0f;
		// 0=available guides, 1=zero guides, 2=motion only, 3=depth only.
		// This is a player-side choice implemented by the guide generator pass;
		// the DLL itself still receives valid depth and motion resources.
		std::uint32_t frameGuidance = 0;
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
			std::uint32_t inputWidth, std::uint32_t inputHeight, std::uint32_t outputWidth, std::uint32_t outputHeight,
			float motionVectorScaleX, float motionVectorScaleY, const Tuning& tuning, bool reset);
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
		[[nodiscard]] bool IsInitialized() const { return status_ == RuntimeStatus::Initialized; }
		[[nodiscard]] bool FeatureCreated(std::uint32_t slot = 0) const { return slot < 2 && featureHandles_[slot] != nullptr; }
		[[nodiscard]] const std::filesystem::path& Path() const { return path_; }

	private:
		Runtime() = default;
		void* module_ = nullptr;
		void* parameters_ = nullptr;
		void* featureHandles_[2]{};
		std::uint32_t featureInputWidth_[2]{};
		std::uint32_t featureInputHeight_[2]{};
		std::uint32_t featureOutputWidth_[2]{};
		std::uint32_t featureOutputHeight_[2]{};
		ID3D12Device* device_ = nullptr;
		RuntimeStatus status_ = RuntimeStatus::NotProbed;
		std::filesystem::path path_;
		std::string version_;
		std::string detail_;
		std::uint32_t ngxResult_ = 0;
		std::uint32_t applicationId_ = 0;
		std::uint32_t apiVersion_ = 0;
		std::uint64_t successfulFrames_ = 0;
		std::uint64_t evaluationAttempts_ = 0;
	};

	const char* ToString(RuntimeStatus status);
}
