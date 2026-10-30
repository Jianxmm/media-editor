@echo off
setlocal
for /f "tokens=2 delims=:" %%C in ('chcp') do set "ME_OLD_CP=%%C"
chcp 65001 >nul
set "ME_ROOT=%~dp0"
set "ME_PYTHON=%ME_ROOT%runtime\python\python.exe"
if not exist "%ME_PYTHON%" if exist "%ME_ROOT%.runtime-path" set /p ME_RUNTIME=<"%ME_ROOT%.runtime-path"
if defined ME_RUNTIME set "ME_PYTHON=%ME_RUNTIME%\runtime\python\python.exe"
if not exist "%ME_PYTHON%" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "& ([scriptblock]::Create([IO.File]::ReadAllText((Join-Path $env:ME_ROOT 'setup.ps1')))) -SkillRoot $env:ME_ROOT" 1>&2
  if errorlevel 1 goto failed
)
if not exist "%ME_PYTHON%" set /p ME_RUNTIME=<"%ME_ROOT%.runtime-path"
if defined ME_RUNTIME set "ME_PYTHON=%ME_RUNTIME%\runtime\python\python.exe"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
"%ME_PYTHON%" -B "%ME_ROOT%scripts\bundle_launcher.py" %*
set "ME_EXIT=%errorlevel%"
goto done
:failed
set "ME_EXIT=1"
:done
if defined ME_OLD_CP chcp %ME_OLD_CP% >nul
exit /b %ME_EXIT%
