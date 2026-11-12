@echo off
rem Monthly update of the Philadelphia Community Outreach Planner.
rem Double-click this file once a month. It downloads the newest public data, rebuilds the
rem demographic model when needed, checks everything and publishes the site (GitHub Pages).
rem It takes about 1-1.5 hours; leave the window open. See README.md, "Monthly update".
cd /d "%~dp0"
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
"%PY%" scripts\update_data.py --push
echo.
pause
