@echo off
setlocal
cd /d "%~dp0"
title Consiz — Desktop AI Assistant

echo ========================================================
echo               Starting Consiz (Windows)
echo ========================================================

:: 1. Check Python installation
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python was not found in your PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    echo and ensure 'Add Python to PATH' is checked.
    echo.
    pause
    exit /b 1
)

:: 2. Check for .env file
if not exist ".env" (
    if exist ".env.example" (
        echo [INFO] Creating .env file from .env.example...
        copy ".env.example" ".env" >nul
        echo [NOTICE] Please edit .env to insert your OpenRouter API key.
    )
)

:: 3. Run Consiz
echo [INFO] Launching Consiz background listener...
echo        - Middle-click anywhere on screen to explain selection
echo        - Or press Ctrl+Alt+S
echo        - Right-click the system tray icon for settings and languages
echo.
python main.py %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [NOTICE] Consiz exited with code %ERRORLEVEL%.
    pause
)
