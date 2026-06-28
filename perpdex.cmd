@echo off
set "PY=C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
"%PY%" -m perpdex_bot %*
