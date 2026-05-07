#!/bin/bash
# iFixForU Dashboard Auto-Deploy
# 从 GitHub 拉取最新 deploy/ 目录并重启服务
# cron: */1 * * * * /opt/dashboard/auto-deploy.sh >> /opt/dashboard/deploy.log 2>&1

REPO_DIR="/opt/dashboard-repo"
DEPLOY_DIR="/opt/dashboard"
BRANCH="main"
REPO_URL="https://github.com/infinitumcom/ifixforu-dashboard.git"
VENV="/opt/dashboard-venv/bin/python"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

# flock 互斥锁：防止与 watchdog.sh 同时操作
LOCK_FILE="/tmp/dashboard-ops.lock"
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "$LOG_PREFIX auto-deploy 跳过：另一个操作正在进行"
    exit 0
fi

# 安全停止进程：发 SIGTERM → 等待退出 → 超时则 SIGKILL
safe_stop() {
    local pattern="$1"
    local pid_file="$2"

    # 先通过 PID 文件停止
    if [ -n "$pid_file" ] && [ -f "$DEPLOY_DIR/$pid_file" ]; then
        local pid=$(cat "$DEPLOY_DIR/$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
        fi
    fi

    # 兜底：pkill
    pkill -f "$pattern" 2>/dev/null

    # 等待最多 5 秒确认进程退出
    for i in $(seq 1 5); do
        if ! pgrep -f "$pattern" > /dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done

    # 超时强杀
    pkill -9 -f "$pattern" 2>/dev/null
    sleep 1
}

# 首次克隆
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "$LOG_PREFIX 首次克隆仓库..."
    git clone --depth 1 --branch $BRANCH "$REPO_URL" "$REPO_DIR"
fi

# 拉取最新
cd "$REPO_DIR"
git fetch origin $BRANCH --depth 1 2>/dev/null
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/$BRANCH)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

echo "$LOG_PREFIX 发现新版本: $LOCAL -> $REMOTE"
git reset --hard origin/$BRANCH

# 比对并复制 deploy/ 下的文件
CHANGED=0

for f in server.py db.py classifier.py dashboard_bot.py dashboard_bot_ar1.py watchdog.sh auto-deploy.sh; do
    SRC="$REPO_DIR/deploy/$f"
    DST="$DEPLOY_DIR/$f"
    if [ -f "$SRC" ]; then
        if ! cmp -s "$SRC" "$DST" 2>/dev/null; then
            cp "$SRC" "$DST"
            echo "$LOG_PREFIX 更新: $f"
            CHANGED=1
        fi
    fi
done

# index.html 也同步
SRC_HTML="$REPO_DIR/deploy/static/index.html"
DST_HTML="$DEPLOY_DIR/static/index.html"
if [ -f "$SRC_HTML" ]; then
    if ! cmp -s "$SRC_HTML" "$DST_HTML" 2>/dev/null; then
        cp "$SRC_HTML" "$DST_HTML"
        echo "$LOG_PREFIX 更新: static/index.html"
        CHANGED=1
    fi
fi

# .env 不覆盖（敏感文件）
# logo 等静态资源同步
for f in "$REPO_DIR/deploy/static/"*.png "$REPO_DIR/deploy/static/"*.jpg "$REPO_DIR/deploy/static/"*.svg; do
    [ -f "$f" ] || continue
    BASENAME=$(basename "$f")
    if ! cmp -s "$f" "$DEPLOY_DIR/static/$BASENAME" 2>/dev/null; then
        cp "$f" "$DEPLOY_DIR/static/$BASENAME"
        echo "$LOG_PREFIX 更新: static/$BASENAME"
    fi
done

if [ "$CHANGED" -eq 1 ]; then
    echo "$LOG_PREFIX 文件有变动，重启服务..."

    # 重启 server.py（安全停止后再启动）
    safe_stop "python.*server.py" ""
    cd $DEPLOY_DIR && nohup $VENV server.py >> /dev/null 2>&1 &
    echo "$LOG_PREFIX server.py 已重启 (PID: $!)"

    # 重启 SG bot（清理 PID 文件，安全停止）
    safe_stop 'python.*dashboard_bot\.py$' "dashboard_bot.pid"
    rm -f "$DEPLOY_DIR/dashboard_bot.pid"
    cd $DEPLOY_DIR && nohup $VENV dashboard_bot.py >> /dev/null 2>&1 &
    echo "$LOG_PREFIX SG bot 已重启 (PID: $!)"

    # 重启 AR1 bot
    safe_stop 'python.*dashboard_bot_ar1\.py$' "dashboard_bot_ar1.pid"
    rm -f "$DEPLOY_DIR/dashboard_bot_ar1.pid"
    cd $DEPLOY_DIR && nohup $VENV dashboard_bot_ar1.py >> /dev/null 2>&1 &
    echo "$LOG_PREFIX AR1 bot 已重启 (PID: $!)"

    echo "$LOG_PREFIX 部署完成!"
else
    echo "$LOG_PREFIX 代码有更新但文件无差异"
fi
