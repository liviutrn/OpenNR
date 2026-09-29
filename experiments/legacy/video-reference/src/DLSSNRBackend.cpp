#include "DLSSNRBackend.h"

#include "Log.h"

#include <Windows.h>
#include <Psapi.h>
#include <d3d12.h>
#include <nvsdk_ngx.h>

#include <array>
#include <cstring>
#include <iomanip>
#include <sstream>
#include <vector>

#include <nvsdk_ngx_helpers.h>

namespace NeuralRendering
{
	namespace
	{
		constexpr wchar_t kRuntimeName[] = L"nvngx_dlssnr.dll";
		constexpr auto kFeatureDlssNr = static_cast<NVSDK_NGX_Feature>(18);
		constexpr std::array<const char*, 5> kRequiredExports{
			"NVSDK_NGX_D3D12_Init_Ext",
			"NVSDK_NGX_D3D12_CreateFeature",
			"NVSDK_NGX_D3D12_EvaluateFeature",
			"NVSDK_NGX_D3D12_ReleaseFeature",
			"NVSDK_NGX_D3D12_Shutdown1",
		};

		using GetUnsignedValue = unsigned int(NVSDK_CONV*)();
		using InitD3D12 = NVSDK_NGX_Result(NVSDK_CONV*)(unsigned long long, const wchar_t*, ID3D12Device*, NVSDK_NGX_Version, const NVSDK_NGX_Parameter*);
		using ShutdownD3D12 = NVSDK_NGX_Result(NVSDK_CONV*)(ID3D12Device*);
		using AllocateParameters = NVSDK_NGX_Result(NVSDK_CONV*)(NVSDK_NGX_Parameter**);
		using DestroyParameters = NVSDK_NGX_Result(NVSDK_CONV*)(NVSDK_NGX_Parameter*);
		using CreateFeature = NVSDK_NGX_Result(NVSDK_CONV*)(ID3D12GraphicsCommandList*, NVSDK_NGX_Feature, NVSDK_NGX_Parameter*, NVSDK_NGX_Handle**);
		using EvaluateFeature = NVSDK_NGX_Result(NVSDK_CONV*)(ID3D12GraphicsCommandList*, const NVSDK_NGX_Handle*, const NVSDK_NGX_Parameter*, PFN_NVSDK_NGX_ProgressCallback);
		using ReleaseFeature = NVSDK_NGX_Result(NVSDK_CONV*)(NVSDK_NGX_Handle*);
		using GetModuleFileNameWFunction = DWORD(WINAPI*)(HMODULE, LPWSTR, DWORD);

		// The experimental DLSSNR runtime is handed the driver-created NGX
		// parameter wrapper. Its stable vtable slot order differs from the order
		// declared in recent public SDK headers, as documented by the ComfyUI
		// reference bridge. Calling the wrapper through the public C++ overloads
		// therefore writes the wrong value type and produces InvalidParameter at
		// EvaluateFeature. Keep this adapter local to the experimental path.
		template <std::size_t Slot, class T>
		void ParamSetRaw(NVSDK_NGX_Parameter* parameters, const char* name, T value)
		{
			using Function = void(NVSDK_CONV*)(NVSDK_NGX_Parameter*, const char*, T);
			auto table = *reinterpret_cast<void***>(parameters);
			reinterpret_cast<Function>(table[Slot])(parameters, name, value);
		}

		void ParamSet(NVSDK_NGX_Parameter* parameters, const char* name, void* value)
		{
			ParamSetRaw<0>(parameters, name, value);
		}
		void ParamSet(NVSDK_NGX_Parameter* parameters, const char* name, ID3D12Resource* value)
		{
			ParamSetRaw<1>(parameters, name, value);
		}
		void ParamSet(NVSDK_NGX_Parameter* parameters, const char* name, ID3D11Resource* value)
		{
			ParamSetRaw<2>(parameters, name, value);
		}
		void ParamSet(NVSDK_NGX_Parameter* parameters, const char* name, int value)
		{
			ParamSetRaw<3>(parameters, name, value);
		}
		void ParamSet(NVSDK_NGX_Parameter* parameters, const char* name, unsigned int value)
		{
			ParamSetRaw<4>(parameters, name, value);
		}
		void ParamSet(NVSDK_NGX_Parameter* parameters, const char* name, double value)
		{
			ParamSetRaw<5>(parameters, name, value);
		}
		void ParamSet(NVSDK_NGX_Parameter* parameters, const char* name, float value)
		{
			ParamSetRaw<6>(parameters, name, value);
		}
		void ParamSet(NVSDK_NGX_Parameter* parameters, const char* name, unsigned long long value)
		{
			ParamSetRaw<7>(parameters, name, value);
		}

		NVSDK_NGX_Result NVSDK_CONV ScalingRatioCallback(NVSDK_NGX_Parameter* parameters)
		{
			if (!parameters)
				return NVSDK_NGX_Result_FAIL_InvalidParameter;
			ParamSet(parameters, "DLSSNR.ScalingRatio", 1.0f);
			return NVSDK_NGX_Result_Success;
		}

		GetModuleFileNameWFunction g_originalGetModuleFileNameW = nullptr;
		HMODULE g_callerModule = nullptr;
		std::wstring g_spoofedRuntimePath;
		std::uint32_t g_proxyHits = 0;

		std::string Hex(std::uint32_t value)
		{
			std::ostringstream stream;
			stream << "0x" << std::uppercase << std::hex << std::setw(8) << std::setfill('0') << value;
			return stream.str();
		}

		std::string ReadFileVersion(const std::filesystem::path& path)
		{
			DWORD ignored = 0;
			const DWORD bytes = GetFileVersionInfoSizeW(path.c_str(), &ignored);
			if (!bytes)
				return {};
			std::vector<std::uint8_t> buffer(bytes);
			if (!GetFileVersionInfoW(path.c_str(), 0, bytes, buffer.data()))
				return {};
			VS_FIXEDFILEINFO* info = nullptr;
			UINT infoBytes = 0;
			if (!VerQueryValueW(buffer.data(), L"\\", reinterpret_cast<void**>(&info), &infoBytes) ||
				!info || infoBytes < sizeof(VS_FIXEDFILEINFO))
				return {};
			std::ostringstream version;
			version << HIWORD(info->dwFileVersionMS) << '.' << LOWORD(info->dwFileVersionMS)
				<< '.' << HIWORD(info->dwFileVersionLS) << '.' << LOWORD(info->dwFileVersionLS);
			return version.str();
		}

		HMODULE FindNgxCoreModule()
		{
			std::array<HMODULE, 1024> modules{};
			DWORD bytesNeeded = 0;
			if (!K32EnumProcessModules(GetCurrentProcess(), modules.data(), static_cast<DWORD>(sizeof(modules)), &bytesNeeded))
				return nullptr;
			const std::size_t count = std::min<std::size_t>(modules.size(), bytesNeeded / sizeof(HMODULE));
			for (std::size_t index = 0; index < count; ++index) {
				if (GetProcAddress(modules[index], "NVSDK_NGX_D3D12_AllocateParameters") &&
					GetProcAddress(modules[index], "NVSDK_NGX_D3D12_DestroyParameters"))
					return modules[index];
			}
			return nullptr;
		}

		DWORD WINAPI SignedRuntimeGetModuleFileNameW(HMODULE module, LPWSTR filename, DWORD size)
		{
			if (module == g_callerModule && filename && size && !g_spoofedRuntimePath.empty()) {
				++g_proxyHits;
				const DWORD length = static_cast<DWORD>(g_spoofedRuntimePath.size());
				const DWORD copyLength = std::min(length, size - 1);
				std::memcpy(filename, g_spoofedRuntimePath.data(), copyLength * sizeof(wchar_t));
				filename[copyLength] = L'\0';
				return copyLength < length ? size : length;
			}
			return g_originalGetModuleFileNameW ? g_originalGetModuleFileNameW(module, filename, size) : 0;
		}

		class SignedRuntimePathScope
		{
		public:
			SignedRuntimePathScope(HMODULE runtime, const std::filesystem::path& ngxPath)
			{
				if (!runtime)
					return;
				GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
					reinterpret_cast<LPCWSTR>(&SignedRuntimeGetModuleFileNameW), &g_callerModule);
				g_spoofedRuntimePath = ngxPath.wstring();
				g_proxyHits = 0;

				auto* base = reinterpret_cast<std::byte*>(runtime);
				auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
				if (dos->e_magic != IMAGE_DOS_SIGNATURE)
					return;
				auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
				if (nt->Signature != IMAGE_NT_SIGNATURE)
					return;
				const auto& imports = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
				if (!imports.VirtualAddress)
					return;

				auto* descriptor = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + imports.VirtualAddress);
				for (; descriptor->Name; ++descriptor) {
					if (!descriptor->OriginalFirstThunk)
						continue;
					auto* names = reinterpret_cast<IMAGE_THUNK_DATA*>(base + descriptor->OriginalFirstThunk);
					auto* functions = reinterpret_cast<IMAGE_THUNK_DATA*>(base + descriptor->FirstThunk);
					for (; names->u1.AddressOfData; ++names, ++functions) {
						if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))
							continue;
						auto* import = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(base + names->u1.AddressOfData);
						if (std::strcmp(reinterpret_cast<const char*>(import->Name), "GetModuleFileNameW"))
							continue;
						slot_ = reinterpret_cast<void**>(&functions->u1.Function);
						g_originalGetModuleFileNameW = reinterpret_cast<GetModuleFileNameWFunction>(*slot_);
						DWORD oldProtection = 0;
						if (VirtualProtect(slot_, sizeof(*slot_), PAGE_READWRITE, &oldProtection)) {
							*slot_ = reinterpret_cast<void*>(&SignedRuntimeGetModuleFileNameW);
							DWORD ignored = 0;
							VirtualProtect(slot_, sizeof(*slot_), oldProtection, &ignored);
							FlushInstructionCache(GetCurrentProcess(), slot_, sizeof(*slot_));
							installed_ = true;
						}
						return;
					}
				}
			}

			~SignedRuntimePathScope()
			{
				if (installed_ && slot_) {
					DWORD oldProtection = 0;
					if (VirtualProtect(slot_, sizeof(*slot_), PAGE_READWRITE, &oldProtection)) {
						*slot_ = reinterpret_cast<void*>(g_originalGetModuleFileNameW);
						DWORD ignored = 0;
						VirtualProtect(slot_, sizeof(*slot_), oldProtection, &ignored);
						FlushInstructionCache(GetCurrentProcess(), slot_, sizeof(*slot_));
					}
				}
				g_spoofedRuntimePath.clear();
				g_callerModule = nullptr;
				g_originalGetModuleFileNameW = nullptr;
			}

			[[nodiscard]] bool IsInstalled() const { return installed_; }
			[[nodiscard]] std::uint32_t Hits() const { return g_proxyHits; }

		private:
			void** slot_ = nullptr;
			bool installed_ = false;
		};

		std::filesystem::path ResolveRuntimePath(const std::filesystem::path& explicitPath)
		{
			if (!explicitPath.empty())
				return std::filesystem::is_directory(explicitPath) ? explicitPath / kRuntimeName : explicitPath;
			wchar_t executable[MAX_PATH]{};
			GetModuleFileNameW(nullptr, executable, static_cast<DWORD>(std::size(executable)));
			const auto dataPath = std::filesystem::path(executable).parent_path();
			const std::array candidates{
				dataPath / L"runtime/dlssnr" / kRuntimeName,
				dataPath / L"dlssnr" / kRuntimeName,
				dataPath / L"runtime" / kRuntimeName,
				dataPath / L"nvngx_dlssnr.dll",
			};
			for (const auto& candidate : candidates) {
				std::error_code error;
				if (std::filesystem::is_regular_file(candidate, error))
					return candidate;
			}
			return {};
		}
	}

	Runtime& Runtime::Instance()
	{
		static Runtime instance;
		return instance;
	}

	Runtime::~Runtime() { Shutdown(); }

	bool Runtime::Probe(const std::filesystem::path& explicitPath)
	{
		Shutdown();
		path_ = ResolveRuntimePath(explicitPath);
		if (path_.empty()) {
			status_ = RuntimeStatus::NotFound;
			detail_ = "nvngx_dlssnr.dll was not found";
			return false;
		}
		version_ = ReadFileVersion(path_);
		if (version_.empty())
			version_ = "unknown";
		module_ = LoadLibraryExW(path_.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
		if (!module_) {
			status_ = RuntimeStatus::LoadFailed;
			detail_ = "LoadLibraryExW failed with error " + std::to_string(GetLastError());
			return false;
		}
		for (const char* exportName : kRequiredExports) {
			if (!GetProcAddress(static_cast<HMODULE>(module_), exportName)) {
				status_ = RuntimeStatus::MissingExport;
				detail_ = std::string("missing export ") + exportName;
				FreeLibrary(static_cast<HMODULE>(module_));
				module_ = nullptr;
				return false;
			}
		}
		auto getAppId = reinterpret_cast<GetUnsignedValue>(GetProcAddress(static_cast<HMODULE>(module_), "NVSDK_NGX_GetApplicationId"));
		auto getApi = reinterpret_cast<GetUnsignedValue>(GetProcAddress(static_cast<HMODULE>(module_), "NVSDK_NGX_GetAPIVersion"));
		if (!getAppId || !getApi) {
			status_ = RuntimeStatus::MissingExport;
			detail_ = "signed runtime identity exports are missing";
			FreeLibrary(static_cast<HMODULE>(module_));
			module_ = nullptr;
			return false;
		}
		applicationId_ = getAppId();
		apiVersion_ = getApi();
		status_ = RuntimeStatus::Ready;
		return true;
	}

	bool Runtime::Initialize(ID3D12Device* device, const std::filesystem::path& dataPath)
	{
		if (!device)
			return false;
		if (status_ == RuntimeStatus::Initialized && device_ != device)
			Shutdown();
		if (!module_ && !Probe())
			return false;
		if (status_ == RuntimeStatus::Initialized && device_ == device)
			return true;

		auto initialize = reinterpret_cast<InitD3D12>(GetProcAddress(static_cast<HMODULE>(module_), "NVSDK_NGX_D3D12_Init_Ext"));
		std::filesystem::path writablePath = dataPath;
		if (writablePath.empty()) {
			wchar_t tempPath[MAX_PATH]{};
			GetTempPathW(MAX_PATH, tempPath);
			writablePath = std::filesystem::path(tempPath) / L"OpenShaders-NGX";
		}
		std::error_code error;
		std::filesystem::create_directories(writablePath, error);
		SignedRuntimePathScope scope(static_cast<HMODULE>(module_), path_.parent_path() / L"nvngx.dll");
		if (!scope.IsInstalled()) {
			status_ = RuntimeStatus::InitializationFailed;
			detail_ = "failed to install signed-runtime path proxy";
			return false;
		}
		ngxResult_ = static_cast<std::uint32_t>(initialize(applicationId_, writablePath.c_str(), device,
			static_cast<NVSDK_NGX_Version>(apiVersion_), nullptr));
		if (ngxResult_ != NVSDK_NGX_Result_Success) {
			status_ = RuntimeStatus::InitializationFailed;
			detail_ = "NGX init failed " + Hex(ngxResult_) + ", proxyHits=" + std::to_string(scope.Hits());
			return false;
		}
		device_ = device;
		device_->AddRef();

		HMODULE core = FindNgxCoreModule();
		if (!core) {
			status_ = RuntimeStatus::CoreUnavailable;
			detail_ = "NGX parameter API module was not found";
			Shutdown();
			status_ = RuntimeStatus::CoreUnavailable;
			detail_ = "NGX parameter API module was not found";
			return false;
		}
		auto allocate = reinterpret_cast<AllocateParameters>(GetProcAddress(core, "NVSDK_NGX_D3D12_AllocateParameters"));
		NVSDK_NGX_Parameter* parameters = nullptr;
		ngxResult_ = static_cast<std::uint32_t>(allocate(&parameters));
		if (ngxResult_ != NVSDK_NGX_Result_Success || !parameters) {
			const auto allocationResult = ngxResult_;
			Shutdown();
			status_ = RuntimeStatus::ParameterAllocationFailed;
			ngxResult_ = allocationResult;
			detail_ = "NGX parameter allocation failed " + Hex(allocationResult);
			return false;
		}
		parameters_ = parameters;
		status_ = RuntimeStatus::Initialized;
		return true;
	}

	bool Runtime::Execute(ID3D12GraphicsCommandList* commandList, std::uint32_t slot,
		ID3D12Resource* color, ID3D12Resource* depth, ID3D12Resource* motionVectors, ID3D12Resource* output,
		std::uint32_t inputWidth, std::uint32_t inputHeight, std::uint32_t outputWidth, std::uint32_t outputHeight,
		float motionVectorScaleX, float motionVectorScaleY, const Tuning& tuning, bool reset)
	{
		if (status_ != RuntimeStatus::Initialized || !commandList || slot >= 2 || !color || !depth || !motionVectors || !output)
			return false;
		auto* parameters = static_cast<NVSDK_NGX_Parameter*>(parameters_);
		auto create = reinterpret_cast<CreateFeature>(GetProcAddress(static_cast<HMODULE>(module_), "NVSDK_NGX_D3D12_CreateFeature"));
		auto evaluate = reinterpret_cast<EvaluateFeature>(GetProcAddress(static_cast<HMODULE>(module_), "NVSDK_NGX_D3D12_EvaluateFeature"));
		auto release = reinterpret_cast<ReleaseFeature>(GetProcAddress(static_cast<HMODULE>(module_), "NVSDK_NGX_D3D12_ReleaseFeature"));
		SignedRuntimePathScope scope(static_cast<HMODULE>(module_), path_.parent_path() / L"nvngx.dll");
		if (!scope.IsInstalled())
			return false;

		const bool dimensionsChanged = featureInputWidth_[slot] != inputWidth || featureInputHeight_[slot] != inputHeight ||
			featureOutputWidth_[slot] != outputWidth || featureOutputHeight_[slot] != outputHeight;
		if (featureHandles_[slot] && dimensionsChanged) {
			release(static_cast<NVSDK_NGX_Handle*>(featureHandles_[slot]));
			featureHandles_[slot] = nullptr;
		}

		if (!featureHandles_[slot]) {
			LOG("[DLSSNR] Feature 18 create begin slot=" << slot << " input=" << inputWidth << "x" << inputHeight
				<< " output=" << outputWidth << "x" << outputHeight);
			ParamSet(parameters, "Width", outputWidth);
			ParamSet(parameters, "Height", outputHeight);
			ParamSet(parameters, "OutWidth", outputWidth);
			ParamSet(parameters, "OutHeight", outputHeight);
			ParamSet(parameters, "DLSSNR.Width", outputWidth);
			ParamSet(parameters, "DLSSNR.Height", outputHeight);
			ParamSet(parameters, "DLSSNR.InputWidth", inputWidth);
			ParamSet(parameters, "DLSSNR.InputHeight", inputHeight);
			ParamSet(parameters, "DLSSNR.OutputWidth", outputWidth);
			ParamSet(parameters, "DLSSNR.OutputHeight", outputHeight);
			ParamSet(parameters, "DLSSNR.Output.Width", outputWidth);
			ParamSet(parameters, "DLSSNR.Output.Height", outputHeight);
			ParamSet(parameters, "DLSSNR.Scale", static_cast<float>(outputWidth) / inputWidth);
			ParamSet(parameters, "DLSSNR.Upscaling", 1u);
			ParamSet(parameters, "DLSSNR.ScalingRatio", static_cast<float>(outputWidth) / inputWidth);
			ParamSet(parameters, "DLSSNRComputeScalingRatioCallback",
				reinterpret_cast<void*>(&ScalingRatioCallback));
			ParamSet(parameters, "DLSSNR.Hint.Render.Preset",
				static_cast<int>(std::clamp(tuning.preset, 0u, 3u)));
			ParamSet(parameters, NVSDK_NGX_Parameter_PerfQualityValue,
				static_cast<int>(NVSDK_NGX_PerfQuality_Value_Balanced));
			ParamSet(parameters, NVSDK_NGX_Parameter_CreationNodeMask, 1u);
			ParamSet(parameters, NVSDK_NGX_Parameter_VisibilityNodeMask, 1u);
			NVSDK_NGX_Handle* handle = nullptr;
			ngxResult_ = static_cast<std::uint32_t>(create(commandList, kFeatureDlssNr, parameters, &handle));
			if (ngxResult_ != NVSDK_NGX_Result_Success || !handle) {
				detail_ = "Feature 18 create failed slot=" + std::to_string(slot) +
					" result=" + Hex(ngxResult_) + " proxyHits=" + std::to_string(scope.Hits());
				return false;
			}
			featureHandles_[slot] = handle;
			featureInputWidth_[slot] = inputWidth;
			featureInputHeight_[slot] = inputHeight;
			featureOutputWidth_[slot] = outputWidth;
			featureOutputHeight_[slot] = outputHeight;
			LOG("[DLSSNR] Feature 18 create success slot=" << slot << " proxyHits=" << scope.Hits());
			reset = true;
		}

		ParamSet(parameters, "DLSSNR.Color", color);
		ParamSet(parameters, "DLSSNR.Depth", depth);
		ParamSet(parameters, "DLSSNR.MVec", motionVectors);
		ParamSet(parameters, "DLSSNR.Output", output);
		ParamSet(parameters, "DLSSNR.ColorSubrectBaseX", 0u);
		ParamSet(parameters, "DLSSNR.ColorSubrectBaseY", 0u);
		ParamSet(parameters, "DLSSNR.ColorSubrectWidth", inputWidth);
		ParamSet(parameters, "DLSSNR.ColorSubrectHeight", inputHeight);
		ParamSet(parameters, "DLSSNR.DepthSubrectBaseX", 0u);
		ParamSet(parameters, "DLSSNR.DepthSubrectBaseY", 0u);
		ParamSet(parameters, "DLSSNR.DepthSubrectWidth", inputWidth);
		ParamSet(parameters, "DLSSNR.DepthSubrectHeight", inputHeight);
		ParamSet(parameters, "DLSSNR.MVecSubrectBaseX", 0u);
		ParamSet(parameters, "DLSSNR.MVecSubrectBaseY", 0u);
		ParamSet(parameters, "DLSSNR.MVecSubrectWidth", inputWidth);
		ParamSet(parameters, "DLSSNR.MVecSubrectHeight", inputHeight);
		ParamSet(parameters, "DLSSNR.OutputSubrectBaseX", 0u);
		ParamSet(parameters, "DLSSNR.OutputSubrectBaseY", 0u);
		ParamSet(parameters, "DLSSNR.OutputSubrectWidth", outputWidth);
		ParamSet(parameters, "DLSSNR.OutputSubrectHeight", outputHeight);
		ParamSet(parameters, "DLSSNR.MVecScaleX", motionVectorScaleX);
		ParamSet(parameters, "DLSSNR.MVecScaleY", motionVectorScaleY);
		ParamSet(parameters, "DLSSNR.DepthInverted", tuning.depthInverted ? 1u : 0u);
		ParamSet(parameters, "DLSSNR.Enabled", 1u);
		ParamSet(parameters, "DLSSNR.Reset", reset ? 1u : 0u);
		// The runtime reads the private NR preset hint during creation on current
		// builds, but setting it during evaluation as well keeps the control live
		// on builds that re-read hints per frame.
		ParamSet(parameters, "DLSSNR.Hint.Render.Preset",
			static_cast<int>(std::clamp(tuning.preset, 0u, 3u)));
		ParamSet(parameters, "DLSSNR.Intensity", tuning.intensity);
		ParamSet(parameters, "DLSSNR.LocalToneStrength", tuning.localToneStrength);
		ParamSet(parameters, "DLSSNR.LocalStructureStrength", tuning.localStructureStrength);
		ParamSet(parameters, "DLSSNR.SkinStructureStrength", tuning.skinStructureStrength);
		ParamSet(parameters, "DLSSNR.UseAutoMask", tuning.useAutoMask ? 1u : 0u);
		ParamSet(parameters, "DLSSNR.Style", std::min<std::uint32_t>(tuning.style, 2u));
		ParamSet(parameters, "DLSSNR.UICorrection", tuning.uiCorrection ? 1u : 0u);
		ParamSet(parameters, "DLSS.Indicator.Invert.X.Axis", 0);
		ParamSet(parameters, "DLSS.Indicator.Invert.Y.Axis", 0);
		const bool firstEvaluation = evaluationAttempts_++ == 0;
		if (firstEvaluation || reset)
			LOG("[DLSSNR] tuning preset=" << tuning.preset
				<< " style=" << tuning.style
				<< " intensity=" << tuning.intensity
				<< " tone=" << tuning.localToneStrength
				<< " structure=" << tuning.localStructureStrength
				<< " skin=" << tuning.skinStructureStrength
				<< " autoMask=" << (tuning.useAutoMask ? 1 : 0)
				<< " uiCorrection=" << (tuning.uiCorrection ? 1 : 0)
				<< " depthInverted=" << (tuning.depthInverted ? 1 : 0)
				<< " mvScale=" << tuning.motionScaleX << "," << tuning.motionScaleY
				<< " frameGuidance=" << tuning.frameGuidance);
		if (firstEvaluation)
			LOG("[DLSSNR] Feature 18 evaluate begin");
		ngxResult_ = static_cast<std::uint32_t>(evaluate(commandList,
			static_cast<NVSDK_NGX_Handle*>(featureHandles_[slot]), parameters, nullptr));
		if (ngxResult_ != NVSDK_NGX_Result_Success) {
			detail_ = "Feature 18 evaluate failed slot=" + std::to_string(slot) +
				" result=" + Hex(ngxResult_);
			return false;
		}
		++successfulFrames_;
		if (successfulFrames_ == 1 || successfulFrames_ % 60 == 0)
			LOG("[DLSSNR] Feature 18 evaluate success count=" << successfulFrames_);
		return true;
	}

	void Runtime::ResetFeature(std::uint32_t slot)
	{
		if (!module_ || slot >= 2)
			return;
		SignedRuntimePathScope scope(static_cast<HMODULE>(module_), path_.parent_path() / L"nvngx.dll");
		auto release = reinterpret_cast<ReleaseFeature>(GetProcAddress(static_cast<HMODULE>(module_), "NVSDK_NGX_D3D12_ReleaseFeature"));
		if (featureHandles_[slot] && release) {
			const auto result = release(static_cast<NVSDK_NGX_Handle*>(featureHandles_[slot]));
			if (result != NVSDK_NGX_Result_Success)
				LOG("[DLSSNR] Feature 18 release failed slot=" << slot << " result="
					<< Hex(static_cast<std::uint32_t>(result)) << " proxyInstalled=" << scope.IsInstalled());
		}
		featureHandles_[slot] = nullptr;
		featureInputWidth_[slot] = featureInputHeight_[slot] = 0;
		featureOutputWidth_[slot] = featureOutputHeight_[slot] = 0;
	}

	void Runtime::ResetFeatures()
	{
		for (std::uint32_t slot = 0; slot < 2; ++slot)
			ResetFeature(slot);
		successfulFrames_ = 0;
		evaluationAttempts_ = 0;
	}

	void Runtime::Shutdown()
	{
		if (device_ && module_) {
			ResetFeatures();
			HMODULE core = FindNgxCoreModule();
			if (parameters_ && core) {
				auto destroy = reinterpret_cast<DestroyParameters>(GetProcAddress(core, "NVSDK_NGX_D3D12_DestroyParameters"));
				if (destroy) destroy(static_cast<NVSDK_NGX_Parameter*>(parameters_));
			}
			parameters_ = nullptr;
			auto shutdown = reinterpret_cast<ShutdownD3D12>(GetProcAddress(static_cast<HMODULE>(module_), "NVSDK_NGX_D3D12_Shutdown1"));
			SignedRuntimePathScope scope(static_cast<HMODULE>(module_), path_.parent_path() / L"nvngx.dll");
			if (shutdown) {
				const auto result = shutdown(device_);
				if (result != NVSDK_NGX_Result_Success)
					LOG("[DLSSNR] NGX shutdown failed result=" << Hex(static_cast<std::uint32_t>(result))
						<< " proxyInstalled=" << scope.IsInstalled());
			}
			device_->Release();
			device_ = nullptr;
		}
		if (module_) FreeLibrary(static_cast<HMODULE>(module_));
		module_ = nullptr;
		status_ = RuntimeStatus::NotProbed;
		path_.clear();
		version_.clear();
		detail_.clear();
		ngxResult_ = applicationId_ = apiVersion_ = 0;
		successfulFrames_ = 0;
		evaluationAttempts_ = 0;
	}

	const char* ToString(RuntimeStatus status)
	{
		switch (status) {
		case RuntimeStatus::NotProbed: return "not-probed";
		case RuntimeStatus::NotFound: return "not-found";
		case RuntimeStatus::VersionUnavailable: return "version-unavailable";
		case RuntimeStatus::UnsupportedVersion: return "unsupported-version";
		case RuntimeStatus::LoadFailed: return "load-failed";
		case RuntimeStatus::MissingExport: return "missing-export";
		case RuntimeStatus::Ready: return "ready";
		case RuntimeStatus::InitializationFailed: return "initialization-failed";
		case RuntimeStatus::CoreUnavailable: return "core-unavailable";
		case RuntimeStatus::ParameterAllocationFailed: return "parameter-allocation-failed";
		case RuntimeStatus::Initialized: return "initialized";
		}
		return "unknown";
	}
}
