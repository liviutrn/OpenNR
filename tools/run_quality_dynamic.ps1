param([int]$ContextProcessId = 6984)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\.CODEX_Projects\OpenNR-VR'
$statePath = 'out/quality_phase_20260905/dynamic_queue.json'
$runStatus = Get-Content -Raw -LiteralPath 'out/quality_phase_20260905/context_continuation/status.json' | ConvertFrom-Json
if ($runStatus.pid -ne $ContextProcessId) { throw 'Context process identity mismatch' }
if ($runStatus.state -ne 'completed') {
    $contextProcess = Get-Process -Id $ContextProcessId -ErrorAction Stop
    $null = $contextProcess.Handle
    @{ state='waiting_for_context'; context_pid=$ContextProcessId; context_start=$contextProcess.StartTime.ToString('o'); queue_pid=$PID } | ConvertTo-Json | Set-Content -LiteralPath $statePath
    Wait-Process -InputObject $contextProcess
}
$runStatus = Get-Content -Raw -LiteralPath 'out/quality_phase_20260905/context_continuation/status.json' | ConvertFrom-Json
if ($runStatus.state -ne 'completed' -or $runStatus.step -ne 20000) { throw 'Context experiment did not complete successfully' }
$smokeStatus = Get-Content -Raw -LiteralPath 'out/quality_phase_20260905/dynamic_smoke/status.json' | ConvertFrom-Json
$dataTest = Get-Content -Raw -LiteralPath 'out/dynamic_patch_validation.json' | ConvertFrom-Json
if ($smokeStatus.state -ne 'completed' -or $dataTest.state -ne 'passed') { throw 'Dynamic loader checks did not pass' }
@{ state='starting_dynamic'; queue_pid=$PID; steps=20000; initialization='out/student_v2_20260904/perceptual/best.pt' } | ConvertTo-Json | Set-Content -LiteralPath $statePath
& 'E:\OpenNR-VR-Poc-Venv\Scripts\python.exe' tools/train_long_student.py --cache C:/OpenNR/TrainingCache/student_v1 --output out/quality_phase_20260905/dynamic_continuation --initialize out/student_v2_20260904/perceptual/best.pt --dynamic-guides C:/OpenNR/TrainingCache/dynamic_guides_v1 --steps 20000 --eval-every 1000 *> out/quality_dynamic_continuation.log
if ($LASTEXITCODE -ne 0) {
    @{ state='failed'; queue_pid=$PID; exit_code=$LASTEXITCODE } | ConvertTo-Json | Set-Content -LiteralPath $statePath
    throw 'Dynamic-crop experiment failed; inspect its log'
}
@{ state='completed'; queue_pid=$PID } | ConvertTo-Json | Set-Content -LiteralPath $statePath
