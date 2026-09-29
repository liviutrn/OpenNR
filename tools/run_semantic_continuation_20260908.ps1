$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'C:\OpenNR\python312_ml_deps_20260908'
$statusPath = 'out\semantic_continuation_status.json'
function Write-ContinuationStatus([string]$state) {
    @{state=$state; updated=(Get-Date -Format o); test_used=$false} | ConvertTo-Json | Set-Content -LiteralPath $statusPath
}
trap { Write-ContinuationStatus ('failed: ' + $_.Exception.Message); throw }
$control = 'C:\OpenNR\Training\semantic_parent_seed812_control4000_20260908'
$joint = 'C:\OpenNR\Training\semantic_parent_seed812_joint4000_20260908'
Write-ContinuationStatus 'continuing_control'
& py -3.12 tools\continue_semantic_parent_training.py --resume C:\OpenNR\Training\semantic_parent_seed812_control1200_20260908\last.pt --output $control --steps 4000 --eval-every 800 > out\semantic_continue_control_stdout.txt 2> out\semantic_continue_control_stderr.txt
if ($LASTEXITCODE -ne 0) { throw 'Control continuation failed' }
Write-ContinuationStatus 'continuing_joint'
& py -3.12 tools\continue_semantic_parent_training.py --resume C:\OpenNR\Training\semantic_parent_seed812_joint1200_20260908\last.pt --output $joint --steps 4000 --eval-every 800 --control $control > out\semantic_continue_joint_stdout.txt 2> out\semantic_continue_joint_stderr.txt
if ($LASTEXITCODE -ne 0) { throw 'Joint continuation failed' }
Write-ContinuationStatus 'replaying_joint_endpoint'
& py -3.12 tools\verify_semantic_joint_parent.py --checkpoint (Join-Path $joint 'last.pt') --output (Join-Path $joint 'independent_replay') --render > out\semantic_continue_replay_stdout.txt 2> out\semantic_continue_replay_stderr.txt
if ($LASTEXITCODE -ne 0) { throw 'Joint endpoint replay failed' }
Write-ContinuationStatus 'ready_for_assessment'
