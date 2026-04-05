@echo off
title Portable AI - One-Click Setup
color 0E

echo ===================================================
echo     PORTABLE AI USB - WINDOWS SETUP                
echo ===================================================
echo.
echo This will download everything you need onto this
echo USB drive. Total download size is roughly 12+ GB.
echo.
echo Make sure you have a good internet connection!
echo.
pause

:: Run the PowerShell setup script from the same folder as this bat file
powershell -ExecutionPolicy Bypass -File "%~dp0install-core.ps1"

echo.
echo ===================================================
echo     SETUP COMPLETE! You're ready to go!            
echo ===================================================
echo.
echo To start your AI, double-click start-windows.bat
echo.
pause
