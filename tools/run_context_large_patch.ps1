$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-Location -LiteralPath 'D:\.CODEX_Projects\OpenNR-VR'

$phase = 'out/quality_phase_20260905'
$statePath = "$phase/context_large_patch_queue.json"
$run = "$phase/context_face_vgg_face_loss_1024"
$evaluation = "$phase/context_face_vgg_face_loss_1024_evaluation"
$baseline = "$phase/OpenNR_ContextFaceVGGFaceLoss_v4_best_mae.pt"
$log = "$phase/context_face_vgg_face_loss_1024.log"

if (Test-Path -LiteralPath $statePath) { throw 'Large-patch queue already exists; inspect its state before retrying' }
foreach ($path in @($run,$evaluation)) {
    if (Test-Path -LiteralPath $path) { throw "Output already exists: $path" }
}
if (-not (Test-Path -LiteralPath $baseline)) { throw "Baseline checkpoint missing: $baseline" }

@{state='training';pid=$PID;run=$run;baseline=$baseline;patch_size=1024;batch=1;started=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $statePath
try {
    & E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/train_long_student.py `
        --cache C:/OpenNR/TrainingCache/student_v1 `
        --output $run `
        --initialize $baseline `
        --dynamic-guides C:/OpenNR/TrainingCache/dynamic_guides_v1 `
        --face-audit "$phase/face_audit_all/result.json" `
        --workers 2 `
        --patch-size 1024 `
        --batch 1 `
        --steps 4000 `
        --lr 0.00002 `
        --eval-every 500 `
        --vgg-weight 0.05 `
        --face-loss-weight 0.75 > $log 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Large-patch training exit code $LASTEXITCODE" }
    @{state='evaluating';pid=$PID;run=$run;baseline=$baseline} | ConvertTo-Json | Set-Content -LiteralPath $statePath
    & E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/evaluate_quality_run.py `
        --cache C:/OpenNR/TrainingCache/student_v1 `
        --run $run `
        --baseline $baseline `
        --output $evaluation >> $log 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Large-patch quality evaluation exit code $LASTEXITCODE" }
    @{state='completed';pid=$PID;run=$run;baseline=$baseline;evaluation=$evaluation} | ConvertTo-Json | Set-Content -LiteralPath $statePath
}
catch {
    @{state='failed';pid=$PID;run=$run;baseline=$baseline;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $statePath
    throw
}
