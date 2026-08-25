@echo off
setlocal EnableExtensions
title MemoryVortex Local Server
cd /d "%~dp0"

set "URL=http://localhost:8777/memory-vortex-prototype-v2.html"

echo ============================================
echo   记忆胶囊原型 v2.2 (数据分离版)
echo   正在启动本地服务器并打开原型...
echo ============================================
echo.

rem ---------- 0. 若服务器已在运行，直接打开页面 ----------
curl -s -o nul -m 2 "%URL%"
if not errorlevel 1 (
    echo 检测到服务器已在运行，直接打开页面...
    start "" "%URL%"
    goto :end
)

rem ---------- 1. 挑一个真正可用的 Python（排除商店假别名） ----------
set "PY="
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"

if not defined PY (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)

if defined PY (
    echo 使用 %PY% 启动服务器...
    start "MemoryVortex Server" /min cmd /c "%PY% -m http.server 8777 --bind 127.0.0.1"
    goto :wait
)

rem ---------- 2. 回退：node / npx ----------
where node >nul 2>nul
if not errorlevel 1 (
    echo 使用 npx serve 启动服务器...
    start "MemoryVortex Server" /min cmd /c "npx --yes serve -l 8777 ."
    goto :wait
)

echo [错误] 未找到可用的 python 或 node，无法启动本地服务器。
echo 请安装 Python (python.org) 或 Node.js (nodejs.org) 后重试。
echo.
pause
goto :end

rem ---------- 3. 等服务器就绪后再打开浏览器（最多约 15 秒） ----------
:wait
set /a TRIES=0

:waitloop
ping -n 2 127.0.0.1 >nul
curl -s -o nul -m 2 "%URL%"
if not errorlevel 1 goto :open
set /a TRIES+=1
if %TRIES% lss 15 goto :waitloop

echo [错误] 服务器启动超时，请把本窗口截图反馈给开发者。
echo.
pause
goto :end

:open
start "" "%URL%"
echo.
echo 已打开原型页面！本窗口可以关闭。
echo (服务器在最小化的 MemoryVortex Server 窗口中运行，关闭它即停止服务)
ping -n 6 127.0.0.1 >nul

:end
endlocal
