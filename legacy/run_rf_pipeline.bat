@echo off
title Aura EV Cockpit - 48V BLDC Random Forest Thermal Prediction Pipeline
color 0b
echo ===============================================================================
echo     AURA EV DASHBOARD - 48V BLDC RANDOM FOREST THERMAL PREDICTION SYSTEM
echo ===============================================================================
echo.
echo [1/3] Launching Aura EV Digital Cockpit in your default web browser...
start "" "%~dp0dashboard_ui\index.html"
echo       - Cockpit URL: file:///%~dp0dashboard_ui/index.html
echo.
echo [2/3] Checking for Python installation for Real-Time Streaming Server...
py --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo       - Python detected! Launching Real-Time WebSocket Server on Port 8765...
    start "Aura EV Random Forest Server" cmd /k "cd /d %~dp0 && py -m core_server.rf_continuous_server"
    goto finish
)

python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo       - Python detected! Launching Real-Time WebSocket Server on Port 8765...
    start "Aura EV Random Forest Server" cmd /k "cd /d %~dp0 && python -m core_server.rf_continuous_server"
    goto finish
)

echo       - Note: Local Python executable was not detected on system PATH.
echo       - NO WORRIES! The EV Cockpit runs the 100-Tree Random Forest Model
echo         100%% CLIENT-SIDE inside your web browser (using rf_model_weights.json)!
echo.
echo [3/3] Google Colab Training Notebook:
echo       - Standalone Notebook: %~dp0google_colab\EV_48V_Random_Forest_Thermal_Prediction.ipynb
echo       - Simply upload this .ipynb file to https://colab.research.google.com/ to train online.
echo.

:finish
echo ===============================================================================
echo  Dashboard is now live! You can inspect live 48V BLDC telemetry, view multi-horizon
echo  Random Forest forecasts (+1m, +5m, +15m, +30m), and analyze Feature Importances.
echo ===============================================================================
echo.
pause
