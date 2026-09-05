@echo off
cd /d "%~dp0"
title Consiz

net session >nul 2>&1
if %errorlevel% equ 0 goto :is_admin

echo Requesting Administrator privileges...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -WorkingDirectory ('%~dp0'.TrimEnd('\')) -ArgumentList '/k python main.py' -Verb RunAs"
exit /b

:is_admin
echo Running with Administrator privileges.
python main.py
pause
