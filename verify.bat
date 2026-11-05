@echo off
chcp 65001 >nul
title InspectAgent v8 · 一键验证

echo.
echo === 正在启动（后台） ===
start /min "" "start.bat"

echo.
echo === 等待服务就绪 ===
timeout /t 8 /nobreak >nul

echo.
echo === 健康检查 ===
curl -s http://127.0.0.1:8000/health
echo.

echo.
echo === 登录 inspector ===
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"inspector\",\"password\":\"inspector123\"}"
echo.

echo.
echo === 任务列表 ===
curl -s http://127.0.0.1:8000/api/v1/tasks?page=1^&pageSize=3 ^
  -H "Authorization: Bearer TEST_TOKEN" 2>nul || echo "（需先登录拿 token，略）"
echo.

echo.
echo === 同步快照（admin） ===
set /p ADMIN_TOKEN=请用上面登录结果里的 accessToken 粘贴（回车跳过）: 
if not "%ADMIN_TOKEN%"=="" (
    curl -s http://127.0.0.1:8000/api/v1/sync/snapshot ^
      -H "Authorization: Bearer %ADMIN_TOKEN%"
)
echo.

echo.
echo === 所有验证完成 ===
echo 服务已在后台运行，访问：
echo   API 基址  : http://localhost:8000
echo   Swagger   : http://localhost:8000/docs
echo   测试台    : http://localhost:8000/
echo.
pause
