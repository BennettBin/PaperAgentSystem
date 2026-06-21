@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-paperagent.ps1"
if errorlevel 1 (
  echo.
  echo PaperAgentSystem startup failed. See the error above.
  pause
)
endlocal
