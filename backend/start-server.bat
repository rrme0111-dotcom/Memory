@echo off
chcp 65001 >nul
title MemoryVortex · Backend Server
cd /d "%~dp0"

echo ============================================
echo   记忆漩涡 MemoryVortex · 后端服务
echo ============================================
echo.

rem ---- 若服务已在运行，直接打开页面 ----
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>nul
if %errorlevel% equ 0 (
    echo [提示] 服务已在运行，直接打开页面...
    start "" http://127.0.0.1:8000/memory-vortex-prototype-v2-api.html
    timeout /t 2 /nobreak >nul
    exit /b 0
)

rem ---- 探测可用的 Python（py 启动器 → 系统 python）----
set "PY="
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 -c "print('ok')" >nul 2>nul
    if %errorlevel% equ 0 set "PY=py -3"
)
if not defined PY (
    python -c "print('ok')" >nul 2>nul
    if %errorlevel% equ 0 set "PY=python"
)

if not defined PY (
    echo [错误] 未找到可用的 Python，请先安装 Python 3.10+
    echo        下载地址: https://www.python.org/downloads/
    echo        安装时务必勾选 "Add python.exe to PATH"
    pause
    exit /b 1
)

echo [OK] 使用 Python: %PY%
echo.

rem ---- 检查依赖，缺失则自动安装 ----
%PY% -c "import fastapi, uvicorn, httpx" >nul 2>nul
if %errorlevel% neq 0 (
    echo [初始化] 首次运行，正在安装依赖（约 1 分钟，仅需一次）...
    %PY% -m pip install -r requirements.txt
    echo.
)

echo [OK] 服务启动中: http://127.0.0.1:8000
echo [OK] 原型页面:   http://127.0.0.1:8000/memory-vortex-prototype-v2-api.html
echo [OK] 接口文档:   http://127.0.0.1:8000/docs
echo.
echo 停止服务：关闭本窗口或按 Ctrl+C
echo.

rem 服务启动 3 秒后自动打开浏览器
start "" cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:8000/memory-vortex-prototype-v2-api.html"

%PY% main.py

echo.
echo [提示] 服务已停止
pause
