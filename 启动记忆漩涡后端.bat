@echo off
chcp 65001 >nul
title MemoryVortex Backend
cd /d E:\Ai-Lab\07-notebook\backend

echo [1/2] 启动本地后端 (localhost:8000)...
start "memory-backend" cmd /c "py -3.13 main.py"

echo [2/2] 启动 Cloudflare 隧道（公网访问入口）...
echo.
echo  隧道网址会显示在弹出的 cloudflared 窗口里（https://xxxx.trycloudflare.com）
echo  如果网址和手机 App 里配置的不一样：
echo    打开 App → 我的 → 服务器地址 → 粘贴新网址 → 保存
echo.
start "cloudflared" cmd /c "E:\Ai-Lab\tools\cloudflared.exe tunnel --url http://localhost:8000 --no-autoupdate"

echo.
echo  两个窗口都保持打开（关闭它们 = 手机 App 无法访问后端）。
echo  本脚本需要电脑开机后手动运行一次。
pause
