@echo off
REM Windows Task Scheduler entry point for the monthly CGD check (ข้อ 3b/3c).
REM Second automation path alongside GitHub Actions -- runs the same full
REM detect->download->extract->clean->load chain, see HANDOFF.md.
REM %~dp0 = this script's own directory (scripts\), so cd one level up to
REM the repo root regardless of Task Scheduler's default "Start in" folder.
cd /d "%~dp0.."
".venv\Scripts\python.exe" src\run_monthly_pipeline.py >> "logs\detect_log.txt" 2>&1
