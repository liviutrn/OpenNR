param([int]$ControlProcessId = 12012)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\.CODEX_Projects\OpenNR-VR'
$controlDirectory = 'out/quality_phase_20260905/detail_continuation'
$statePath = 'out/quality_phase_20260905/context_queue.json'
$controlStatus = Get-Content -Raw -LiteralPath "$controlDirectory/status.json" | ConvertFrom-Json
if ($controlStatus.pid -ne $ControlProcessId) { throw 'Control process identity differs from requested run' }
if ($controlStatus.state -ne 'completed') {
    # Pin the live process object; waiting is not based on a stale status file.
    $controlProcess = Get-Process -Id $ControlProcessId -ErrorAction Stop
    $null = $controlProcess.Handle
    @{ state='waiting_for_control'; control_pid=$ControlProcessId; control_start=$controlProcess.StartTime.ToString('o'); queue_pid=$PID } | ConvertTo-Json | Set-Content -LiteralPath $statePath
    Wait-Process -InputObject $controlProcess
}
$controlStatus = Get-Content -Raw -LiteralPath "$controlDirectory/status.json" | ConvertFrom-Json
if ($controlStatus.state -ne 'completed' -or $controlStatus.step -ne 20000) { throw 'Control run did not complete successfully; context experiment not started' }
@{ state='starting_context'; queue_pid=$PID; matched_initialization='out/student_v2_20260904/perceptual/best.pt'; steps=20000 } | ConvertTo-Json | Set-Content -LiteralPath $statePath
& 'E:\OpenNR-VR-Poc-Venv\Scripts\python.exe' tools/train_long_student.py --cache C:/OpenNR/TrainingCache/student_v1 --output out/quality_phase_20260905/context_continuation --initialize out/student_v2_20260904/perceptual/best.pt --upgrade-context --steps 20000 --eval-every 1000 *> out/quality_context_continuation.log
if ($LASTEXITCODE -ne 0) {
    @{ state='failed'; queue_pid=$PID; exit_code=$LASTEXITCODE } | ConvertTo-Json | Set-Content -LiteralPath $statePath
    throw 'Context experiment failed; inspect its log'
}
@{ state='completed'; queue_pid=$PID } | ConvertTo-Json | Set-Content -LiteralPath $statePath
