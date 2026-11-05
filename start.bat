@echo off
chcp 65001 >nul
title 智巡 InspectAgent v8 - 配电房智能巡检后端

cd /d "%~dp0"

echo.
echo  ╔═══════════════════════════════════════════╗
echo  ║     智巡 InspectAgent · v8 后端服务         ║
echo  ║     配电房智能巡检系统                       ║
echo  ╚═══════════════════════════════════════════╝
echo.

REM 检查 venv
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 找不到 .venv\Scripts\python.exe
    echo 请确认完整解压本压缩包
    pause
    exit /b 1
)

REM 检查 .env
if not exist ".env" (
    echo [警告] 未找到 .env 配置文件
    echo 请把 .env.example 重命名为 .env 并填写 API KEY
    echo 当前将以 MOCK 模式启动...
    set MOCK_MODE=1
)

REM 端口 8000 是否已被占用
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
    echo [警告] 端口 8000 已被 PID %%a 占用，正在停止...
    taskkill /F /PID %%a >nul 2>&1
    timeout /t 2 /nobreak >nul
)

echo [启动] uvicorn 正在启动...
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info

echo.
echo 服务已停止
pause
