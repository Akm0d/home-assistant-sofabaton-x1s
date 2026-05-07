@echo off
setlocal

set "REPO_ROOT=%~dp0.."
set "PYTHON="

if exist "%REPO_ROOT%\.venv-py313\Scripts\python.exe" set "PYTHON=%REPO_ROOT%\.venv-py313\Scripts\python.exe"
if not defined PYTHON if exist "%REPO_ROOT%\.venv-py313-smoke\Scripts\python.exe" set "PYTHON=%REPO_ROOT%\.venv-py313-smoke\Scripts\python.exe"
if not defined PYTHON if exist "%REPO_ROOT%\.venv\Scripts\python.exe" set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"

if not defined PYTHON (
  echo No project Python found. 1>&2
  exit /b 1
)

"%PYTHON%" -m pytest %*
exit /b %ERRORLEVEL%
