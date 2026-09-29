@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-DLSSNRRuntime.ps1" -RuntimeMode RTX40-Ada -AllowAdaPatchedRuntime
if errorlevel 1 (
  echo.
  echo RTX 40 Ada runtime setup did not complete. Read the error above.
)
pause
