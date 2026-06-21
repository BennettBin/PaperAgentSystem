@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-paperagent.ps1"
if errorlevel 1 (
  echo.
  echo PaperAgentSystem shutdown failed. See the error above.
  pause
)
endlocal
