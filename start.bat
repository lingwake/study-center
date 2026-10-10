@echo off
chcp 65001 >nul
title 学习中心 - 服务
cd /d "%~dp0"

echo ============================================
echo   学习中心 正在启动...
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有检测到 Python
    echo 请先安装: https://www.python.org/downloads/
    echo 安装时记得勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

python server.py --port 8000

echo.
echo 服务已停止
pause
