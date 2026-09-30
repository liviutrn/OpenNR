$ErrorActionPreference = 'Stop'

function Replace-Exact {
    param([string]$Path,[string]$Old,[string]$New)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected exactly one source block in $Path, found $count" }
    [IO.File]::WriteAllText($resolved, $text.Replace($Old,$New), [Text.UTF8Encoding]::new($false))
}

$renderer = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Renderer.cpp'
$runtime = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Runtime.h'

# Reserve 27 atlas-only native handles: 9 model tiers x 3 sequential stages.
$old = 'static constexpr std::uint32_t kFeatureSlotCount = 54;'
$new = 'static constexpr std::uint32_t kFeatureSlotCount = 81;'
Replace-Exact $runtime $old $new

# Atlas slots never alias the established per-eye histories.
$old = @'
		std::uint32_t FeatureSlot(std::uint32_t eyeIndex, std::uint32_t tierIndex, std::uint32_t passIndex)
		{
			return eyeIndex + (passIndex + tierIndex * kCascadePassCount) * kEyeCount;
		}
'@
$new = @'
		std::uint32_t FeatureSlot(std::uint32_t eyeIndex, std::uint32_t tierIndex, std::uint32_t passIndex)
		{
			return eyeIndex + (passIndex + tierIndex * kCascadePassCount) * kEyeCount;
		}

		constexpr std::uint32_t kPerEyeFeatureSlotCount = kEyeCount * kResolutionTierCount * kCascadePassCount;
		std::uint32_t AtlasFeatureSlot(std::uint32_t tierIndex, std::uint32_t passIndex)
		{
			return kPerEyeFeatureSlotCount + tierIndex * kCascadePassCount + passIndex;
		}
'@
Replace-Exact $renderer $old $new

# Atlas backing resources are independent of eye resources so toggling the mode
# cannot contaminate normal stereo histories/resources.
$old = @'
		struct EyeResources
'@
$new = @'
		struct StereoAtlasResources
		{
			SharedTexture color;
			SharedTexture depth;
			SharedTexture motionVectors;
			SharedTexture output;
			std::uint32_t colorEyeWidth = 0;
			std::uint32_t colorEyeHeight = 0;
			std::uint32_t guideEyeWidth = 0;
			std::uint32_t guideEyeHeight = 0;
			std::uint32_t colorGuard = 0;
			std::uint32_t guideGuard = 0;
			bool valid = false;
		};

		struct EyeResources
'@
Replace-Exact $renderer $old $new

# Add atlas pack/evaluate helpers before failure latching.
$old = @'
		bool LatchFailure(const char* operation, HRESULT error)
'@
$new = @'
		enum class StereoAtlasResult
		{
			FallBack,
			Applied,
			Failed,
		};

		struct StereoAtlasPackConstants
		{
			std::uint32_t eyeWidth = 0;
			std::uint32_t eyeHeight = 0;
			std::uint32_t guardWidth = 0;
			std::uint32_t sourceOffsetX = 0;
			std::uint32_t sourceOffsetY = 0;
			std::uint32_t atlasWidth = 0;
			std::uint32_t atlasHeight = 0;
			std::uint32_t padding = 0;
		};
		static_assert(sizeof(StereoAtlasPackConstants) == 32);

		void ResetStereoAtlasFeatures()
		{
			for (std::uint32_t tier = 0; tier < kResolutionTierCount; ++tier)
				for (std::uint32_t pass = 0; pass < kCascadePassCount; ++pass)
					Runtime::Instance().ResetFeature(AtlasFeatureSlot(tier, pass));
			stereoAtlasResetPending = true;
		}

		bool EnsureStereoAtlasPackResources(ID3D11Device* device)
		{
			if (!device)
				return false;
			if (!stereoAtlasColorPackCS.Get(L"Data\\Shaders\\Upscaling\\NeuralRendering\\StereoAtlasPackColorCS.hlsl", {},
				"cs_5_0", "main", "NeuralRendering::StereoAtlasPackColorCS") ||
				!stereoAtlasDepthPackCS.Get(L"Data\\Shaders\\Upscaling\\NeuralRendering\\StereoAtlasPackDepthCS.hlsl", {},
				"cs_5_0", "main", "NeuralRendering::StereoAtlasPackDepthCS") ||
				!stereoAtlasMotionPackCS.Get(L"Data\\Shaders\\Upscaling\\NeuralRendering\\StereoAtlasPackMotionCS.hlsl", {},
				"cs_5_0", "main", "NeuralRendering::StereoAtlasPackMotionCS"))
				return false;
			if (!stereoAtlasPackCB) {
				D3D11_BUFFER_DESC desc{};
				desc.ByteWidth = sizeof(StereoAtlasPackConstants);
				desc.Usage = D3D11_USAGE_DEFAULT;
				desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&desc, nullptr, stereoAtlasPackCB.GetAddressOf())))
					return false;
				Util::SetResourceName(stereoAtlasPackCB.Get(), "NeuralRendering::StereoAtlasPackCB");
			}
			return true;
		}

		bool DispatchStereoAtlasPack(ID3D11DeviceContext* context, ID3D11ComputeShader* shader,
			ID3D11ShaderResourceView* left, ID3D11ShaderResourceView* right, ID3D11UnorderedAccessView* target,
			std::uint32_t eyeWidth, std::uint32_t eyeHeight, std::uint32_t guardWidth,
			std::uint32_t sourceOffsetX, std::uint32_t sourceOffsetY)
		{
			if (!context || !shader || !left || !right || !target || !eyeWidth || !eyeHeight || !guardWidth)
				return false;
			StereoAtlasPackConstants constants{};
			constants.eyeWidth = eyeWidth;
			constants.eyeHeight = eyeHeight;
			constants.guardWidth = guardWidth;
			constants.sourceOffsetX = sourceOffsetX;
			constants.sourceOffsetY = sourceOffsetY;
			constants.atlasWidth = eyeWidth * 2 + guardWidth;
			constants.atlasHeight = eyeHeight;
			context->UpdateSubresource(stereoAtlasPackCB.Get(), 0, nullptr, &constants, 0, 0);
			ID3D11ShaderResourceView* sources[2]{ left, right };
			ID3D11Buffer* cb = stereoAtlasPackCB.Get();
			context->CSSetShader(shader, nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &cb);
			context->CSSetShaderResources(0, 2, sources);
			context->CSSetUnorderedAccessViews(0, 1, &target, nullptr);
			context->Dispatch((constants.atlasWidth + 7) / 8, (constants.atlasHeight + 7) / 8, 1);
			ID3D11ShaderResourceView* nullSRVs[2]{};
			ID3D11UnorderedAccessView* nullUAV = nullptr;
			ID3D11Buffer* nullCB = nullptr;
			context->CSSetShaderResources(0, 2, nullSRVs);
			context->CSSetUnorderedAccessViews(0, 1, &nullUAV, nullptr);
			context->CSSetConstantBuffers(0, 1, &nullCB);
			context->CSSetShader(nullptr, nullptr, 0);
			return true;
		}

		bool EnsureStereoAtlasResources(ID3D11Device* device, std::uint32_t modelWidth, std::uint32_t modelHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorGuard, std::uint32_t guideGuard)
		{
			if (!device || !modelWidth || !modelHeight || !guideWidth || !guideHeight || !colorGuard || !guideGuard)
				return false;
			const auto colorAtlasWidth = modelWidth * 2 + colorGuard;
			const auto guideAtlasWidth = guideWidth * 2 + guideGuard;
			const UINT sharedFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
			const auto colorDesc = MakeSharedDesc(eyes[0].color.desc, colorAtlasWidth, modelHeight, sharedFlags);
			const auto outputDesc = colorDesc;
			const auto depthDesc = MakeSharedDesc(eyes[0].depth.desc, guideAtlasWidth, guideHeight, sharedFlags);
			const auto motionDesc = MakeSharedDesc(eyes[0].motionVectors.desc, guideAtlasWidth, guideHeight, sharedFlags);
			const bool matches = stereoAtlas.valid &&
				stereoAtlas.colorEyeWidth == modelWidth && stereoAtlas.colorEyeHeight == modelHeight &&
				stereoAtlas.guideEyeWidth == guideWidth && stereoAtlas.guideEyeHeight == guideHeight &&
				stereoAtlas.colorGuard == colorGuard && stereoAtlas.guideGuard == guideGuard &&
				Matches(stereoAtlas.color, colorDesc) && Matches(stereoAtlas.depth, depthDesc) &&
				Matches(stereoAtlas.motionVectors, motionDesc) && Matches(stereoAtlas.output, outputDesc);
			if (matches)
				return true;
			if (stereoAtlas.valid && !interop.WaitForIdle())
				return false;
			ResetStereoAtlasFeatures();
			stereoAtlas = {};
			if (!interop.CreateSharedTexture(colorDesc, stereoAtlas.color, "NeuralRendering::StereoAtlasColor") ||
				!interop.CreateSharedTexture(depthDesc, stereoAtlas.depth, "NeuralRendering::StereoAtlasDepth") ||
				!interop.CreateSharedTexture(motionDesc, stereoAtlas.motionVectors, "NeuralRendering::StereoAtlasMotion") ||
				!interop.CreateSharedTexture(outputDesc, stereoAtlas.output, "NeuralRendering::StereoAtlasOutput"))
			{
				stereoAtlas = {};
				return false;
			}
			stereoAtlas.colorEyeWidth = modelWidth;
			stereoAtlas.colorEyeHeight = modelHeight;
			stereoAtlas.guideEyeWidth = guideWidth;
			stereoAtlas.guideEyeHeight = guideHeight;
			stereoAtlas.colorGuard = colorGuard;
			stereoAtlas.guideGuard = guideGuard;
			stereoAtlas.valid = true;
			return true;
		}

		bool PackStereoAtlas(ID3D11Device* device, ID3D11DeviceContext* context,
			ID3D11ShaderResourceView* leftColor, ID3D11ShaderResourceView* rightColor,
			ID3D11ShaderResourceView* leftDepth, ID3D11ShaderResourceView* rightDepth,
			ID3D11ShaderResourceView* leftMotion, ID3D11ShaderResourceView* rightMotion,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorGuard, std::uint32_t guideGuard,
			std::uint32_t colorOffsetX = 0, std::uint32_t colorOffsetY = 0,
			std::uint32_t guideOffsetX = 0, std::uint32_t guideOffsetY = 0)
		{
			return EnsureStereoAtlasPackResources(device) &&
				DispatchStereoAtlasPack(context, stereoAtlasColorPackCS.get(), leftColor, rightColor, stereoAtlas.color.uav11.Get(),
					colorWidth, colorHeight, colorGuard, colorOffsetX, colorOffsetY) &&
				DispatchStereoAtlasPack(context, stereoAtlasDepthPackCS.get(), leftDepth, rightDepth, stereoAtlas.depth.uav11.Get(),
					guideWidth, guideHeight, guideGuard, guideOffsetX, guideOffsetY) &&
				DispatchStereoAtlasPack(context, stereoAtlasMotionPackCS.get(), leftMotion, rightMotion, stereoAtlas.motionVectors.uav11.Get(),
					guideWidth, guideHeight, guideGuard, guideOffsetX, guideOffsetY);
		}

		bool EvaluateStereoAtlasPass(std::uint32_t tierIndex, std::uint32_t passIndex,
			std::uint32_t eyeColorWidth, std::uint32_t eyeColorHeight,
			std::uint32_t eyeGuideWidth, std::uint32_t eyeGuideHeight,
			std::uint32_t colorGuard, std::uint32_t guideGuard,
			float motionScaleX, float motionScaleY, const Tuning& tuning, bool reset)
		{
			ID3D12GraphicsCommandList* commandList = nullptr;
			if (!interop.BeginD3D12(&commandList))
				return false;
			const auto atlasColorWidth = eyeColorWidth * 2 + colorGuard;
			const auto atlasGuideWidth = eyeGuideWidth * 2 + guideGuard;
			TransitionEvaluationResources(commandList, stereoAtlas.color.resource12.Get(), stereoAtlas.depth.resource12.Get(),
				stereoAtlas.motionVectors.resource12.Get(), stereoAtlas.output.resource12.Get(), true);
			Feature18GuideContract guide{};
			guide.colorWidth = atlasColorWidth;
			guide.colorHeight = eyeColorHeight;
			guide.depthWidth = atlasGuideWidth;
			guide.depthHeight = eyeGuideHeight;
			guide.motionWidth = atlasGuideWidth;
			guide.motionHeight = eyeGuideHeight;
			guide.outputWidth = atlasColorWidth;
			guide.outputHeight = eyeColorHeight;
			guide.creationInputWidth = atlasColorWidth;
			guide.creationInputHeight = eyeColorHeight;
			guide.creationOutputWidth = atlasColorWidth;
			guide.creationOutputHeight = eyeColorHeight;
			guide.motionVectorScaleX = motionScaleX;
			guide.motionVectorScaleY = motionScaleY;
			guide.motionVectorsLowResolution = atlasGuideWidth <= atlasColorWidth && eyeGuideHeight <= eyeColorHeight;
			const auto passTuning = TuningForCascadePass(tuning, passIndex);
			const bool succeeded = Runtime::Instance().Execute(commandList, AtlasFeatureSlot(tierIndex, passIndex),
				stereoAtlas.color.resource12.Get(), stereoAtlas.depth.resource12.Get(), stereoAtlas.motionVectors.resource12.Get(),
				stereoAtlas.output.resource12.Get(), guide, passTuning, reset);
			TransitionEvaluationResources(commandList, stereoAtlas.color.resource12.Get(), stereoAtlas.depth.resource12.Get(),
				stereoAtlas.motionVectors.resource12.Get(), stereoAtlas.output.resource12.Get(), false);
			if (!interop.EndD3D12())
				return false;
			return succeeded;
		}

		void SplitStereoAtlasOutput(ID3D11DeviceContext* context, ID3D11Resource* leftTarget, ID3D11Resource* rightTarget,
			std::uint32_t eyeWidth, std::uint32_t eyeHeight, std::uint32_t guardWidth)
		{
			const D3D11_BOX leftBox{ 0, 0, 0, eyeWidth, eyeHeight, 1 };
			const D3D11_BOX rightBox{ eyeWidth + guardWidth, 0, 0, eyeWidth * 2 + guardWidth, eyeHeight, 1 };
			context->CopySubresourceRegion(leftTarget, 0, 0, 0, 0, stereoAtlas.output.resource11.Get(), 0, &leftBox);
			context->CopySubresourceRegion(rightTarget, 0, 0, 0, 0, stereoAtlas.output.resource11.Get(), 0, &rightBox);
		}

		StereoAtlasResult ApplyStereoAtlasNative(ID3D11Device* device, ID3D11DeviceContext* context,
			const std::array<StereoEyeInput, 2>& inputs, std::uint32_t tierIndex,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t modelWidth, std::uint32_t modelHeight,
			std::uint32_t modelResolution, std::uint32_t passCount, const Tuning& tuning)
		{
			if (!tuning.stereoAtlas) {
				if (stereoAtlasActiveLastFrame) {
					if (interop.WaitForIdle()) ResetStereoAtlasFeatures();
					stereoAtlasActiveLastFrame = false;
				}
				return StereoAtlasResult::FallBack;
			}
			const bool scalesMatch = std::abs(inputs[0].motionVectorScaleX - inputs[1].motionVectorScaleX) < 1e-4f &&
				std::abs(inputs[0].motionVectorScaleY - inputs[1].motionVectorScaleY) < 1e-4f;
			const bool compatible = passCount >= 1 && passCount <= 2 && !tuning.adaptiveResolution &&
				tuning.temporalReuseCadence == 0 && !tuning.temporalReuseStaggerEyes && scalesMatch &&
				modelWidth && modelHeight && guideWidth && guideHeight;
			if (!compatible) {
				if (!stereoAtlasFallbackLogged) {
					logger::warn("[DLSSNR][Atlas] incompatible route; falling back to independent-eye Feature18");
					stereoAtlasFallbackLogged = true;
				}
				if (stereoAtlasActiveLastFrame && interop.WaitForIdle()) ResetStereoAtlasFeatures();
				stereoAtlasActiveLastFrame = false;
				return StereoAtlasResult::FallBack;
			}

			const auto requestedGuard = std::clamp(tuning.stereoAtlasGuardPixels, 8u, 256u);
			const auto colorGuard = std::clamp(ScaleDimension(requestedGuard, modelResolution), 1u, modelWidth);
			const auto guideGuard = std::clamp(static_cast<std::uint32_t>(std::lround(
				static_cast<double>(colorGuard) * guideWidth / std::max(modelWidth, 1u))), 1u, guideWidth);
			if (!EnsureStereoAtlasResources(device, modelWidth, modelHeight, guideWidth, guideHeight, colorGuard, guideGuard))
				return StereoAtlasResult::FallBack;

			auto& leftTier = eyes[0].tiers[tierIndex];
			auto& rightTier = eyes[1].tiers[tierIndex];
			ID3D11ShaderResourceView* leftInput = leftTier.reducedResolution ? leftTier.modelInput.srv11.Get() : eyes[0].color.srv11.Get();
			ID3D11ShaderResourceView* rightInput = rightTier.reducedResolution ? rightTier.modelInput.srv11.Get() : eyes[1].color.srv11.Get();
			if (!leftInput || !rightInput || !eyes[0].depth.srv11 || !eyes[1].depth.srv11 ||
				!eyes[0].motionVectors.srv11 || !eyes[1].motionVectors.srv11 ||
				!PackStereoAtlas(device, context, leftInput, rightInput,
					eyes[0].depth.srv11.Get(), eyes[1].depth.srv11.Get(),
					eyes[0].motionVectors.srv11.Get(), eyes[1].motionVectors.srv11.Get(),
					modelWidth, modelHeight, guideWidth, guideHeight, colorGuard, guideGuard))
				return StereoAtlasResult::FallBack;

			const float motionScaleX = inputs[0].motionVectorScaleX * static_cast<float>(modelWidth) / colorWidth;
			const float motionScaleY = inputs[0].motionVectorScaleY * static_cast<float>(modelHeight) / colorHeight;
			const bool reset = stereoAtlasResetPending || resetPending[0][tierIndex] || resetPending[1][tierIndex] ||
				(temporalSkippedSinceFull && tuning.temporalReuseResetAfterSkip);
			if (!EvaluateStereoAtlasPass(tierIndex, 0, modelWidth, modelHeight, guideWidth, guideHeight,
				colorGuard, guideGuard, motionScaleX, motionScaleY, tuning, reset)) {
			Runtime::Instance().ResetFeature(AtlasFeatureSlot(tierIndex, 0));
			stereoAtlasResetPending = true;
			return StereoAtlasResult::FallBack;
			}

			ID3D11Resource* leftPass1Target = passCount == 1 ? leftTier.output.resource11.Get() : leftTier.cascadeIntermediates[0].resource11.Get();
			ID3D11Resource* rightPass1Target = passCount == 1 ? rightTier.output.resource11.Get() : rightTier.cascadeIntermediates[0].resource11.Get();
			if (!leftPass1Target || !rightPass1Target)
				return StereoAtlasResult::FallBack;
			SplitStereoAtlasOutput(context, leftPass1Target, rightPass1Target, modelWidth, modelHeight, colorGuard);

			if (passCount == 2) {
				const auto coverage = std::clamp(tuning.secondPass.coveragePercent, 50u, 100u);
				const auto pass2Width = ScaleDimension(modelWidth, coverage);
				const auto pass2Height = ScaleDimension(modelHeight, coverage);
				const auto pass2GuideWidth = ScaleDimension(guideWidth, coverage);
				const auto pass2GuideHeight = ScaleDimension(guideHeight, coverage);
				const auto pass2ColorGuard = std::min(colorGuard, pass2Width);
				const auto pass2GuideGuard = std::min(guideGuard, pass2GuideWidth);
				const auto colorOffsetX = (modelWidth - pass2Width) / 2;
				const auto colorOffsetY = (modelHeight - pass2Height) / 2;
				const auto guideOffsetX = (guideWidth - pass2GuideWidth) / 2;
				const auto guideOffsetY = (guideHeight - pass2GuideHeight) / 2;
				if (!PackStereoAtlas(device, context,
					leftTier.cascadeIntermediates[0].srv11.Get(), rightTier.cascadeIntermediates[0].srv11.Get(),
					eyes[0].depth.srv11.Get(), eyes[1].depth.srv11.Get(),
					eyes[0].motionVectors.srv11.Get(), eyes[1].motionVectors.srv11.Get(),
					pass2Width, pass2Height, pass2GuideWidth, pass2GuideHeight,
					pass2ColorGuard, pass2GuideGuard, colorOffsetX, colorOffsetY, guideOffsetX, guideOffsetY))
					return StereoAtlasResult::FallBack;
				if (!EvaluateStereoAtlasPass(tierIndex, 1, pass2Width, pass2Height, pass2GuideWidth, pass2GuideHeight,
					pass2ColorGuard, pass2GuideGuard, motionScaleX, motionScaleY, tuning, reset)) {
					Runtime::Instance().ResetFeature(AtlasFeatureSlot(tierIndex, 1));
					stereoAtlasResetPending = true;
					return StereoAtlasResult::FallBack;
				}
				if (coverage < 100) {
					if (!leftTier.secondPassOutput.resource11 || !rightTier.secondPassOutput.resource11)
						return StereoAtlasResult::FallBack;
					SplitStereoAtlasOutput(context, leftTier.secondPassOutput.resource11.Get(), rightTier.secondPassOutput.resource11.Get(),
						pass2Width, pass2Height, pass2ColorGuard);
					if (!CompositeSequentialPass(device, context, leftTier, modelWidth, modelHeight, pass2Width, pass2Height, tuning) ||
						!CompositeSequentialPass(device, context, rightTier, modelWidth, modelHeight, pass2Width, pass2Height, tuning))
						return StereoAtlasResult::FallBack;
				} else {
					SplitStereoAtlasOutput(context, leftTier.output.resource11.Get(), rightTier.output.resource11.Get(),
						modelWidth, modelHeight, colorGuard);
				}
			}

			stereoAtlasResetPending = false;
			stereoAtlasActiveLastFrame = true;
			stereoAtlasFallbackLogged = false;
			if (!stereoAtlasActiveLogged) {
				logger::info("[DLSSNR][Atlas] active passes={} guard={}px modelGuard={}px; one Feature18 atlas evaluation per pass",
					passCount, tuning.stereoAtlasGuardPixels, colorGuard);
				stereoAtlasActiveLogged = true;
			}
			return StereoAtlasResult::Applied;
		}

		bool LatchFailure(const char* operation, HRESULT error)
'@
Replace-Exact $renderer $old $new

# Atlas state and shader ownership.
$old = @'
		Util::LazyShader<ID3D11ComputeShader> sequentialCompositeCS;
		Microsoft::WRL::ComPtr<ID3D11Buffer> sequentialCompositeCB;
'@
$new = @'
		Util::LazyShader<ID3D11ComputeShader> sequentialCompositeCS;
		Util::LazyShader<ID3D11ComputeShader> stereoAtlasColorPackCS;
		Util::LazyShader<ID3D11ComputeShader> stereoAtlasDepthPackCS;
		Util::LazyShader<ID3D11ComputeShader> stereoAtlasMotionPackCS;
		Microsoft::WRL::ComPtr<ID3D11Buffer> sequentialCompositeCB;
		Microsoft::WRL::ComPtr<ID3D11Buffer> stereoAtlasPackCB;
'@
Replace-Exact $renderer $old $new

$old = @'
		std::array<EyeResources, 2> eyes;
		std::array<std::array<bool, kResolutionTierCount>, 2> resetPending{};
'@
$new = @'
		std::array<EyeResources, 2> eyes;
		StereoAtlasResources stereoAtlas;
		std::array<std::array<bool, kResolutionTierCount>, 2> resetPending{};
		bool stereoAtlasResetPending = true;
		bool stereoAtlasActiveLastFrame = false;
		bool stereoAtlasActiveLogged = false;
		bool stereoAtlasFallbackLogged = false;
'@
Replace-Exact $renderer $old $new

# Reset / shader-cache ownership.
$old = @'
			sequentialCompositeCS.Reset();
			sequentialCompositeCB.Reset();
			modelResolutionCB.Reset();
'@
$new = @'
			sequentialCompositeCS.Reset();
			stereoAtlasColorPackCS.Reset();
			stereoAtlasDepthPackCS.Reset();
			stereoAtlasMotionPackCS.Reset();
			sequentialCompositeCB.Reset();
			stereoAtlasPackCB.Reset();
			stereoAtlas = {};
			stereoAtlasResetPending = true;
			stereoAtlasActiveLastFrame = false;
			stereoAtlasActiveLogged = false;
			stereoAtlasFallbackLogged = false;
			modelResolutionCB.Reset();
'@
Replace-Exact $renderer $old $new

$old = @'
			sequentialCompositeCS.Reset();
			for (auto& eye : eyes)
'@
$new = @'
			sequentialCompositeCS.Reset();
			stereoAtlasColorPackCS.Reset();
			stereoAtlasDepthPackCS.Reset();
			stereoAtlasMotionPackCS.Reset();
			for (auto& eye : eyes)
'@
Replace-Exact $renderer $old $new

# Try atlas after all per-eye inputs are prepared and capture has consumed them,
# but before the normal independent-eye D3D12 evaluate block.
$old = @'
			ID3D12GraphicsCommandList* commandList = nullptr;
			if (!interop.BeginD3D12(&commandList)) {
'@
$new = @'
			bool nativeEvaluationDone = false;
			const auto atlasResult = ApplyStereoAtlasNative(device, context, inputs, tierIndex,
				colorWidth, colorHeight, guideWidth, guideHeight, modelWidth, modelHeight,
				modelResolution, passCount, tuning);
			if (atlasResult == StereoAtlasResult::Failed) {
#if defined(OPENNR_CAPTURE_ENABLED)
				if (captureFrame)
					globals::features::openNRCapture.AbortFrame();
#endif
				return LatchFailure("stereo atlas", E_FAIL);
			}
			nativeEvaluationDone = atlasResult == StereoAtlasResult::Applied;

			if (!nativeEvaluationDone) {
			ID3D12GraphicsCommandList* commandList = nullptr;
			if (!interop.BeginD3D12(&commandList)) {
'@
Replace-Exact $renderer $old $new

$old = @'
				return LatchFailure("Feature 18 stereo", static_cast<HRESULT>(Runtime::Instance().NgxResult()));
			}

			D3D11_BOX outputBox{ 0, 0, 0, colorWidth, colorHeight, 1 };
'@
$new = @'
				return LatchFailure("Feature 18 stereo", static_cast<HRESULT>(Runtime::Instance().NgxResult()));
			}
			}

			D3D11_BOX outputBox{ 0, 0, 0, colorWidth, colorHeight, 1 };
'@
Replace-Exact $renderer $old $new

# The atlas helper already performs the reduced-pass composite; skip the normal
# stereo merge only for that frame.
$old = 'if (passCount == 2 && tuning.secondPass.coveragePercent < 100) {'
$text = [IO.File]::ReadAllText((Resolve-Path $renderer)).Replace("`r`n", "`n")
$matches = [regex]::Matches($text, [regex]::Escape($old))
if ($matches.Count -lt 2) { throw "Expected at least two reduced-pass merge guards, found $($matches.Count)" }
# Only the stereo loop is indented four tabs; preserve the single-eye route.
$text = $text.Replace("`t`t`t`tif (passCount == 2 && tuning.secondPass.coveragePercent < 100) {",
	"`t`t`t`tif (!nativeEvaluationDone && passCount == 2 && tuning.secondPass.coveragePercent < 100) {")
[IO.File]::WriteAllText((Resolve-Path $renderer), $text, [Text.UTF8Encoding]::new($false))

Write-Host 'v01 stereo atlas path applied successfully.'
