$ErrorActionPreference = 'Stop'

$patch = 'patches/2.20.1-v00-gaze-history.patch'
if (-not (Test-Path $patch)) { throw "Missing v00 patch: $patch" }

git apply --reject $patch
$applyExit = $LASTEXITCODE
$rejects = @(Get-ChildItem 'runtime/open-shaders' -Filter '*.rej' -Recurse)
$expectedReject = (Resolve-Path 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering').Path + '\Renderer.cpp.rej'
if ($applyExit -ne 0) {
    if ($rejects.Count -ne 1 -or $rejects[0].FullName -ne $expectedReject) {
        $rejects | ForEach-Object { Write-Host "Unexpected reject: $($_.FullName)" }
        throw 'v00 patch produced unexpected rejects'
    }
    $renderer = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Renderer.cpp'
    $text = (Get-Content $renderer -Raw).Replace("`r`n", "`n")
    $old = @(
      "`t`treturn state_->ApplyStereo(device, context, color, eyes,",
      "`t`t`tguideWidth, guideHeight, colorWidth, colorHeight, tuning,",
      "`t`t`t`tdestination, destinationUAV, blendSubrect, resourceEnvelope);",
      "`t}", "",
      "`tbool Renderer::Reset() { return state_->Reset(); }",
      "`tvoid Renderer::ClearShaderCache() { state_->ClearShaderCache(); }",
      "`tvoid Renderer::ResetHistory() { state_->ResetHistory(); }"
    ) -join "`n"
    $new = @(
      "`t`tconst bool succeeded = state_->ApplyStereo(device, context, color, eyes,",
      "`t`t`tguideWidth, guideHeight, colorWidth, colorHeight, tuning,",
      "`t`t`t`tdestination, destinationUAV, blendSubrect, resourceEnvelope);",
      "`t`tfor (std::uint32_t eye = 0; eye < 2; ++eye)",
      "`t`t`tFoveatedRenderImpl::CropMotion::Commit(2 + eye, succeeded && eyes[eye].compensateCropMotion);",
      "`t`treturn succeeded;",
      "`t}", "",
      "`tbool Renderer::Reset() { FoveatedRenderImpl::CropMotion::Invalidate(2, 2); return state_->Reset(); }",
      "`tvoid Renderer::ClearShaderCache() { state_->ClearShaderCache(); }",
      "`tvoid Renderer::ResetHistory() { FoveatedRenderImpl::CropMotion::Invalidate(2, 2); state_->ResetHistory(); }"
    ) -join "`n"
    if (-not $text.Contains($old)) { throw 'Expected Renderer wrapper text missing after partial v00 patch' }
    [IO.File]::WriteAllText((Resolve-Path $renderer), $text.Replace($old,$new), [Text.UTF8Encoding]::new($false))
    Remove-Item $rejects[0].FullName -Force
}

if (Get-ChildItem 'runtime/open-shaders' -Filter '*.rej' -Recurse) { throw 'Unexpected patch reject remains' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'v00 reconstructed source has whitespace errors' }
Write-Host 'v00 gaze-history base reconstructed.'
