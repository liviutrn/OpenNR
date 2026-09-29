param([int]$AppearanceControllerId = 19252)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\.CODEX_Projects\OpenNR-VR'
$phase = 'out/quality_phase_20260905'
$queuePath = "$phase/face_queue.json"
if (Test-Path -LiteralPath $queuePath) { throw 'Face queue already exists; inspect original process before resuming' }
$controller = Get-Process -Id $AppearanceControllerId -ErrorAction Stop
$null = $controller.Handle
@{state='waiting_for_appearance';pid=$PID;controller_pid=$AppearanceControllerId;controller_start=$controller.StartTime.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $queuePath
Wait-Process -InputObject $controller
$state = Get-Content -Raw -LiteralPath "$phase/appearance_pair_status.json" | ConvertFrom-Json
if ($state.state -ne 'completed' -or -not (Test-Path -LiteralPath "$phase/context_fresh_vgg_evaluation/complete.json")) { throw 'Appearance pair failed or did not finish evaluation' }
$smoke = Get-Content -Raw -LiteralPath "$phase/face_sampler_smoke/status.json" | ConvertFrom-Json
$test = Get-Content -Raw -LiteralPath "$phase/face_sampler_validation.json" | ConvertFrom-Json
if ($smoke.state -ne 'completed' -or $test.state -ne 'passed') { throw 'Face sampler validation missing' }
@{state='training';pid=$PID} | ConvertTo-Json | Set-Content -LiteralPath $queuePath
& E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/train_long_student.py --cache C:/OpenNR/TrainingCache/student_v1 --output "$phase/context_face_control" --initialize "$phase/context_continuation/best_feature.pt" --dynamic-guides C:/OpenNR/TrainingCache/dynamic_guides_v1 --face-audit "$phase/face_audit_all/result.json" --workers 2 --steps 12000 --lr 0.00005 --eval-every 1000 *> "$phase/context_face_control.log"
if ($LASTEXITCODE -ne 0) { @{state='failed';stage='training';pid=$PID} | ConvertTo-Json | Set-Content -LiteralPath $queuePath; throw 'Face training failed' }
@{state='evaluating';pid=$PID} | ConvertTo-Json | Set-Content -LiteralPath $queuePath
& E:/OpenNR-VR-Poc-Venv/Scripts/python.exe tools/evaluate_quality_run.py --cache C:/OpenNR/TrainingCache/student_v1 --run "$phase/context_face_control" --baseline "$phase/context_fresh_control/best_mae.pt" --output "$phase/context_face_control_evaluation" *> "$phase/context_face_control_evaluation.log"
if ($LASTEXITCODE -ne 0) { @{state='failed';stage='evaluation';pid=$PID} | ConvertTo-Json | Set-Content -LiteralPath $queuePath; throw 'Face evaluation failed' }
@{state='completed';pid=$PID} | ConvertTo-Json | Set-Content -LiteralPath $queuePath
