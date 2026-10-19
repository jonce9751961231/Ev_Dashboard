@echo off
title Push Ev_Dashboard to GitHub
color 0b
echo ===============================================================================
echo          AUTOMATIC GITHUB AUTHENTICATION ^& REPOSITORY PUSH
echo          Target: https://github.com/jonce9751961231/Ev_Dashboard
echo ===============================================================================
echo.
cd /d "%~dp0"
echo [1/3] Authenticating with GitHub...
echo A one-time code will appear below and your browser will open.
echo Please confirm or paste the code in your browser to authorize.
echo.
where gh >nul 2>&1 && set "GH_CMD=gh" || set "GH_CMD=%LOCALAPPDATA%\Programs\gh\bin\gh.exe"
where git >nul 2>&1 && set "GIT_CMD=git" || set "GIT_CMD=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"

"%GH_CMD%" auth login --web -h github.com -p https
echo.
echo [2/3] Configuring Git Credentials...
"%GH_CMD%" auth setup-git
echo.
echo [3/3] Pushing all files to https://github.com/jonce9751961231/Ev_Dashboard...
"%GIT_CMD%" push -u origin main
echo.
if %ERRORLEVEL% EQU 0 (
    echo ===============================================================================
    echo [SUCCESS] Your repository has been pushed to GitHub successfully!
    echo Check your code at: https://github.com/jonce9751961231/Ev_Dashboard
    echo ===============================================================================
) else (
    echo ===============================================================================
    echo [ERROR] Push failed. If you have a Personal Access Token (PAT), run:
    echo   git push https://^<YOUR_TOKEN^>@github.com/jonce9751961231/Ev_Dashboard.git main
    echo ===============================================================================
)
echo.
pause
