@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-DLSSNRRuntime.ps1"
if errorlevel 1 (
  echo.
  echo Runtime setup did not complete. Read the error above.
)
pause
