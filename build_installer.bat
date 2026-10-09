@echo off
setlocal
echo ===================================================
echo     Consiz - Windows Standalone Installer Builder
echo ===================================================

python build_installer.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Build failed with error code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [+] Done! Setup installer generated in 'dist\ConsizSetup.exe'.
pause
