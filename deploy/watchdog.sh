#!/bin/bash
# Dashboard Watchdog — 自动检查并恢复服务
# 安装: crontab -e → */2 * * * * /opt/dashboard/watchdog.sh >> /opt/dashboard/watchdog.log 2>&1

# flock 互斥锁：防止 watchdog 与 auto-deploy 同时操作
LOCK_FILE="/tmp/dashboard-ops.lock"
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] watchdog 跳过：另一个操作正在进行"
    exit 0
fi

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
        # 确认进程已死
        while pgrep -f "python.*server.py" > /dev/null 2>&1; do
            sleep 1
        done
        cd $DIR && nohup $VENV server.py >> /dev/null 2>&1 200>&- &
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

# 2. 检查 SG bot（通过 PID 文件 + pgrep 双重检查）
check_sg_bot() {
    PID_FILE="$DIR/dashboard_bot.pid"
    RUNNING=false

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            RUNNING=true
        fi
    fi

    # PID 文件不存在或进程不在，再用 pgrep 兜底
    if [ "$RUNNING" = false ] && pgrep -f "python.*dashboard_bot\.py$" > /dev/null 2>&1; then
        RUNNING=true
    fi

    if [ "$RUNNING" = false ]; then
        echo "$LOG_PREFIX SG bot 未运行，正在启动..."
        rm -f "$PID_FILE"  # 清理残留 PID 文件
        cd $DIR && nohup $VENV dashboard_bot.py >> /dev/null 2>&1 200>&- &
        sleep 2
        echo "$LOG_PREFIX SG bot 已启动 (PID: $(cat "$PID_FILE" 2>/dev/null || pgrep -f 'python.*dashboard_bot\.py$'))"
    fi
}

# 3. 检查 AR1 bot
check_ar1_bot() {
    PID_FILE="$DIR/dashboard_bot_ar1.pid"
    RUNNING=false

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            RUNNING=true
        fi
    fi

    if [ "$RUNNING" = false ] && pgrep -f "python.*dashboard_bot_ar1\.py$" > /dev/null 2>&1; then
        RUNNING=true
    fi

    if [ "$RUNNING" = false ]; then
        echo "$LOG_PREFIX AR1 bot 未运行，正在启动..."
        rm -f "$PID_FILE"
        cd $DIR && nohup $VENV dashboard_bot_ar1.py >> /dev/null 2>&1 200>&- &
        sleep 2
        echo "$LOG_PREFIX AR1 bot 已启动 (PID: $(cat "$PID_FILE" 2>/dev/null || pgrep -f 'python.*dashboard_bot_ar1\.py$'))"
    fi
}

# 4. 检查 LV bot
check_lv_bot() {
    PID_FILE="$DIR/dashboard_bot_lv.pid"
    RUNNING=false

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            RUNNING=true
        fi
    fi

    if [ "$RUNNING" = false ] && pgrep -f "python.*dashboard_bot_lv\.py$" > /dev/null 2>&1; then
        RUNNING=true
    fi

    if [ "$RUNNING" = false ]; then
        echo "$LOG_PREFIX LV bot 未运行，正在启动..."
        rm -f "$PID_FILE"
        cd $DIR && nohup $VENV dashboard_bot_lv.py >> /dev/null 2>&1 200>&- &
        sleep 2
        echo "$LOG_PREFIX LV bot 已启动 (PID: $(cat "$PID_FILE" 2>/dev/null || pgrep -f 'python.*dashboard_bot_lv\.py$'))"
    fi
}

check_server
check_sg_bot
check_ar1_bot
check_lv_bot
