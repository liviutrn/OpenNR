param([int]$TrainingProcessId = 6192, [int]$CheckpointStep = 4000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\.CODEX_Projects\OpenNR-VR'
$sourceDirectory = 'out/quality_phase_20260905/dynamic_continuation'
$destinationDirectory = 'out/quality_phase_20260905/dynamic_prefetch_continuation'
$handoffPath = 'out/quality_phase_20260905/dynamic_prefetch_handoff.json'
if (Test-Path -LiteralPath "$destinationDirectory/run.json") { throw 'Prefetch continuation already exists' }
$smoke = Get-Content -Raw -LiteralPath 'out/quality_phase_20260905/dynamic_prefetch_smoke/status.json' | ConvertFrom-Json
if ($smoke.state -ne 'completed' -or $smoke.step -ne 10) { throw 'Prefetch CUDA smoke did not pass' }
$oldProcess = Get-Process -Id $TrainingProcessId -ErrorAction Stop
$null = $oldProcess.Handle
$oldQueue = Get-Process -Id 8740 -ErrorAction SilentlyContinue
@{ state='waiting_for_saved_checkpoint'; process_id=$TrainingProcessId; target_step=$CheckpointStep; coordinator_pid=$PID; reason='Enable validated asynchronous crop prefetch; preserve optimizer, RNG and sampling order' } | ConvertTo-Json | Set-Content -LiteralPath $handoffPath
while ($true) {
    if ($oldProcess.HasExited) { throw 'Training exited before controlled handoff; inspect original run' }
    $record = $null
    try { $record = Get-Content -LiteralPath "$sourceDirectory/history.jsonl" -Tail 1 | ConvertFrom-Json } catch { }
    if ($record -and $record.step -ge $CheckpointStep) { break }
    Start-Sleep -Milliseconds 500
}
# History is written only after all checkpoint files have been atomically saved.
Stop-Process -InputObject $oldProcess
Wait-Process -InputObject $oldProcess -ErrorAction SilentlyContinue
if ($oldQueue) { Wait-Process -InputObject $oldQueue -ErrorAction SilentlyContinue }
$priorState = Get-Content -Raw -LiteralPath "$sourceDirectory/status.json" | ConvertFrom-Json
$priorState.state = 'interrupted_for_prefetch'
$priorState | ConvertTo-Json | Set-Content -LiteralPath "$sourceDirectory/status.json"
@{ state='superseded_by_prefetch_continuation'; checkpoint_step=$record.step; destination=$destinationDirectory } | ConvertTo-Json | Set-Content -LiteralPath 'out/quality_phase_20260905/dynamic_queue.json'
New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
foreach ($name in @('best_mae.pt','best_feature.pt')) { Copy-Item -LiteralPath "$sourceDirectory/$name" -Destination "$destinationDirectory/$name" }
@{ state='resuming'; checkpoint_step=$record.step; source="$sourceDirectory/last.pt"; destination=$destinationDirectory; coordinator_pid=$PID } | ConvertTo-Json | Set-Content -LiteralPath $handoffPath
& 'E:\OpenNR-VR-Poc-Venv\Scripts\python.exe' tools/train_long_student.py --cache C:/OpenNR/TrainingCache/student_v1 --output $destinationDirectory --resume "$sourceDirectory/last.pt" --dynamic-guides C:/OpenNR/TrainingCache/dynamic_guides_v1 --workers 2 --steps 20000 --eval-every 1000 *> out/quality_dynamic_prefetch_continuation.log
if ($LASTEXITCODE -ne 0) {
    @{ state='failed'; destination=$destinationDirectory; exit_code=$LASTEXITCODE } | ConvertTo-Json | Set-Content -LiteralPath $handoffPath
    throw 'Resumed training failed; original checkpoint remains preserved'
}
@{ state='completed'; destination=$destinationDirectory } | ConvertTo-Json | Set-Content -LiteralPath $handoffPath
