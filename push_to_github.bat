@echo off
title Push Ev_Dashboard to GitHub
color 0b
echo ===============================================================================
echo          PUSH LOCAL EV DASHBOARD TO GITHUB REPOSITORY
echo          Target: https://github.com/jonce9751961231/Ev_Dashboard
echo ===============================================================================
echo.
echo Current branch: main
echo Remote origin : https://github.com/jonce9751961231/Ev_Dashboard.git
echo.
echo Attempting to push files to GitHub...
echo (If prompted, please sign in via browser or enter your GitHub Personal Access Token)
echo.
"C:\Users\ELCOT\AppData\Local\Programs\Git\cmd\git.exe" push -u origin main
echo.
if %ERRORLEVEL% EQU 0 (
    echo ===============================================================================
    echo [SUCCESS] Your repository has been pushed to GitHub successfully!
    echo View your code at: https://github.com/jonce9751961231/Ev_Dashboard
    echo ===============================================================================
) else (
    echo ===============================================================================
    echo [NOTE] If the remote repository already contains a README or commits on GitHub,
    echo run this command to force sync your latest code:
    echo   git push -u origin main --force
    echo ===============================================================================
)
echo.
pause
