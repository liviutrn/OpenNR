$ErrorActionPreference = 'Stop'
$durationRun = 'E:/OpenNR_Training/stable_unet_joint_teacher_duration6000_20260907'
$durationPython = 'E:/OpenNR-VR-Poc-Venv/Scripts/python.exe'
$durationTools = $PSScriptRoot
$durationMidpoint = 'E:/OpenNR_Training/joint_teacher_duration_step3200_snapshot_20260907/checkpoint.pt'
$durationMidpointSHA = '529e5cc79f87edaa8fd028cb689a40b01059d4fa9e0b07068ea9264b40658c6c'
if ((Get-Content -LiteralPath "$durationRun/status.json" -Raw | ConvertFrom-Json).state -ne 'complete') {
    throw 'Duration training is not complete; no concurrent GPU diagnostics permitted.'
}
if ((Get-FileHash -LiteralPath $durationMidpoint -Algorithm SHA256).Hash.ToLowerInvariant() -ne $durationMidpointSHA) {
    throw 'Midpoint snapshot identity changed.'
}
& $durationPython "$durationTools/verify_spatial_tone.py" --run $durationRun --final-checkpoint
if ($LASTEXITCODE -ne 0) { throw 'Final replay failed.' }
& $durationPython "$durationTools/render_joint_teacher_snapshot.py" --checkpoint "$durationRun/last.pt" --output E:/OpenNR_Training/joint_teacher_duration_final_gallery_20260908
if ($LASTEXITCODE -ne 0) { throw 'Final gallery failed.' }
& $durationPython "$durationTools/render_joint_teacher_snapshot.py" --checkpoint $durationMidpoint --output E:/OpenNR_Training/joint_teacher_duration_midpoint_gallery_20260908
if ($LASTEXITCODE -ne 0) { throw 'Midpoint gallery failed.' }
& $durationPython "$durationTools/diagnose_joint_teacher_response.py" --run $durationRun --output E:/OpenNR_Training/joint_teacher_duration_final_response_20260908
if ($LASTEXITCODE -ne 0) { throw 'Final response diagnostic failed.' }
& $durationPython "$durationTools/diagnose_joint_teacher_response.py" --run $durationRun --snapshot $durationMidpoint --expected-snapshot-sha256 $durationMidpointSHA --expected-snapshot-step 3200 --output E:/OpenNR_Training/joint_teacher_duration_midpoint_response_20260908
if ($LASTEXITCODE -ne 0) { throw 'Midpoint response diagnostic failed.' }
& $durationPython "$durationTools/evaluate_retention_training_fit.py" --run $durationRun --tone-head --final-checkpoint --output E:/OpenNR_Training/joint_teacher_duration_final_training_fit_20260908
if ($LASTEXITCODE -ne 0) { throw 'Final full training-fit failed.' }
