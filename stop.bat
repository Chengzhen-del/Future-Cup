@echo off
chcp 65001 >nul
title 停掉 InspectAgent v8

echo 正在停止 InspectAgent 后端...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
    echo 已终止 PID %%a
)
echo 完成
timeout /t 2 /nobreak >nul
