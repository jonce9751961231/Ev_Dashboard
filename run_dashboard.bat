@echo off
title EV Dashboard - 48V-96V BLDC Motor Predictive AI & ESP CSV System
echo ===============================================================================
echo     AURA EV DASHBOARD - 48V-96V BLDC MOTOR PREDICTIVE AI & ESP CSV SYSTEM
echo ===============================================================================
echo.
echo [1/2] Opening Interactive EV Digital Cockpit in default browser...
start "" "%~dp0dashboard_ui\index.html"
echo.
echo [2/2] Attempting to launch Python Telemetry Server (Port 8000 if Python installed)...
py -m core_server.server || python -m core_server.server
echo.
echo Note: If Python is not installed, the EV Dashboard works 100%% client-side in the browser!
echo You can upload ESP CSV files and run AI temperature predictions directly.
echo.
pause
