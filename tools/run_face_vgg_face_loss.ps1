$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-Location -LiteralPath 'D:\.CODEX_Projects\OpenNR-VR'
$phase = 'out/quality_phase_20260905'
$statePath = "$phase/face_vgg_face_loss_queue.json"
$run = "$phase/context_face_vgg_face_loss"
$evaluation = "$phase/context_face_vgg_face_loss_evaluation"
$faceEvaluation = "$phase/context_face_vgg_face_loss_face_evaluation"
$baseline = "$phase/context_continuation/best_feature.pt"
if (Test-Path -LiteralPath $statePath) { throw 'Face/VGG/face-loss queue already exists; inspect its state before retrying' }
foreach ($path in @($run,$evaluation,$faceEvaluation)) {
    if (Test-Path -LiteralPath $path) { throw "Output already exists: $path" }
}
@{state='training';pid=$PID;run=$run;started=(Get-Date).ToString('o');vgg_weight=0.05;face_loss_weight=0.75} | ConvertTo-Json | Set-Content -LiteralPath $statePath
try {
    & E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/train_long_student.py --cache C:/OpenNR/TrainingCache/student_v1 --output $run --initialize $baseline --dynamic-guides C:/OpenNR/TrainingCache/dynamic_guides_v1 --face-audit "$phase/face_audit_all/result.json" --workers 2 --steps 12000 --lr 0.00005 --eval-every 1000 --vgg-weight 0.05 --face-loss-weight 0.75 > "$phase/context_face_vgg_face_loss.log" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Face/VGG/face-loss training exit code $LASTEXITCODE" }
    @{state='evaluating_quality';pid=$PID;run=$run} | ConvertTo-Json | Set-Content -LiteralPath $statePath
    & E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/evaluate_quality_run.py --cache C:/OpenNR/TrainingCache/student_v1 --run $run --baseline $baseline --output $evaluation > "$phase/context_face_vgg_face_loss_evaluation.log" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Quality evaluation exit code $LASTEXITCODE" }
    @{state='evaluating_faces';pid=$PID;run=$run;evaluation=$evaluation} | ConvertTo-Json | Set-Content -LiteralPath $statePath
    & E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/evaluate_face_regions.py --cache C:/OpenNR/TrainingCache/student_v1 --faces "$phase/face_audit_validation/result.json" --output $faceEvaluation --models $baseline "$run/best_mae.pt" "$run/best_feature.pt" > "$phase/context_face_vgg_face_loss_face_evaluation.log" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Face-region evaluation exit code $LASTEXITCODE" }
    & E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/export_quality_candidate.py --checkpoint "$run/best_mae.pt" --output "$phase/OpenNR_ContextFaceVGGFaceLoss_v4_best_mae.pt" > "$phase/context_face_vgg_face_loss_export_mae.log" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "MAE export exit code $LASTEXITCODE" }
    & E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/export_quality_candidate.py --checkpoint "$run/best_feature.pt" --output "$phase/OpenNR_ContextFaceVGGFaceLoss_v4_best_feature.pt" > "$phase/context_face_vgg_face_loss_export_feature.log" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Feature export exit code $LASTEXITCODE" }
    @{state='completed';pid=$PID;run=$run;evaluation=$evaluation;face_evaluation=$faceEvaluation} | ConvertTo-Json | Set-Content -LiteralPath $statePath
}
catch {
    @{state='failed';pid=$PID;run=$run;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $statePath
    throw
}
