@echo off
chcp 65001 >nul 2>&1
title 志愿Agent 启动器

echo ========================================
echo   志愿Agent — 高考志愿填报 AI 助手
echo ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 Add Python to PATH
    echo.
    pause
    exit /b 1
)

:: Check virtual environment
if not exist ".venv\Scripts\python.exe" (
    echo [提示] 正在创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
)

:: Install dependencies
echo [提示] 检查依赖...
.venv\Scripts\pip install -q openpyxl >nul 2>&1

:: Check frontend file
if not exist "frontend\index.html" (
    echo [错误] 未找到 frontend\index.html，请确认脚本位于项目目录
    pause
    exit /b 1
)

:: Check database (auto-copied from kb/ on first start)
set DB_FOUND=0
if exist "data\gaokao_data.db" set DB_FOUND=1
if exist "kb\07_录取数据\gaokao_data.db" set DB_FOUND=1
if %DB_FOUND%==0 (
    echo [警告] 未找到数据库文件，首次启动时将从知识仓库自动加载
)

echo.
echo [启动] 服务器启动中...
echo [地址] http://127.0.0.1:8765
echo.

.venv\Scripts\python.exe run.py