@echo off
title Aura EV - Host Application Server (Port 8000)
color 0a
echo ===============================================================================
echo       AURA EV COCKPIT - UNIFIED HOST APPLICATION SERVER (PORT 8000)
echo ===============================================================================
echo.
echo [1/2] Opening Web Cockpit in your default browser...
start http://localhost:8000/
echo.
echo [2/2] Launching FastAPI + WebSocket + Random Forest Host Server...
echo       - Web Dashboard  : http://localhost:8000/
echo       - Telemetry WS   : ws://localhost:8000/ws/telemetry
echo       - API Health     : http://localhost:8000/api/health
echo       - Model          : Random Forest Regressor (100 Trees)
echo.
echo Press Ctrl+C at any time to stop the server.
echo ===============================================================================
echo.
py -3.11 -m core_server.host_app
pause
