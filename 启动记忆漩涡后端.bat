@echo off
setlocal
title MemoryVortex Backend
cd /d "E:\Ai-Lab\07-notebook\backend"

if not exist "E:\Ai-Lab\07-notebook\database_url.secret.txt" (
  echo [WARN] database_url.secret.txt not found - backend will use local SQLite
) else (
  set /p DATABASE_URL=<"E:\Ai-Lab\07-notebook\database_url.secret.txt"
)

echo [1/2] Starting local backend on port 8000 ...
start "memory-backend" cmd /k "py -3.13 main.py"

echo [2/2] Starting Cloudflare tunnel ...
echo The public URL (https://xxxx.trycloudflare.com) shows in the cloudflared window.
echo If it differs from the URL saved in the App: App - My - Server URL - paste the new one.
start "cloudflared" cmd /k "E:\Ai-Lab\tools\cloudflared.exe tunnel --url http://localhost:8000 --no-autoupdate --protocol http2 --edge-ip-version 4"

echo.
echo Keep both windows OPEN. Closing them = App cannot reach the backend.
pause
