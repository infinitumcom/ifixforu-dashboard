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

# 比对并复制 deploy/ 下的文件（不含 static/index.html 的整体替换，只同步 Python 文件）
CHANGED=0

for f in server.py db.py classifier.py dashboard_bot.py dashboard_bot_ar1.py watchdog.sh; do
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

    # 重启 server.py
    pkill -f "python.*server.py" 2>/dev/null
    sleep 2
    cd $DEPLOY_DIR && nohup $VENV server.py >> /dev/null 2>&1 &
    echo "$LOG_PREFIX server.py 已重启"

    # 重启 SG bot
    pkill -f "python.*dashboard_bot.py" 2>/dev/null
    sleep 2
    cd $DEPLOY_DIR && nohup $VENV dashboard_bot.py >> /dev/null 2>&1 &
    echo "$LOG_PREFIX SG bot 已重启"

    # 重启 AR1 bot
    pkill -f "python.*dashboard_bot_ar1.py" 2>/dev/null
    sleep 2
    cd $DEPLOY_DIR && nohup $VENV dashboard_bot_ar1.py >> /dev/null 2>&1 &
    echo "$LOG_PREFIX AR1 bot 已重启"

    echo "$LOG_PREFIX 部署完成!"
else
    echo "$LOG_PREFIX 代码有更新但文件无差异"
fi
