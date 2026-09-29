@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-DLSSNRRuntime.ps1" -RuntimeMode Universal-SM75-SM86-SM89-SM120 -AllowAdaPatchedRuntime
if errorlevel 1 (
  echo.
  echo Universal multi-GPU runtime setup did not complete. Read the error above.
)
pause
