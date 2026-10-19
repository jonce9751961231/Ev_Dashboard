@echo off
title Aura EV Cockpit - 12V DC Motor Real-Time Predictive Host App
echo ===============================================================================
echo       AURA EV COCKPIT - 12V DC MOTOR PREDICTIVE AI SYSTEM (PORT 8000)
echo ===============================================================================
echo.
echo [1/2] Launching Python Host Server on http://localhost:8000 ...
echo [2/2] Opening Web Cockpit in your default browser...
start http://localhost:8000/
echo.
cd /d "%~dp0"
py -3.11 -m core_server.host_app || python -m core_server.host_app
pause
