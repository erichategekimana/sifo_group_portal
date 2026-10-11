@echo off
REM sifo_portal.bat
REM Self-elevating 1-click launcher for SIFO Group Portal

:: Check for Administrator privileges
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Requesting Administrator privileges...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

:: Run sifo_portal.ps1 with Administrator privileges
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0sifo_portal.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo An error occurred running SIFO Portal launcher.
    pause
)

