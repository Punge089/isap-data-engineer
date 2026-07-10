@echo off
REM Windows Task Scheduler entry point for the monthly CGD check (ข้อ 3b).
REM Second automation path alongside GitHub Actions -- see HANDOFF.md.
REM %~dp0 = this script's own directory (scripts\), so cd one level up to
REM the repo root regardless of Task Scheduler's default "Start in" folder.
cd /d "%~dp0.."
".venv\Scripts\python.exe" src\detect.py >> "logs\detect_log.txt" 2>&1
