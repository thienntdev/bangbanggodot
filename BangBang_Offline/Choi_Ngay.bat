@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title BangBang - Choi ngay
if not exist "%~dp0runtime\python\python.exe" (
  echo Thieu Python portable. Hay giai nen DAY DU goi game, khong chi tai file BAT.
  pause
  exit /b 1
)
"%~dp0runtime\python\python.exe" -I -B -X utf8 "%~dp0server\portable_launcher.py" %*
set "BB_EXIT=%ERRORLEVEL%"
if not "%BB_EXIT%"=="0" (
  echo.
  echo Khong khoi dong duoc. Xem thong bao phia tren.
  pause
)
exit /b %BB_EXIT%
