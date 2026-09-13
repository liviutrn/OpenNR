param(
    [string]$ModelRoot = 'C:\OpenNR\Models'
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = 'C:\OpenNR\python312_ml_deps_gen_20260910;C:\OpenNR\python312_ml_deps_20260908'

$baseRevision = '462165984030d82259a11f4367a4eed129e94a7b'
$controlRevision = 'eb115a19a10d14909256db740ed109532ab1483c'
$base = Join-Path $ModelRoot 'sdxl-base-1.0'
$control = Join-Path $ModelRoot 'controlnet-canny-sdxl-1.0'
New-Item -ItemType Directory -Force -Path $base,$control | Out-Null

$baseFiles = @(
    'model_index.json',
    'scheduler/scheduler_config.json',
    'tokenizer/merges.txt',
    'tokenizer/special_tokens_map.json',
    'tokenizer/tokenizer_config.json',
    'tokenizer/vocab.json',
    'tokenizer_2/merges.txt',
    'tokenizer_2/special_tokens_map.json',
    'tokenizer_2/tokenizer_config.json',
    'tokenizer_2/vocab.json',
    'text_encoder/config.json',
    'text_encoder/model.fp16.safetensors',
    'text_encoder_2/config.json',
    'text_encoder_2/model.fp16.safetensors',
    'unet/config.json',
    'unet/diffusion_pytorch_model.fp16.safetensors',
    'vae/config.json',
    'vae/diffusion_pytorch_model.fp16.safetensors'
)

python -m huggingface_hub.commands.huggingface_cli download `
    stabilityai/stable-diffusion-xl-base-1.0 @baseFiles `
    --revision $baseRevision --local-dir $base --max-workers 4
if ($LASTEXITCODE -ne 0) { throw "SDXL download failed: $LASTEXITCODE" }

python -m huggingface_hub.commands.huggingface_cli download `
    diffusers/controlnet-canny-sdxl-1.0 config.json diffusion_pytorch_model.fp16.safetensors `
    --revision $controlRevision --local-dir $control --max-workers 2
if ($LASTEXITCODE -ne 0) { throw "ControlNet download failed: $LASTEXITCODE" }

$expected = @{
    (Join-Path $base 'text_encoder_2/model.fp16.safetensors') = 'EC310DF2AF79C318E24D20511B601A591CA8CD4F1FCE1D8DFF822A356BCDB1F4'
    (Join-Path $base 'unet/diffusion_pytorch_model.fp16.safetensors') = '83E012A805B84C7CA28E5646747C90A243C65C8BA4F070E2D7DDC9D74661E139'
    (Join-Path $control 'diffusion_pytorch_model.fp16.safetensors') = 'B2E7D3921058A442CC80430D1EC8847F42599C705E2451C95E77CF4DCF8D6C25'
}
foreach ($path in $expected.Keys) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing model payload: $path" }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToUpperInvariant()
    if ($actual -ne $expected[$path]) { throw "Hash mismatch for ${path}: $actual" }
    [pscustomobject]@{ Path = $path; SHA256 = $actual; Bytes = (Get-Item -LiteralPath $path).Length }
}
