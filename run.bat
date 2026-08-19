@echo off
cd /d "%~dp0"
if not exist ".python-runtime\python.exe" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_pyside6.ps1"
  if errorlevel 1 goto :failed
)
"%~dp0.python-runtime\python.exe" "%~dp0src\app.py"
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo 启动失败，请查看上方错误信息。
pause
