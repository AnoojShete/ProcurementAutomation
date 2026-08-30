@echo off
REM Double-clickable entry point for Windows — hands off to run.ps1, which
REM re-execs run.sh inside WSL2. See run.ps1 for why.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
