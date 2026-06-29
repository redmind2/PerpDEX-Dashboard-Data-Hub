@echo off
set "PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
"%PY%" -m perpdex_bot %*
