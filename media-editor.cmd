@echo off
setlocal
set "ME_ROOT=%~dp0"
set "ME_PYTHON=%ME_ROOT%runtime\python\python.exe"
if not exist "%ME_PYTHON%" (
  echo Please download the Windows x64 offline bundle with its runtime.
  exit /b 1
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
"%ME_PYTHON%" -B "%ME_ROOT%scripts\bundle_launcher.py" %*
exit /b %errorlevel%
