@echo off
chcp 65001 >nul
title 达人沟通台
echo 正在启动本机模型和达人沟通台，请稍候...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if errorlevel 1 (
  echo.
  echo 启动失败，请把这个窗口的文字发给我。
  pause
) else (
  echo 启动成功，可以关闭这个窗口。
  timeout /t 2 >nul
)

