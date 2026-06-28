#!/bin/bash
# ============================================
# 志愿Agent 一键部署脚本
# 在阿里云服务器上以 root 身份执行:
#   bash /root/志愿agent/setup.sh
# ============================================

set -e

IP_PUBLIC="47.105.49.129"
PROJECT_DIR="/root/志愿agent"
DOMAIN=""  # ← 填入你的域名，不填就用 IP 访问

echo "=========================================="
echo " 志愿Agent 部署脚本"
echo "=========================================="

# 1. 检查 Python
echo ""
echo "[1/6] 检查 Python..."
if ! command -v python3 &>/dev/null; then
    echo "安装 Python3..."
    if command -v apt &>/dev/null; then
        apt update && apt install -y python3 python3-pip
    elif command -v yum &>/dev/null; then
        yum install -y python3
    fi
else
    echo "Python3 已安装: $(python3 --version)"
fi

# 2. 安装 Nginx + Certbot
echo ""
echo "[2/6] 安装 Nginx 和 Certbot..."
if command -v apt &>/dev/null; then
    apt install -y nginx certbot python3-certbot-nginx
elif command -v yum &>/dev/null; then
    yum install -y epel-release
    yum install -y nginx certbot python3-certbot-nginx
fi
echo "Nginx: $(nginx -v 2>&1)"

# 3. 检查项目文件
echo ""
echo "[3/6] 检查项目文件..."
if [ ! -f "$PROJECT_DIR/run.py" ]; then
    echo "❌ 找不到 run.py，请确认项目目录: $PROJECT_DIR"
    exit 1
fi
if [ ! -d "$PROJECT_DIR/data" ]; then
    echo "⚠️  警告: data/ 目录不存在，请从本地 scp 传过来"
    echo "   scp -r data root@${IP_PUBLIC}:$PROJECT_DIR/"
fi
if [ ! -d "$PROJECT_DIR/kb" ]; then
    echo "⚠️  警告: kb/ 目录不存在，请从本地 scp 传过来"
    echo "   scp -r kb root@${IP_PUBLIC}:$PROJECT_DIR/"
fi
echo "项目目录: $PROJECT_DIR ✓"

# 4. 配置 systemd
echo ""
echo "[4/6] 配置 systemd 服务..."
cat > /etc/systemd/system/zhiyuan-agent.service << 'EOF'
[Unit]
Description=Zhiyuan Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/志愿agent
ExecStart=/usr/bin/python3 /root/志愿agent/run.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=XUEFENG_HOST=127.0.0.1
Environment=XUEFENG_PORT=8765

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable zhiyuan-agent
systemctl restart zhiyuan-agent

# 等待启动
sleep 2
if systemctl is-active --quiet zhiyuan-agent; then
    echo "服务已启动 ✓"
else
    echo "❌ 服务启动失败，查看日志:"
    journalctl -u zhiyuan-agent --no-pager -n 20
    exit 1
fi

# 5. 配置 Nginx
echo ""
echo "[5/6] 配置 Nginx..."

if [ -n "$DOMAIN" ]; then
    SERVER_NAME="$DOMAIN"
else
    SERVER_NAME="$IP_PUBLIC"
fi

# 先配置 HTTP 反代（不重定向 HTTPS，因为没有域名就没有证书）
cat > /etc/nginx/conf.d/zhiyuan-agent.conf << NGINX_EOF
server {
    listen 80;
    listen [::]:80;
    server_name $SERVER_NAME;

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # SSE 长连接超时
        proxy_read_timeout 300;
        proxy_send_timeout 300;
        proxy_buffering off;
        tcp_nopush on;
        tcp_nodelay on;
    }
}
NGINX_EOF

# 删除默认站点
rm -f /etc/nginx/conf.d/default.conf

nginx -t && systemctl reload nginx
echo "Nginx 配置完成 ✓"

# 6. 如果有域名，申请 HTTPS 证书
echo ""
echo "[6/6] 检查 HTTPS..."
if [ -n "$DOMAIN" ]; then
    echo "域名: $DOMAIN"
    echo "申请 Let's Encrypt 证书..."
    certbot --nginx -d "$DOMAIN" --non-interactive --register-unsafely-without-email --agree-tos || {
        echo "⚠️  证书申请失败，请先手动执行: certbot --nginx -d $DOMAIN"
    }
    echo "HTTPS 已配置 ✓"
else
    echo "没有配置域名，使用 HTTP 访问（建议配置域名后启用 HTTPS）"
    echo "后续可执行: bash /root/志愿agent/setup-https.sh 你的域名"
fi

echo ""
echo "=========================================="
echo " 部署完成！"
echo "=========================================="
echo ""
if [ -n "$DOMAIN" ]; then
    echo "访问地址: https://$DOMAIN"
else
    echo "访问地址: http://$IP_PUBLIC"
fi
echo ""
echo "常用命令:"
echo "  查看日志:   journalctl -u zhiyuan-agent -f"
echo "  重启服务:   systemctl restart zhiyuan-agent"
echo "  停止服务:   systemctl stop zhiyuan-agent"
echo "  Nginx 日志: tail -f /var/log/nginx/access.log"
echo ""
echo "如果后续要添加域名和 HTTPS:"
echo "  1. 在阿里云控制台把域名解析到这个 IP"
echo "  2. 编辑此脚本的 DOMAIN 变量为你的域名"
echo "  3. 重新运行: bash /root/志愿agent/setup.sh"