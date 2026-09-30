$ErrorActionPreference = 'Stop'

function Replace-Exact {
    param([string]$Path,[string]$Old,[string]$New)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected exactly one source block in $Path, found $count" }
    [IO.File]::WriteAllText($resolved, $text.Replace($Old,$New), [Text.UTF8Encoding]::new($false))
}

function Replace-RegexOnce {
    param([string]$Path,[string]$Pattern,[string]$Replacement)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $rx = [regex]::new($Pattern, [Text.RegularExpressions.RegexOptions]::Singleline)
    if ($rx.Matches($text).Count -ne 1) { throw "Expected exactly one regex source block in $Path" }
    [IO.File]::WriteAllText($resolved, $rx.Replace($text,$Replacement,1), [Text.UTF8Encoding]::new($false))
}

$renderer = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Renderer.cpp'

# Add the small D3D11 compute composite used after the native pass-2 evaluation.
$old = @'
		bool LatchFailure(const char* operation, HRESULT error)
'@
$new = @'
		struct SequentialCompositeConstants
		{
			std::uint32_t fullWidth = 0;
			std::uint32_t fullHeight = 0;
			std::uint32_t pass2OffsetX = 0;
			std::uint32_t pass2OffsetY = 0;
			std::uint32_t pass2Width = 0;
			std::uint32_t pass2Height = 0;
			std::uint32_t blendMode = 1;
			std::uint32_t maskMode = 1;
			std::uint32_t frameIndex = 0;
			float featherWidth = 64.0f;
			float ditherStrength = 1.0f;
			float falloffCurve = 1.0f;
			float pad0 = 0.0f;
			float pad1 = 0.0f;
			float pad2 = 0.0f;
			float pad3 = 0.0f;
		};
		static_assert(sizeof(SequentialCompositeConstants) == 64);

		bool EnsureSequentialCompositeResources(ID3D11Device* device)
		{
			if (!device)
				return false;
			if (!sequentialCompositeCS.Get(
				L"Data\\Shaders\\Upscaling\\NeuralRendering\\SequentialCompositeCS.hlsl", {},
				"cs_5_0", "main", "NeuralRendering::SequentialCompositeCS"))
				return false;
			if (!sequentialCompositeCB) {
				D3D11_BUFFER_DESC desc{};
				desc.ByteWidth = sizeof(SequentialCompositeConstants);
				desc.Usage = D3D11_USAGE_DEFAULT;
				desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
				if (FAILED(device->CreateBuffer(&desc, nullptr, sequentialCompositeCB.GetAddressOf())))
					return false;
				Util::SetResourceName(sequentialCompositeCB.Get(), "NeuralRendering::SequentialCompositeCB");
			}
			return true;
		}

		void ClearSequentialCompositeBindings(ID3D11DeviceContext* context)
		{
			if (!context)
				return;
			ID3D11ShaderResourceView* nullSRVs[2]{};
			ID3D11UnorderedAccessView* nullUAV = nullptr;
			ID3D11Buffer* nullCB = nullptr;
			context->CSSetShaderResources(0, 2, nullSRVs);
			context->CSSetUnorderedAccessViews(0, 1, &nullUAV, nullptr);
			context->CSSetConstantBuffers(0, 1, &nullCB);
			context->CSSetShader(nullptr, nullptr, 0);
		}

		bool CompositeSequentialPass(ID3D11Device* device, ID3D11DeviceContext* context,
			TierResources& tier, std::uint32_t fullWidth, std::uint32_t fullHeight,
			std::uint32_t pass2Width, std::uint32_t pass2Height, const Tuning& tuning)
		{
			if (!device || !context || !fullWidth || !fullHeight || !pass2Width || !pass2Height ||
				pass2Width > fullWidth || pass2Height > fullHeight ||
				!tier.cascadeIntermediates[0].srv11 || !tier.secondPassOutput.srv11 || !tier.output.uav11 ||
				!EnsureSequentialCompositeResources(device))
				return false;

			SequentialCompositeConstants constants{};
			constants.fullWidth = fullWidth;
			constants.fullHeight = fullHeight;
			constants.pass2OffsetX = (fullWidth - pass2Width) / 2;
			constants.pass2OffsetY = (fullHeight - pass2Height) / 2;
			constants.pass2Width = pass2Width;
			constants.pass2Height = pass2Height;
			constants.blendMode = std::min(tuning.secondPass.blendMode, 2u);
			constants.maskMode = std::min(tuning.secondPass.maskMode, 1u);
			constants.frameIndex = globals::state ? static_cast<std::uint32_t>(globals::state->frameCount) : 0u;
			constants.featherWidth = std::clamp(tuning.secondPass.featherWidth, 2.0f, 128.0f);
			constants.ditherStrength = std::clamp(tuning.secondPass.ditherStrength, 0.0f, 2.0f);
			constants.falloffCurve = std::clamp(tuning.secondPass.falloffCurve, 0.5f, 2.0f);

			CS_GPU_PASS("NeuralRendering::SequentialComposite");
			context->UpdateSubresource(sequentialCompositeCB.Get(), 0, nullptr, &constants, 0, 0);
			ID3D11ShaderResourceView* sources[2]{
				tier.cascadeIntermediates[0].srv11.Get(), tier.secondPassOutput.srv11.Get() };
			ID3D11UnorderedAccessView* target = tier.output.uav11.Get();
			ID3D11Buffer* cb = sequentialCompositeCB.Get();
			context->CSSetShader(sequentialCompositeCS.get(), nullptr, 0);
			context->CSSetConstantBuffers(0, 1, &cb);
			context->CSSetShaderResources(0, 2, sources);
			context->CSSetUnorderedAccessViews(0, 1, &target, nullptr);
			context->Dispatch((fullWidth + 7) / 8, (fullHeight + 7) / 8, 1);
			ClearSequentialCompositeBindings(context);
			return true;
		}

		bool LatchFailure(const char* operation, HRESULT error)
'@
Replace-Exact $renderer $old $new

# Shader/cache ownership lives with Renderer::State.
$old = @'
		Util::LazyShader<ID3D11ComputeShader> resultShapingCS;
		Microsoft::WRL::ComPtr<ID3D11Buffer> modelResolutionCB;
'@
$new = @'
		Util::LazyShader<ID3D11ComputeShader> resultShapingCS;
		Util::LazyShader<ID3D11ComputeShader> sequentialCompositeCS;
		Microsoft::WRL::ComPtr<ID3D11Buffer> sequentialCompositeCB;
		Microsoft::WRL::ComPtr<ID3D11Buffer> modelResolutionCB;
'@
Replace-Exact $renderer $old $new

# Reset and shader-cache clear must drop the new resources too.
$old = @'
			resultShapingCS.Reset();
			modelResolutionCB.Reset();
'@
$new = @'
			resultShapingCS.Reset();
			sequentialCompositeCS.Reset();
			sequentialCompositeCB.Reset();
			modelResolutionCB.Reset();
'@
Replace-Exact $renderer $old $new

$old = @'
			resultShapingCS.Reset();
			for (auto& eye : eyes)
'@
$new = @'
			resultShapingCS.Reset();
			sequentialCompositeCS.Reset();
			for (auto& eye : eyes)
'@
Replace-Exact $renderer $old $new

# Replace the hard compact-pass merge in the single-eye route.
$pattern = '\t\t\tif \(passCount == 2 && tuning\.secondPass\.coveragePercent < 100\) \{\n\t\t\t\tconst auto pass2Coverage = std::clamp\(tuning\.secondPass\.coveragePercent, 50u, 100u\);\n\t\t\t\tconst auto pass2Width = ScaleDimension\(modelWidth, pass2Coverage\);\n\t\t\t\tconst auto pass2Height = ScaleDimension\(modelHeight, pass2Coverage\);\n\t\t\t\tif \(!tier\.secondPassOutput\.resource11 \|\| !tier\.cascadeIntermediates\[0\]\.resource11\)\n\t\t\t\t\treturn LatchFailure\("second-pass merge resources", E_FAIL\);\n\t\t\t\tcontext->CopyResource\(tier\.output\.resource11\.Get\(\), tier\.cascadeIntermediates\[0\]\.resource11\.Get\(\)\);\n\t\t\t\tconst D3D11_BOX pass2Box\{ 0, 0, 0, pass2Width, pass2Height, 1 \};\n\t\t\t\tcontext->CopySubresourceRegion\(tier\.output\.resource11\.Get\(\), 0,\n\t\t\t\t\t\(modelWidth - pass2Width\) / 2, \(modelHeight - pass2Height\) / 2, 0,\n\t\t\t\t\ttier\.secondPassOutput\.resource11\.Get\(\), 0, &pass2Box\);\n\t\t\t\}'
$replacement = @'
			if (passCount == 2 && tuning.secondPass.coveragePercent < 100) {
				const auto pass2Coverage = std::clamp(tuning.secondPass.coveragePercent, 50u, 100u);
				const auto pass2Width = ScaleDimension(modelWidth, pass2Coverage);
				const auto pass2Height = ScaleDimension(modelHeight, pass2Coverage);
				if (!CompositeSequentialPass(device, context, tier, modelWidth, modelHeight,
					pass2Width, pass2Height, tuning))
					return LatchFailure("second-pass composite", E_FAIL);
			}
'@
Replace-RegexOnce $renderer $pattern $replacement

# Replace the stereo route hard merge as well.
$pattern = '\t\t\t\tif \(passCount == 2 && tuning\.secondPass\.coveragePercent < 100\) \{\n\t\t\t\t\tconst auto pass2Coverage = std::clamp\(tuning\.secondPass\.coveragePercent, 50u, 100u\);\n\t\t\t\t\tconst auto pass2Width = ScaleDimension\(modelWidth, pass2Coverage\);\n\t\t\t\t\tconst auto pass2Height = ScaleDimension\(modelHeight, pass2Coverage\);\n\t\t\t\t\tif \(!tier\.secondPassOutput\.resource11 \|\| !tier\.cascadeIntermediates\[0\]\.resource11\)\n\t\t\t\t\t\treturn LatchFailure\("second-pass stereo merge resources", E_FAIL\);\n\t\t\t\t\tcontext->CopyResource\(tier\.output\.resource11\.Get\(\), tier\.cascadeIntermediates\[0\]\.resource11\.Get\(\)\);\n\t\t\t\t\tconst D3D11_BOX pass2Box\{ 0, 0, 0, pass2Width, pass2Height, 1 \};\n\t\t\t\t\tcontext->CopySubresourceRegion\(tier\.output\.resource11\.Get\(\), 0,\n\t\t\t\t\t\t\(modelWidth - pass2Width\) / 2, \(modelHeight - pass2Height\) / 2, 0,\n\t\t\t\t\t\ttier\.secondPassOutput\.resource11\.Get\(\), 0, &pass2Box\);\n\t\t\t\t\}'
$replacement = @'
				if (passCount == 2 && tuning.secondPass.coveragePercent < 100) {
					const auto pass2Coverage = std::clamp(tuning.secondPass.coveragePercent, 50u, 100u);
					const auto pass2Width = ScaleDimension(modelWidth, pass2Coverage);
					const auto pass2Height = ScaleDimension(modelHeight, pass2Coverage);
					if (!CompositeSequentialPass(device, context, tier, modelWidth, modelHeight,
						pass2Width, pass2Height, tuning))
						return LatchFailure("second-pass stereo composite", E_FAIL);
				}
'@
Replace-RegexOnce $renderer $pattern $replacement

Write-Host 'v01 independent pass-2 feather/dither composite applied successfully.'
