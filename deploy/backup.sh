#!/bin/bash
# iFixForU Dashboard 每日备份
# 备份数据库 + 配置文件，保留 15 天
# cron: 0 2 * * * /opt/dashboard/backup.sh >> /opt/dashboard/backup.log 2>&1

DEPLOY_DIR="/opt/dashboard"
BACKUP_DIR="/opt/dashboard/backups"
KEEP_DAYS=15
DATE=$(date '+%Y%m%d')
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

mkdir -p "$BACKUP_DIR"

TODAY_DIR="$BACKUP_DIR/$DATE"
mkdir -p "$TODAY_DIR"

echo "$LOG_PREFIX 开始备份..."

# 1. 备份数据库
if [ -f "$DEPLOY_DIR/dashboard.db" ]; then
    cp "$DEPLOY_DIR/dashboard.db" "$TODAY_DIR/dashboard.db"
    echo "$LOG_PREFIX 数据库已备份"
fi

# 2. 备份 Python 文件
for f in server.py db.py classifier.py dashboard_bot.py dashboard_bot_ar1.py watchdog.sh .env; do
    if [ -f "$DEPLOY_DIR/$f" ]; then
        cp "$DEPLOY_DIR/$f" "$TODAY_DIR/$f"
    fi
done
echo "$LOG_PREFIX Python 文件已备份"

# 3. 备份 index.html
if [ -f "$DEPLOY_DIR/static/index.html" ]; then
    cp "$DEPLOY_DIR/static/index.html" "$TODAY_DIR/index.html"
    echo "$LOG_PREFIX index.html 已备份"
fi

# 4. 记录当前进程状态
ps aux | grep -E "server.py|dashboard_bot" | grep -v grep > "$TODAY_DIR/processes.txt"

# 5. 记录 crontab
crontab -l > "$TODAY_DIR/crontab.txt" 2>/dev/null

# 6. 清理超过 15 天的备份
find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +$KEEP_DAYS -exec rm -rf {} \;
echo "$LOG_PREFIX 已清理 ${KEEP_DAYS} 天前的备份"

# 统计
TOTAL=$(du -sh "$TODAY_DIR" | cut -f1)
COUNT=$(ls -d "$BACKUP_DIR"/2* 2>/dev/null | wc -l)
echo "$LOG_PREFIX 备份完成: $TODAY_DIR ($TOTAL), 共保留 $COUNT 天"
