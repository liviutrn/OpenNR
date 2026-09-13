[CmdletBinding()]
param(
    [string]$Session,
    [string]$APath,
    [string]$BPath,
    [string]$OutputPath,
    [string]$ALabel = 'A',
    [string]$BLabel = 'B',
    [string]$ProjectRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM'
)

$ErrorActionPreference = 'Stop'
$comparisonRoot = Join-Path $ProjectRoot 'captures\ab'

function Find-Session {
    if ($Session) {
        if (Test-Path -LiteralPath $Session -PathType Container) { return (Resolve-Path -LiteralPath $Session).Path }
        $candidate = Join-Path $comparisonRoot $Session
        if (Test-Path -LiteralPath $candidate -PathType Container) { return (Resolve-Path -LiteralPath $candidate).Path }
        throw "Comparison session was not found: $Session"
    }
    $latest = Get-ChildItem -LiteralPath $comparisonRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { throw "No comparison sessions exist under $comparisonRoot" }
    return $latest.FullName
}

$sessionDirectory = Find-Session
if (-not $APath) { $APath = Get-ChildItem -LiteralPath $sessionDirectory -File -ErrorAction Stop | Where-Object { $_.BaseName -eq 'A' -and $_.Extension -match '^\.(png|bmp|jpg|jpeg)$' } | Select-Object -First 1 -ExpandProperty FullName }
if (-not $BPath) { $BPath = Get-ChildItem -LiteralPath $sessionDirectory -File -ErrorAction Stop | Where-Object { $_.BaseName -eq 'B' -and $_.Extension -match '^\.(png|bmp|jpg|jpeg)$' } | Select-Object -First 1 -ExpandProperty FullName }
if (-not $APath -or -not (Test-Path -LiteralPath $APath -PathType Leaf)) { throw 'Side A image was not found.' }
if (-not $BPath -or -not (Test-Path -LiteralPath $BPath -PathType Leaf)) { throw 'Side B image was not found. Capture B before composing the pair.' }
if (-not $OutputPath) { $OutputPath = Join-Path $sessionDirectory 'AB-side-by-side.png' }
$outputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

Add-Type -AssemblyName System.Drawing
$a = $null
$b = $null
$canvas = $null
$graphics = $null
$font = $null
$brush = $null
try {
    $a = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $APath).Path)
    $b = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $BPath).Path)
    $header = 44
    $aWidth = $a.Width
    $bWidth = $b.Width
    $aHeight = $a.Height
    $bHeight = $b.Height
    $outputWidth = $aWidth + $bWidth
    $outputHeight = [math]::Max($aHeight, $bHeight) + $header
    $canvas = [System.Drawing.Bitmap]::new($outputWidth, $outputHeight, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    $graphics.Clear([System.Drawing.Color]::Black)
    $font = [System.Drawing.Font]::new('Segoe UI', 16, [System.Drawing.FontStyle]::Bold)
    $brush = [System.Drawing.Brushes]::White
    $graphics.DrawString($ALabel, $font, $brush, 12, 10)
    $graphics.DrawString($BLabel, $font, $brush, $aWidth + 12, 10)
    $graphics.DrawImage($a, 0, $header, $aWidth, $aHeight)
    $graphics.DrawImage($b, $aWidth, $header, $bWidth, $bHeight)
    $canvas.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    if ($graphics) { $graphics.Dispose() }
    if ($font) { $font.Dispose() }
    if ($canvas) { $canvas.Dispose() }
    if ($a) { $a.Dispose() }
    if ($b) { $b.Dispose() }
}

[pscustomobject]@{ Output = $OutputPath; A = $APath; B = $BPath; Width = $outputWidth; Height = $outputHeight } | Format-List
