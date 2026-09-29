# One-off paired replication for the active training goal.
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'C:\OpenNR\python312_ml_deps_20260908'
$statusPath = 'out\semantic_replication_status.json'
function Write-ReplicationStatus([string]$state) {
    @{state=$state; updated=(Get-Date -Format o); test_used=$false} |
        ConvertTo-Json | Set-Content -LiteralPath $statusPath
}
trap {
    Write-ReplicationStatus ('failed: ' + $_.Exception.Message)
    throw
}
$priorRun = Get-Content C:\OpenNR\Training\semantic_joint_parent400_20260908\run.json -Raw | ConvertFrom-Json
$controlRoot = 'C:\OpenNR\Training\semantic_parent_seed812_control1200_20260908'
$jointRoot = 'C:\OpenNR\Training\semantic_parent_seed812_joint1200_20260908'
$commonArgs = @('-3.12', 'tools\train_semantic_parent_replication.py', '--warm-head', $priorRun.warm_head,
    '--steps', '1200', '--eval-every', '400', '--seed', '812', '--learning-rate', '0.0001',
    '--parent-learning-rate', '0.00001')
for ($i=0; $i -lt $priorRun.cohorts.Count; $i++) {
    $commonArgs += @('--cohort', ($priorRun.cohort_labels[$i] + '=' + $priorRun.cohorts[$i]))
}
$commonArgs += @('--probabilities', '0.40', '0.15', '0.10', '0.15', '0.10', '0.10')
Write-ReplicationStatus 'training_control'
$controlArgs = $commonArgs + @('--output', $controlRoot, '--freeze-parent')
& py @controlArgs > out\semantic_seed812_control_stdout.txt 2> out\semantic_seed812_control_stderr.txt
if ($LASTEXITCODE -ne 0) { throw 'Replication control failed' }
Write-ReplicationStatus 'training_joint'
$jointArgs = $commonArgs + @('--output', $jointRoot, '--control', $controlRoot)
& py @jointArgs > out\semantic_seed812_joint_stdout.txt 2> out\semantic_seed812_joint_stderr.txt
if ($LASTEXITCODE -ne 0) { throw 'Replication joint arm failed' }
Write-ReplicationStatus 'replaying_joint_endpoint'
& py -3.12 tools\verify_semantic_joint_parent.py --checkpoint (Join-Path $jointRoot 'last.pt') --output (Join-Path $jointRoot 'independent_replay') --render > out\semantic_seed812_replay_stdout.txt 2> out\semantic_seed812_replay_stderr.txt
if ($LASTEXITCODE -ne 0) { throw 'Replication endpoint replay failed' }
Write-ReplicationStatus 'ready_for_assessment'
