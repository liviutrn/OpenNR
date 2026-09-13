param(
    [Parameter(Mandatory=$true)][string]$Plan,
    [switch]$StartTraining
)
$ErrorActionPreference = 'Stop'
if (-not $StartTraining) { throw 'Training is paused. Explicit -StartTraining is required after user authorization.' }
$recipe = Get-Content -LiteralPath $Plan -Raw | ConvertFrom-Json
if ($recipe.schema -ne 'opennr-joint-teacher-training-plan-v1' -or $recipe.state -ne 'prepared_paused') { throw 'Unexpected training plan' }
foreach ($sourceEntry in $recipe.source_sha256.PSObject.Properties) {
    $sourcePath = Join-Path $PSScriptRoot $sourceEntry.Name
    if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceEntry.Value) { throw "Training source changed: $($sourceEntry.Name)" }
}
for ($cohortIndex=0; $cohortIndex -lt $recipe.cohorts.Count; $cohortIndex++) {
    $completionPath = Join-Path $recipe.cohorts[$cohortIndex] 'complete.json'
    if ((Get-FileHash -LiteralPath $completionPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $recipe.cohort_complete_sha256[$cohortIndex]) { throw 'Cohort completion identity changed' }
}
if (Test-Path -LiteralPath $recipe.output) { throw 'Output exists. Do not overwrite or restart an existing experiment.' }
$trainingArguments = @((Join-Path $PSScriptRoot 'train_spatial_tone.py'), '--run', $recipe.parent_run,
    '--output', $recipe.output, '--stable-unet', '--initial-head-run', $recipe.initial_head_run,
    '--additional-cohort', $recipe.cohorts[3], '--two-pass-cohort', $recipe.cohorts[4],
    '--steps', [string]$recipe.steps, '--seed', [string]$recipe.seed)
& 'E:/OpenNR-VR-Poc-Venv/Scripts/python.exe' @trainingArguments
exit $LASTEXITCODE
