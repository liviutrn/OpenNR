[CmdletBinding()]
param(
    [string]$Session,
    [int]$Columns = 3,
    [double]$Scale = 0.5,
    [string]$OutputPath,
    [string]$ProjectRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM'
)

$ErrorActionPreference = 'Stop'
if ($Columns -lt 1) { throw 'Columns must be at least 1.' }
if ($Scale -le 0 -or $Scale -gt 1) { throw 'Scale must be greater than 0 and at most 1.' }
$matrixRoot = Join-Path $ProjectRoot 'captures\intensity-matrix'
if ($Session) {
    $sessionDirectory = if (Test-Path -LiteralPath $Session -PathType Container) { (Resolve-Path -LiteralPath $Session).Path } else { (Resolve-Path -LiteralPath (Join-Path $matrixRoot $Session)).Path }
} else {
    $sessionDirectory = (Get-ChildItem -LiteralPath $matrixRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}
if (-not $sessionDirectory) { throw 'No matrix session exists.' }
$labels = @('Off', 'I0.0', 'I0.5', 'I1.0', 'I1.5', 'I2.0', 'Cinematic')
$files = foreach ($label in $labels) {
    Get-ChildItem -LiteralPath $sessionDirectory -File -ErrorAction SilentlyContinue |
        Where-Object { $_.BaseName -eq $label -and $_.Extension -match '^\.(png|bmp|jpg|jpeg)$' } |
        Select-Object -First 1
}
if ($files.Count -ne $labels.Count) { throw "Matrix is incomplete: found $($files.Count) of $($labels.Count) images." }
if (-not $OutputPath) { $OutputPath = Join-Path $sessionDirectory 'intensity-matrix.png' }
$outputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

Add-Type -AssemblyName System.Drawing
$images = @()
$canvas = $null
$graphics = $null
$font = $null
try {
    foreach ($file in $files) { $images += [System.Drawing.Image]::FromFile($file.FullName) }
    $tileWidth = [int][math]::Round((($images | Measure-Object Width -Maximum).Maximum) * $Scale)
    $tileHeight = [int][math]::Round((($images | Measure-Object Height -Maximum).Maximum) * $Scale)
    $header = 38
    $rows = [int][math]::Ceiling($labels.Count / [double]$Columns)
    $canvasWidth = $Columns * $tileWidth
    $canvasHeight = $rows * ($tileHeight + $header)
    $canvas = [System.Drawing.Bitmap]::new($canvasWidth, $canvasHeight, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    $graphics.Clear([System.Drawing.Color]::Black)
    $font = [System.Drawing.Font]::new('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
    for ($i = 0; $i -lt $labels.Count; $i++) {
        $col = $i % $Columns
        $row = [int][math]::Floor($i / [double]$Columns)
        $x = $col * $tileWidth
        $y = $row * ($tileHeight + $header)
        $graphics.DrawString($labels[$i], $font, [System.Drawing.Brushes]::White, $x + 8, $y + 8)
        $graphics.DrawImage($images[$i], $x, $y + $header, $tileWidth, $tileHeight)
    }
    $canvas.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    if ($graphics) { $graphics.Dispose() }
    if ($font) { $font.Dispose() }
    if ($canvas) { $canvas.Dispose() }
    foreach ($image in $images) { if ($image) { $image.Dispose() } }
}

[pscustomobject]@{ Output = $OutputPath; Session = $sessionDirectory; Profiles = $labels.Count; Columns = $Columns; Scale = $Scale; Width = $canvasWidth; Height = $canvasHeight } | Format-List
