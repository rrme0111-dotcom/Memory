#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════
#  记忆漩涡 MemoryVortex · Oracle Cloud 一键部署脚本
# ══════════════════════════════════════════════════════════════════
#  用法：  sudo bash deploy/setup.sh
#
#  前提：
#    · Ubuntu 22.04 / 24.04（Oracle Cloud Always Free 实例）
#    · 项目代码已上传到服务器（scp 或 git clone）
#    · 脚本位于项目根目录下的 deploy/setup.sh
#
#  脚本自动完成：
#    1. 安装系统依赖（nginx, python3, python3-venv）
#    2. 创建虚拟环境 + 安装 Python 依赖
#    3. 生成 API 令牌
#    4. 创建数据目录 + 静态文件 index.html 软链接
#    5. 安装 Nginx 反代配置
#    6. 安装 systemd 进程守护
#    7. 开放防火墙 80 端口
#    8. 验证服务
# ══════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_DIR/backend"
VENV_DIR="$PROJECT_DIR/venv"

# ── 颜色 ──
G='\033[0;32m'; Y='\033[0;33m'; R='\033[0;31m'; N='\033[0m'

echo -e "${G}════════════════════════════════════════${N}"
echo -e "${G}  记忆漩涡 · 部署脚本${N}"
echo -e "${G}  项目目录: ${PROJECT_DIR}${N}"
echo -e "${G}════════════════════════════════════════${N}"

# ── 检查 root ──
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${R}请用 sudo 运行: sudo bash deploy/setup.sh${N}"
    exit 1
fi

# ── 检查应用目录 ──
if [ ! -f "$APP_DIR/main.py" ]; then
    echo -e "${R}找不到 $APP_DIR/main.py${N}"
    echo -e "${R}请确认项目目录结构：deploy/ 与 backend/ 同级${N}"
    exit 1
fi

# ── 1/8 安装系统依赖 ──
echo -e "${Y}▶ [1/8] 安装系统依赖...${N}"
apt update -qq
DEBIAN_FRONTEND=noninteractive apt install -y -qq nginx python3 python3-venv git iptables-persistent > /dev/null 2>&1
echo -e "  ${G}系统依赖已安装${N}"

# ── 2/8 创建虚拟环境 + 安装依赖 ──
echo -e "${Y}▶ [2/8] 创建 Python 虚拟环境...${N}"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
echo -e "  ${G}Python 依赖已安装${N}"

# ── 3/8 生成 API 令牌 ──
echo -e "${Y}▶ [3/8] 生成 API 令牌...${N}"
TOKEN_FILE="$APP_DIR/auth_token.txt"
if [ ! -f "$TOKEN_FILE" ]; then
    TOKEN=$("$VENV_DIR/bin/python" -c "import secrets; print(secrets.token_hex(16))")
    echo -n "$TOKEN" > "$TOKEN_FILE"
fi
TOKEN=$(cat "$TOKEN_FILE")
echo -e "  ${G}令牌已生成 → backend/auth_token.txt${N}"

# ── 4/8 准备目录与软链接 ──
echo -e "${Y}▶ [4/8] 准备目录与软链接...${N}"
mkdir -p "$APP_DIR/data/uploads"
# 创建 index.html 软链接，让 / 直接返回应用页面
ln -sf memory-vortex-prototype-v2-api.html "$APP_DIR/static/index.html"
chown -R www-data:www-data "$APP_DIR/data"
chown -R www-data:www-data "$APP_DIR/static"
chown www-data:www-data "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
echo -e "  ${G}目录就绪${N}"

# ── 5/8 安装 Nginx 配置 ──
echo -e "${Y}▶ [5/8] 安装 Nginx 反代配置...${N}"
cat > /etc/nginx/conf.d/memory-vortex.conf << NGINX_EOF
server {
    listen 80;
    server_name _;

    # 静态前端（Nginx 直伺，比经 uvicorn 更快）
    location / {
        root ${APP_DIR}/static;
        try_files \$uri \$uri/ /index.html;
    }

    # 上传文件（Nginx 直伺）
    location /uploads/ {
        alias ${APP_DIR}/data/uploads/;
    }

    # 后端 API → uvicorn
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }

    # 上传大小限制（照片/视频）
    client_max_body_size 20m;
}
NGINX_EOF
nginx -t 2>&1 | tail -1
systemctl reload nginx
echo -e "  ${G}Nginx 配置已安装${N}"

# ── 6/8 安装 systemd 进程守护 ──
echo -e "${Y}▶ [6/8] 安装 systemd 进程守护...${N}"
cat > /etc/systemd/system/memory-vortex.service << SVC_EOF
[Unit]
Description=MemoryVortex FastAPI
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=${APP_DIR}
Environment=MC_API_TOKEN=${TOKEN}
ExecStart=${VENV_DIR}/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SVC_EOF
systemctl daemon-reload
systemctl enable --now memory-vortex
echo -e "  ${G}服务已启动${N}"

# ── 7/8 开放防火墙 ──
echo -e "${Y}▶ [7/8] 开放防火墙端口 80...${N}"
# Oracle Cloud Ubuntu 默认 iptables 会阻止 80 端口入站
iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || \
    iptables -I INPUT 5 -p tcp --dport 80 -j ACCEPT
netfilter-persistent save 2>/dev/null || true
echo -e "  ${G}防火墙已放行 80 端口${N}"

# ── 8/8 验证 ──
echo -e "${Y}▶ [8/8] 验证服务...${N}"
sleep 2
if curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
    echo -e "  ${G}FastAPI (uvicorn) 运行正常${N}"
else
    echo -e "  ${R}uvicorn 可能未就绪，检查: systemctl status memory-vortex${N}"
fi
if curl -sf http://127.0.0.1/ > /dev/null 2>&1; then
    echo -e "  ${G}Nginx 反代正常${N}"
else
    echo -e "  ${R}Nginx 反代可能有问题，检查: nginx -t${N}"
fi

# ── 完成 ──
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "未知")
echo ""
echo -e "${G}════════════════════════════════════════${N}"
echo -e "${G}  部署完成！${N}"
echo -e "${G}════════════════════════════════════════${N}"
echo ""
echo "  API 令牌: $TOKEN"
echo "  本地访问: http://127.0.0.1"
echo "  公网 IP:  $PUBLIC_IP"
echo ""
echo -e "  ${Y}最后一步（在 Oracle Cloud 控制台操作）：${N}"
echo "     VCN → Subnet → Security List → Ingress Rules → 添加："
echo "     Source CIDR: 0.0.0.0/0  Protocol: TCP  Dest Port: 80"
echo ""
echo "  完成后浏览器打开: http://$PUBLIC_IP"
echo -e "${G}════════════════════════════════════════${N}"
