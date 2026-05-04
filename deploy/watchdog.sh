#!/bin/bash
# Dashboard Watchdog — 自动检查并恢复服务
# 安装: crontab -e → */2 * * * * /opt/dashboard/watchdog.sh >> /opt/dashboard/watchdog.log 2>&1

LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"
VENV="/opt/dashboard-venv/bin/python"
DIR="/opt/dashboard"

# 1. 检查 server.py
check_server() {
    RESP=$(curl -s --max-time 5 http://localhost:8889/api/dashboard?store=san_gabriel)
    if [ -z "$RESP" ]; then
        echo "$LOG_PREFIX server.py 无响应，正在重启..."
        pkill -f "python.*server.py" 2>/dev/null
        sleep 2
        cd $DIR && nohup $VENV server.py >> /dev/null 2>&1 &
        sleep 3
        # 验证
        RESP2=$(curl -s --max-time 5 http://localhost:8889/api/dashboard?store=san_gabriel)
        if [ -z "$RESP2" ]; then
            echo "$LOG_PREFIX server.py 重启失败!"
        else
            echo "$LOG_PREFIX server.py 重启成功 (PID: $(pgrep -f 'python.*server.py'))"
        fi
    fi
}

# 2. 检查 SG bot
check_sg_bot() {
    if ! pgrep -f "python.*dashboard_bot.py" > /dev/null 2>&1; then
        echo "$LOG_PREFIX SG bot 未运行，正在启动..."
        cd $DIR && nohup $VENV dashboard_bot.py >> /dev/null 2>&1 &
        sleep 2
        echo "$LOG_PREFIX SG bot 已启动 (PID: $(pgrep -f 'python.*dashboard_bot.py'))"
    fi
}

# 3. 检查 AR1 bot
check_ar1_bot() {
    if ! pgrep -f "python.*dashboard_bot_ar1.py" > /dev/null 2>&1; then
        echo "$LOG_PREFIX AR1 bot 未运行，正在启动..."
        cd $DIR && nohup $VENV dashboard_bot_ar1.py >> /dev/null 2>&1 &
        sleep 2
        echo "$LOG_PREFIX AR1 bot 已启动 (PID: $(pgrep -f 'python.*dashboard_bot_ar1.py'))"
    fi
}

check_server
check_sg_bot
check_ar1_bot
