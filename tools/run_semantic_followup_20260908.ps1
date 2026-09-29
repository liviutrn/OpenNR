# One-off local research queue for the active goal, not a recurring automation.
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'C:\OpenNR\python312_ml_deps_20260908'
$projectionRoot = 'C:\OpenNR\Training\semantic_projection_pretrained1200_20260908'
$followupStatus = 'out\semantic_followup_status.json'
$waitDeadline = (Get-Date).AddMinutes(40)
function Write-FollowupStatus([string]$state) {
    @{state=$state; updated=(Get-Date -Format o); test_used=$false} |
        ConvertTo-Json | Set-Content -LiteralPath $followupStatus
}
trap {
    Write-FollowupStatus ('failed: ' + $_.Exception.Message)
    throw
}
Write-FollowupStatus 'waiting_for_projection'
do {
    $projectionState = (Get-Content (Join-Path $projectionRoot 'status.json') -Raw | ConvertFrom-Json).state
    if ($projectionState -eq 'failed') { throw 'Projection arm failed; follow-up not started' }
    if ((Get-Date) -gt $waitDeadline) { throw 'Projection wait timed out' }
    if ($projectionState -ne 'complete') { Start-Sleep -Seconds 10 }
} while ($projectionState -ne 'complete')

$history = Get-Content (Join-Path $projectionRoot 'history.json') -Raw | ConvertFrom-Json
$eligible = @($history | Where-Object all_cohorts_improved)
$checkpointName = if ($eligible.Count) { 'best_all_cohorts.pt' } else { 'last.pt' }
$checkpointPath = Join-Path $projectionRoot $checkpointName
Write-FollowupStatus 'verifying_projection_freeze'
& py -3.12 tools\verify_semantic_projection_freeze.py --checkpoint $checkpointPath --encoder-reference C:\OpenNR\Training\semantic_pretrained_arm400_20260908\last.pt --output (Join-Path $projectionRoot 'selected_freeze_verification.json')
if ($LASTEXITCODE -ne 0) { throw 'Projection freeze verification failed' }
Write-FollowupStatus 'replaying_projection'
& py -3.12 tools\verify_semantic_ablation.py --checkpoint $checkpointPath --output (Join-Path $projectionRoot 'independent_replay') --render > out\semantic_projection_replay_stdout.txt 2> out\semantic_projection_replay_stderr.txt
if ($LASTEXITCODE -ne 0) { throw 'Projection independent replay failed' }
if ($eligible.Count) {
    Write-FollowupStatus 'projection_candidate_ready_for_assessment'
    exit 0
}

# No all-cohort candidate: run the predeclared graph-adaptation alternative.
Write-FollowupStatus 'training_joint_parent'
$controlPath = 'C:\OpenNR\Training\semantic_pretrained_arm400_20260908'
$controlRun = Get-Content (Join-Path $controlPath 'run.json') -Raw | ConvertFrom-Json
$jointRoot = 'C:\OpenNR\Training\semantic_joint_parent400_20260908'
$trainArgs = @('-3.12', 'tools\train_semantic_joint_parent.py', '--warm-head', $controlRun.warm_head,
    '--output', $jointRoot, '--control', $controlPath, '--steps', '400', '--eval-every', '400',
    '--seed', '367', '--learning-rate', '0.0001', '--parent-learning-rate', '0.00001')
for ($i=0; $i -lt $controlRun.cohorts.Count; $i++) {
    $trainArgs += @('--cohort', ($controlRun.cohort_labels[$i] + '=' + $controlRun.cohorts[$i]))
}
$trainArgs += @('--probabilities', '0.40', '0.15', '0.10', '0.15', '0.10', '0.10')
& py @trainArgs > out\semantic_joint_parent_stdout.txt 2> out\semantic_joint_parent_stderr.txt
if ($LASTEXITCODE -ne 0) { throw 'Joint-parent training failed' }
Write-FollowupStatus 'replaying_joint_parent'
& py -3.12 tools\verify_semantic_joint_parent.py --checkpoint (Join-Path $jointRoot 'last.pt') --output (Join-Path $jointRoot 'independent_replay') --render > out\semantic_joint_parent_replay_stdout.txt 2> out\semantic_joint_parent_replay_stderr.txt
if ($LASTEXITCODE -ne 0) { throw 'Joint-parent independent replay failed' }
Write-FollowupStatus 'joint_parent_ready_for_assessment'
