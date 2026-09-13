$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-Location -LiteralPath 'D:\.CODEX_Projects\OpenNR-VR'
$phase = 'out/quality_phase_20260905'
$statePath = "$phase/face_vgg_combo_queue.json"
$run = "$phase/context_face_vgg_combo"
$evaluation = "$phase/context_face_vgg_combo_evaluation"
if (Test-Path -LiteralPath $statePath) { throw 'Combo queue already exists; inspect its state before retrying' }
if (Test-Path -LiteralPath $run) { throw 'Combo output already exists' }
if (Test-Path -LiteralPath $evaluation) { throw 'Combo evaluation output already exists' }
@{state='training';pid=$PID;run=$run;started=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $statePath
try {
    & E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/train_long_student.py --cache C:/OpenNR/TrainingCache/student_v1 --output $run --initialize "$phase/context_continuation/best_feature.pt" --dynamic-guides C:/OpenNR/TrainingCache/dynamic_guides_v1 --face-audit "$phase/face_audit_all/result.json" --workers 2 --steps 12000 --lr 0.00005 --eval-every 1000 --vgg-weight 0.05 > "$phase/context_face_vgg_combo.log" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Combo training exit code $LASTEXITCODE" }
    @{state='evaluating';pid=$PID} | ConvertTo-Json | Set-Content -LiteralPath $statePath
    & E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/evaluate_quality_run.py --cache C:/OpenNR/TrainingCache/student_v1 --run $run --baseline "$phase/context_continuation/best_feature.pt" --output $evaluation > "$phase/context_face_vgg_combo_evaluation.log" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Combo evaluation exit code $LASTEXITCODE" }
    @{state='completed';pid=$PID;run=$run;evaluation=$evaluation} | ConvertTo-Json | Set-Content -LiteralPath $statePath
}
catch {
    @{state='failed';pid=$PID;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $statePath
    throw
}
